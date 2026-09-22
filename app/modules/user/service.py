import uuid
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PaginationParams
from app.core.storage import get_r2_client
from app.modules.notification.service import NotificationService
from app.modules.user.dto import (
    CvDownloadResponseDTO,
    CvUploadRequestDTO,
    CvUploadResponseDTO,
    InstructorDocumentReadDTO,
    InstructorDocumentUpdateDTO,
    InstructorDocumentUploadRequestDTO,
    InstructorDocumentUploadResponseDTO,
    ProfilePictureUploadRequest,
    ProfilePictureUploadResponse,
    UserFilterParams,
    UserUpdateDTO,
)
from app.modules.user.entity import InstructorDocument, User
from app.modules.user.repository import InstructorDocumentRepository, UserRepository


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = UserRepository(session)
        self.document_repository = InstructorDocumentRepository(session)

    async def update_profile(self, user: User, payload: UserUpdateDTO) -> User:
        if payload.username and payload.username.lower() != user.username.lower():
            if await self.repository.username_exists(payload.username):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, 
                    detail="Username already taken"
                )
                
        updates = payload.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(user, field, value)

        await self.repository.update(user)
        await self.session.commit()
        return user

    async def generate_profile_picture_upload_url(
        self, user: User, payload: ProfilePictureUploadRequest
    ) -> ProfilePictureUploadResponse:
        r2_client = get_r2_client()

        if user.profile_picture_url:
            from app.core.config import settings
            old_key = user.profile_picture_url.replace(f"{settings.r2_public_url.rstrip('/')}/", "")
            r2_client.delete_object(old_key)

        avatar_key = r2_client.build_avatar_key(user.id, payload.file_name)
        upload_url = r2_client.generate_upload_url(avatar_key, payload.content_type)

        public_url = r2_client.get_public_url(avatar_key)
        user.profile_picture_url = public_url
        await self.repository.update(user)
        await self.session.commit()
        await NotificationService(self.session).notify_profile_picture_updated(user)

        return ProfilePictureUploadResponse(upload_url=upload_url, profile_picture_url=public_url)

    async def list(
        self, pagination: PaginationParams, filters: UserFilterParams | None = None
    ) -> tuple[Sequence[User], int]:
        return await self.repository.list(pagination, filters)

    async def get_by_id(self, id: str) -> User | None:
        return await self.repository.get_by_id(id)

    async def set_suspend_status(self, user: User, is_suspended: bool) -> User:
        user.is_suspended = is_suspended
        await self.repository.update(user)
        await self.session.commit()
        notifications = NotificationService(self.session)
        if is_suspended:
            await notifications.notify_account_suspended(user)
        else:
            await notifications.notify_account_unsuspended(user)
        return user

    async def update_role(self, user: User, role: str) -> User:
        user.user_type = role
        await self.repository.update(user)
        await self.session.commit()
        await NotificationService(self.session).notify_role_changed(user, role)
        return user

    # -- instructor CV -----------------------------------------------------------

    async def generate_cv_upload_url(self, user: User, payload: CvUploadRequestDTO) -> CvUploadResponseDTO:
        r2_client = get_r2_client()

        if user.cv_storage_key:
            r2_client.delete_object(user.cv_storage_key)

        storage_key = r2_client.build_user_cv_key(user.id, payload.file_name)
        upload_url = r2_client.generate_upload_url(storage_key, payload.content_type)

        user.cv_storage_key = storage_key
        user.cv_file_name = payload.file_name
        await self.repository.update(user)
        await self.session.commit()

        return CvUploadResponseDTO(upload_url=upload_url, cv_file_name=payload.file_name)

    async def get_cv_download_url(self, user: User) -> CvDownloadResponseDTO:
        if not user.cv_storage_key or not user.cv_file_name:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No CV has been uploaded yet")

        download_url = get_r2_client().generate_download_url(user.cv_storage_key)
        return CvDownloadResponseDTO(download_url=download_url, cv_file_name=user.cv_file_name)

    # -- instructor documents -----------------------------------------------------

    def _document_to_dto(self, document: InstructorDocument) -> InstructorDocumentReadDTO:
        return InstructorDocumentReadDTO(
            id=document.id,
            name=document.name,
            file_name=document.file_name,
            mime_type=document.mime_type,
            file_size_bytes=document.file_size_bytes,
            download_url=get_r2_client().generate_download_url(document.storage_key),
            created_at=document.created_at,
            updated_at=document.updated_at,
            deleted_at=document.deleted_at,
            restored_at=document.restored_at,
            created_by=document.created_by,
            updated_by=document.updated_by,
            deleted_by=document.deleted_by,
            restored_by=document.restored_by,
        )

    async def list_documents(self, user: User) -> Sequence[InstructorDocumentReadDTO]:
        documents = await self.document_repository.list_for_user(user.id)
        return [self._document_to_dto(d) for d in documents]

    async def create_document_upload_url(
        self, user: User, payload: InstructorDocumentUploadRequestDTO
    ) -> InstructorDocumentUploadResponseDTO:
        r2_client = get_r2_client()
        storage_key = r2_client.build_instructor_document_key(user.id, payload.file_name)

        document = InstructorDocument(
            user_id=user.id,
            name=payload.name,
            storage_key=storage_key,
            file_name=payload.file_name,
            mime_type=payload.content_type,
        )
        await self.document_repository.create(document)
        await self.session.commit()

        upload_url = r2_client.generate_upload_url(storage_key, payload.content_type)
        return InstructorDocumentUploadResponseDTO(document_id=document.id, upload_url=upload_url)

    async def replace_document_file(
        self, user: User, document_id: uuid.UUID, payload: InstructorDocumentUploadRequestDTO
    ) -> InstructorDocumentUploadResponseDTO:
        document = await self._get_document_or_404(user.id, document_id)

        r2_client = get_r2_client()
        r2_client.delete_object(document.storage_key)

        storage_key = r2_client.build_instructor_document_key(user.id, payload.file_name)
        document.name = payload.name
        document.storage_key = storage_key
        document.file_name = payload.file_name
        document.mime_type = payload.content_type
        await self.document_repository.update(document)
        await self.session.commit()

        upload_url = r2_client.generate_upload_url(storage_key, payload.content_type)
        return InstructorDocumentUploadResponseDTO(document_id=document.id, upload_url=upload_url)

    async def update_document(
        self, user: User, document_id: uuid.UUID, payload: InstructorDocumentUpdateDTO
    ) -> InstructorDocumentReadDTO:
        document = await self._get_document_or_404(user.id, document_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(document, field, value)
        await self.document_repository.update(document)
        await self.session.commit()
        return self._document_to_dto(document)

    async def delete_document(self, user: User, document_id: uuid.UUID) -> None:
        document = await self._get_document_or_404(user.id, document_id)
        get_r2_client().delete_object(document.storage_key)
        await self.document_repository.soft_delete(document, user.id)
        await self.session.commit()

    async def _get_document_or_404(self, user_id: uuid.UUID, document_id: uuid.UUID) -> InstructorDocument:
        document = await self.document_repository.get_for_user(document_id, user_id)
        if document is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
        return document
