import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.bunny import get_bunny_client
from app.core.storage import get_r2_client
from app.modules.course.content_dto import DocumentFinalizeDTO, DocumentUploadCredentialsDTO, VideoUploadCredentialsDTO
from app.modules.course.content_entity import VideoStatusEnum
from app.modules.resource.content_dto import (
    ResourceAttachmentCreateDTO,
    ResourceAttachmentManageReadDTO,
    ResourceAttachmentReadDTO,
    ResourceAttachmentReorderDTO,
    ResourceAttachmentUpdateDTO,
    ResourceDocumentDTO,
    ResourceDocumentManageDTO,
    ResourceLinkDTO,
    ResourceVideoDTO,
    ResourceVideoManageDTO,
)
from app.modules.resource.content_entity import ResourceAttachment, ResourceDocument, ResourceLink, ResourceVideo
from app.modules.resource.content_repository import ResourceContentRepository
from app.modules.resource.entity import Resource, ResourceAttachmentTypeEnum
from app.modules.resource.repository import ResourceRepository
from app.modules.resource.service import ResourceService
from app.modules.user.entity import User, UserTypeEnum


class ResourceContentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ResourceContentRepository(session)
        self.resource_repo = ResourceRepository(session)
        self._r2 = None
        self._bunny = None

    @property
    def r2(self):
        if self._r2 is None:
            self._r2 = get_r2_client()
        return self._r2

    @property
    def bunny(self):
        if self._bunny is None:
            self._bunny = get_bunny_client()
        return self._bunny

    # -- authorization helpers ----------------------------------------------

    async def _authorize_resource(self, resource_id: uuid.UUID, user: User) -> Resource:
        resource = await self.resource_repo.get_by_id(resource_id)
        if resource is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource not found")
        await ResourceService(self.session).ensure_can_manage(resource, user)
        return resource

    async def _authorize_attachment(
        self, attachment_id: uuid.UUID, user: User
    ) -> tuple[Resource, ResourceAttachment]:
        attachment = await self.repo.get_attachment(attachment_id)
        if attachment is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
        resource = await self._authorize_resource(attachment.resource_id, user)
        return resource, attachment

    # -- attachments -------------------------------------------------------

    async def create_attachment(
        self, resource_id: uuid.UUID, payload: ResourceAttachmentCreateDTO, current_user: User
    ) -> tuple[ResourceAttachment, VideoUploadCredentialsDTO | None, DocumentUploadCredentialsDTO | None]:
        resource = await self._authorize_resource(resource_id, current_user)

        attachment = ResourceAttachment(
            resource_id=resource.id,
            attachment_type=payload.attachment_type,
            title=payload.title,
            order_index=payload.order_index,
        )
        self.session.add(attachment)
        await self.session.flush()

        video_credentials: VideoUploadCredentialsDTO | None = None
        document_credentials: DocumentUploadCredentialsDTO | None = None

        if payload.attachment_type == ResourceAttachmentTypeEnum.VIDEO:
            guid = await self.bunny.create_video(payload.title)
            self.session.add(ResourceVideo(attachment_id=attachment.id, bunny_video_guid=guid))
            video_credentials = VideoUploadCredentialsDTO(**self.bunny.build_tus_credentials(guid))
        elif payload.attachment_type == ResourceAttachmentTypeEnum.DOCUMENT:
            if not payload.file_name:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "file_name is required for document attachments")
            storage_key = self.r2.build_resource_document_key(resource.id, payload.file_name)
            self.session.add(
                ResourceDocument(
                    attachment_id=attachment.id,
                    storage_key=storage_key,
                    file_name=payload.file_name,
                    downloadable=payload.downloadable,
                )
            )
            document_credentials = DocumentUploadCredentialsDTO(
                upload_url=self.r2.generate_upload_url(storage_key), storage_key=storage_key
            )
        elif payload.attachment_type == ResourceAttachmentTypeEnum.LINKS:
            if not payload.url:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "url is required for link attachments")
            self.session.add(
                ResourceLink(
                    attachment_id=attachment.id, url=payload.url, label=payload.label, description=payload.description
                )
            )

        await self.session.commit()
        return attachment, video_credentials, document_credentials

    async def update_attachment(
        self, attachment_id: uuid.UUID, payload: ResourceAttachmentUpdateDTO, current_user: User
    ) -> ResourceAttachment:
        _, attachment = await self._authorize_attachment(attachment_id, current_user)

        sub_entity_fields = {"downloadable", "url", "label", "description"}
        for field, value in payload.model_dump(exclude_unset=True, exclude=sub_entity_fields).items():
            setattr(attachment, field, value)

        if "downloadable" in payload.model_fields_set:
            document = await self.repo.get_document_by_attachment(attachment.id)
            if document is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "This attachment is not a document")
            document.downloadable = payload.downloadable

        link_fields = {
            field: getattr(payload, field)
            for field in ("url", "label", "description")
            if field in payload.model_fields_set
        }
        if link_fields:
            link = await self.repo.get_link_by_attachment(attachment.id)
            if link is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "This attachment is not a link")
            for field, value in link_fields.items():
                setattr(link, field, value)

        await self.session.flush()
        await self.session.commit()
        return attachment

    async def delete_attachment(self, attachment_id: uuid.UUID, current_user: User) -> None:
        _, attachment = await self._authorize_attachment(attachment_id, current_user)

        if attachment.attachment_type == ResourceAttachmentTypeEnum.DOCUMENT:
            document = await self.repo.get_document_by_attachment(attachment.id)
            if document:
                self.r2.delete_object(document.storage_key)

        attachment.mark_deleted(current_user.id)
        await self.session.commit()

    async def reorder_attachments(
        self, resource_id: uuid.UUID, payload: ResourceAttachmentReorderDTO, current_user: User
    ) -> None:
        await self._authorize_resource(resource_id, current_user)
        for entry in payload.attachments:
            attachment = await self.repo.get_attachment(entry.id)
            if attachment is not None and attachment.resource_id == resource_id:
                attachment.order_index = entry.order_index
        await self.session.commit()

    # -- document --------------------------------------------------------------

    async def finalize_document(
        self, attachment_id: uuid.UUID, payload: DocumentFinalizeDTO, current_user: User
    ) -> ResourceDocument:
        _, attachment = await self._authorize_attachment(attachment_id, current_user)
        document = await self.repo.get_document_by_attachment(attachment.id)
        if document is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found for this attachment")
        document.is_uploaded = True
        if payload.mime_type is not None:
            document.mime_type = payload.mime_type
        if payload.file_size_bytes is not None:
            document.file_size_bytes = payload.file_size_bytes
        await self.session.flush()
        await self.session.commit()
        return document

    async def get_document_download_url(
        self, slug: str, attachment_id: uuid.UUID, current_user: User | None = None
    ) -> str:
        resource, document = await self._get_accessible_resource_document(slug, attachment_id, current_user)

        if not document.downloadable:
            can_manage = current_user is not None and (
                current_user.user_type == UserTypeEnum.ADMIN or resource.owner_id == current_user.id
            )
            if not can_manage:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "This document is not available for download")

        return self.r2.generate_download_url(document.storage_key)

    async def get_document_view_url(
        self, slug: str, attachment_id: uuid.UUID, current_user: User | None = None
    ) -> str:
        _, document = await self._get_accessible_resource_document(slug, attachment_id, current_user)
        return self.r2.generate_download_url(document.storage_key)

    async def _get_accessible_resource_document(
        self, slug: str, attachment_id: uuid.UUID, current_user: User | None = None
    ) -> tuple[Resource, ResourceDocument]:
        resource = await self.resource_repo.get_by_slug(slug)
        if resource is None or not resource.is_published:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource not found")

        can_access, _ = await ResourceService(self.session).resolve_access(resource, current_user)
        if not can_access:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have access to this resource")

        attachment = await self.repo.get_attachment(attachment_id)
        if attachment is None or attachment.resource_id != resource.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
        document = await self.repo.get_document_by_attachment(attachment.id)
        if document is None or not document.is_uploaded:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not available")

        return resource, document

    # -- video -------------------------------------------------------------------

    async def refresh_video_upload(self, attachment_id: uuid.UUID, current_user: User) -> VideoUploadCredentialsDTO:
        _, attachment = await self._authorize_attachment(attachment_id, current_user)
        video = await self.repo.get_video_by_attachment(attachment.id)
        if video is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found for this attachment")
        return VideoUploadCredentialsDTO(**self.bunny.build_tus_credentials(video.bunny_video_guid))

    async def handle_bunny_webhook(self, video_guid: str, bunny_status: int) -> None:
        from sqlalchemy import select

        stmt = select(ResourceVideo).where(ResourceVideo.bunny_video_guid == video_guid)
        video = (await self.session.execute(stmt)).scalar_one_or_none()
        if video is None:
            return

        if bunny_status == 3:
            video.status = VideoStatusEnum.READY
            video.playback_url = self.bunny.build_playback_url(video_guid)
            video.thumbnail_url = self.bunny.build_thumbnail_url(video_guid)
        elif bunny_status in (5, 6):
            video.status = VideoStatusEnum.FAILED
        else:
            video.status = VideoStatusEnum.PROCESSING
        await self.session.commit()

    # -- assembly for resource detail endpoints ---------------------------------

    async def build_attachments(self, resource_id: uuid.UUID, manage: bool) -> list:
        attachments = await self.repo.list_attachments(resource_id)
        attachment_ids = [a.id for a in attachments]

        videos = {v.attachment_id: v for v in await self.repo.list_videos_for_attachments(attachment_ids)}
        documents = {d.attachment_id: d for d in await self.repo.list_documents_for_attachments(attachment_ids)}
        links = {l.attachment_id: l for l in await self.repo.list_links_for_attachments(attachment_ids)}

        return [
            self._map_attachment(a, videos.get(a.id), documents.get(a.id), links.get(a.id), manage)
            for a in attachments
        ]

    def _map_attachment(
        self,
        attachment: ResourceAttachment,
        video: ResourceVideo | None,
        document: ResourceDocument | None,
        link: ResourceLink | None,
        manage: bool,
    ):
        video_dto = None
        if video is not None:
            video_cls = ResourceVideoManageDTO if manage else ResourceVideoDTO
            playback_url = (
                self.bunny.build_playback_url(video.bunny_video_guid) if video.status == VideoStatusEnum.READY else None
            )
            extra = {"bunny_video_guid": video.bunny_video_guid} if manage else {}
            video_dto = video_cls(
                status=video.status,
                playback_url=playback_url,
                thumbnail_url=video.thumbnail_url if video.status == VideoStatusEnum.READY else None,
                duration_seconds=video.duration_seconds,
                **extra,
            )

        document_dto = None
        if document is not None:
            document_cls = ResourceDocumentManageDTO if manage else ResourceDocumentDTO
            extra = {"storage_key": document.storage_key} if manage else {}
            document_dto = document_cls(
                file_name=document.file_name,
                mime_type=document.mime_type,
                file_size_bytes=document.file_size_bytes,
                is_uploaded=document.is_uploaded,
                downloadable=document.downloadable,
                **extra,
            )

        link_dto = None
        if link is not None:
            link_dto = ResourceLinkDTO(url=link.url, label=link.label, description=link.description)

        attachment_cls = ResourceAttachmentManageReadDTO if manage else ResourceAttachmentReadDTO
        return attachment_cls(
            id=attachment.id,
            created_at=attachment.created_at,
            resource_id=attachment.resource_id,
            title=attachment.title,
            attachment_type=attachment.attachment_type,
            order_index=attachment.order_index,
            video=video_dto,
            document=document_dto,
            link=link_dto,
        )
