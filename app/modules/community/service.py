import uuid
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PaginationParams
from app.core import presence
from app.core.storage import get_r2_client
from app.core.ws_pubsub import channel_name, publish_event
from app.modules.community import membership
from app.modules.course.access_entity import UserCourseAccess
from app.modules.community.dto import (
    CommunityAttachmentKindEnum,
    CommunityAttachmentUploadRequestDTO,
    CommunityAttachmentUploadResponseDTO,
    CommunityMemberReadDTO,
    CommunityMessageCreateDTO,
    CommunityMessageQuoteDTO,
    CommunityMessageReadDTO,
    CommunityOnlineMembersReadDTO,
    CommunityReadDTO,
    CommunityMembersAddDTO,
    CustomCommunityCreateDTO,
)
from app.modules.community.entity import (
    Community,
    CommunityMembership,
    CommunityMembershipAddedViaEnum,
    CommunityMessage,
    CommunityTypeEnum,
)
from app.modules.community.message_repository import CommunityMessageRepository
from app.modules.community.repository import CommunityMembershipRepository, CommunityRepository
from app.modules.resource.dto import ResourceCardDTO
from app.modules.resource.entity import Resource
from app.modules.resource.repository import ResourceRepository
from app.modules.user.dto import UserReadDTO
from app.modules.user.entity import User, UserTypeEnum
from app.modules.user.repository import UserRepository

_PRESENCE_NAMESPACE = "community"
_CHANNEL_NAMESPACE = "community"


def community_channel(community_id: uuid.UUID) -> str:
    return channel_name(_CHANNEL_NAMESPACE, community_id)


class CommunityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = CommunityRepository(session)
        self.membership_repo = CommunityMembershipRepository(session)
        self.message_repo = CommunityMessageRepository(session)
        self.resource_repo = ResourceRepository(session)
        self.user_repo = UserRepository(session)

    # -- lookups / guards ------------------------------------------------------

    async def get_community_entity(self, community_id: uuid.UUID) -> Community | None:
        """Raw lookup (no 404/authorization) - used by the WebSocket handshake in
        `router.py`, which needs to distinguish "not found" from "forbidden" itself
        to close the socket with the right code."""
        return await self.repository.get_by_id(community_id)

    async def _get_community_or_404(self, community_id: uuid.UUID) -> Community:
        community = await self.get_community_entity(community_id)
        if community is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Community not found")
        return community

    async def assert_member(self, community: Community, user: User) -> None:
        if not await membership.is_member(self.session, community, user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not a member of this community")

    async def get_or_create_singleton(self, community_type: CommunityTypeEnum, name: str) -> Community:
        """Defensive get-or-create for the GENERAL/HELP singletons - they're seeded
        by the migration, but this keeps a fresh/dev DB from ever missing them."""
        existing = await self.repository.get_singleton(community_type)
        if existing is not None:
            return existing
        community = Community(type=community_type, name=name)
        await self.repository.create(community)
        await self.session.commit()
        return community

    # -- DTO builders ------------------------------------------------------------

    async def _build_community_dto(
        self, community: Community, with_member_count: bool = False
    ) -> CommunityReadDTO:
        member_count = None
        if with_member_count:
            member_count = len(await membership.list_member_ids(self.session, community))
        return CommunityReadDTO(
            id=community.id,
            type=community.type,
            course_id=community.course_id,
            name=community.name,
            description=community.description,
            is_active=community.is_active,
            member_count=member_count,
            created_at=community.created_at,
        )

    async def _build_message_dto(self, message: CommunityMessage) -> CommunityMessageReadDTO:
        senders, reply_parents, resources = await self.message_repo.bulk_load_context([message])
        return self._message_to_dto(message, senders, reply_parents, resources)

    def _message_to_dto(
        self,
        message: CommunityMessage,
        senders: dict[uuid.UUID, User],
        reply_parents: dict[uuid.UUID, CommunityMessage],
        resources: dict[uuid.UUID, Resource],
    ) -> CommunityMessageReadDTO:
        sender = senders.get(message.sender_id)

        attachment_url = None
        attachment_kind = None
        if message.attachment_storage_key:
            attachment_url = get_r2_client().get_public_url(message.attachment_storage_key)
            attachment_kind = (
                CommunityAttachmentKindEnum.IMAGE
                if (message.attachment_mime_type or "").startswith("image/")
                else CommunityAttachmentKindEnum.DOCUMENT
            )

        reply_to = None
        if message.reply_to_message_id is not None:
            parent = reply_parents.get(message.reply_to_message_id)
            if parent is not None:
                reply_to = CommunityMessageQuoteDTO(
                    id=parent.id,
                    sender_id=parent.sender_id,
                    body=parent.body,
                    attachment_file_name=parent.attachment_file_name,
                )

        resource_reference = None
        if message.resource_reference_id is not None:
            resource = resources.get(message.resource_reference_id)
            if resource is not None:
                resource_reference = ResourceCardDTO.model_validate(resource)

        return CommunityMessageReadDTO(
            id=message.id,
            community_id=message.community_id,
            sender_id=message.sender_id,
            sender=UserReadDTO.model_validate(sender) if sender else None,
            body=message.body,
            created_at=message.created_at,
            reply_to=reply_to,
            attachment_url=attachment_url,
            attachment_file_name=message.attachment_file_name,
            attachment_mime_type=message.attachment_mime_type,
            attachment_file_size_bytes=message.attachment_file_size_bytes,
            attachment_kind=attachment_kind,
            resource_reference=resource_reference,
        )

    # -- listing -----------------------------------------------------------------

    async def list_for_user(self, user: User) -> list[CommunityReadDTO]:
        general = await self.get_or_create_singleton(CommunityTypeEnum.GENERAL, "General")
        help_community = await self.get_or_create_singleton(CommunityTypeEnum.HELP, "Help")
        communities: list[Community] = [general, help_community]

        if user.user_type == UserTypeEnum.ADMIN:
            communities.extend(await self.repository.list_by_type(CommunityTypeEnum.COURSE))
            custom_all, _ = await self.repository.list_custom(PaginationParams(page=1, page_size=1000))
            communities.extend(custom_all)
        else:
            course_ids = await self._accessible_course_ids(user.id)
            communities.extend(await self.repository.list_for_courses(course_ids))

            custom_ids = await self._custom_community_ids_for_user(user.id)
            for community_id in custom_ids:
                custom_community = await self.repository.get_by_id(community_id)
                if custom_community is not None:
                    communities.append(custom_community)

        seen: set[uuid.UUID] = set()
        unique_communities = []
        for community in communities:
            if community.id in seen:
                continue
            seen.add(community.id)
            unique_communities.append(community)

        return [await self._build_community_dto(c) for c in unique_communities]

    async def _accessible_course_ids(self, user_id: uuid.UUID) -> list[uuid.UUID]:
        """Every course `user_id` can see a COURSE community for: enrolled via
        `UserCourseAccess`, the course's owning instructor, or a credited
        co-instructor."""
        from app.modules.course.entity import Course
        from app.modules.course.instructor_entity import CourseInstructor

        enrolled_stmt = select(UserCourseAccess.course_id).where(UserCourseAccess.user_id == user_id)
        owner_stmt = select(Course.id).where(Course.instructor_id == user_id, Course.deleted_at.is_(None))
        co_instructor_stmt = select(CourseInstructor.course_id).where(CourseInstructor.user_id == user_id)

        course_ids: set[uuid.UUID] = set((await self.session.execute(enrolled_stmt)).scalars().all())
        course_ids.update((await self.session.execute(owner_stmt)).scalars().all())
        course_ids.update((await self.session.execute(co_instructor_stmt)).scalars().all())
        return list(course_ids)

    async def _custom_community_ids_for_user(self, user_id: uuid.UUID) -> list[uuid.UUID]:
        stmt = select(CommunityMembership.community_id).where(
            CommunityMembership.deleted_at.is_(None), CommunityMembership.user_id == user_id
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_custom_for_admin(
        self, pagination: PaginationParams, search: str | None = None
    ) -> tuple[list[CommunityReadDTO], int]:
        items, total = await self.repository.list_custom(pagination, search)
        return [await self._build_community_dto(c, with_member_count=True) for c in items], total

    async def get_community(self, community_id: uuid.UUID, user: User) -> CommunityReadDTO:
        community = await self._get_community_or_404(community_id)
        await self.assert_member(community, user)
        return await self._build_community_dto(community, with_member_count=True)

    # -- custom community management ----------------------------------------------

    async def _snapshot_course_ids(self, course_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[uuid.UUID]]:
        """course_id -> its current enrollee+instructor user ids, for the
        "add a course's current enrollees" snapshot mechanic."""
        result: dict[uuid.UUID, list[uuid.UUID]] = {}
        for course_id in course_ids:
            result[course_id] = await membership.list_course_member_ids(self.session, course_id)
        return result

    async def create_custom(self, payload: CustomCommunityCreateDTO, admin: User) -> CommunityReadDTO:
        community = Community(
            type=CommunityTypeEnum.CUSTOM,
            name=payload.name,
            description=payload.description,
            created_by=admin.id,
        )
        await self.repository.create(community)

        if payload.user_ids:
            await self.membership_repo.add_members(
                community.id, payload.user_ids, CommunityMembershipAddedViaEnum.MANUAL
            )

        if payload.course_snapshot_ids:
            snapshots = await self._snapshot_course_ids(payload.course_snapshot_ids)
            for course_id, user_ids in snapshots.items():
                await self.membership_repo.add_members(
                    community.id, user_ids, CommunityMembershipAddedViaEnum.COURSE_SNAPSHOT, course_id
                )

        await self.session.commit()
        return await self._build_community_dto(community, with_member_count=True)

    async def add_members(self, community_id: uuid.UUID, payload: CommunityMembersAddDTO, admin: User) -> None:
        community = await self._get_community_or_404(community_id)
        if community.type != CommunityTypeEnum.CUSTOM:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only custom communities support manual membership")

        if payload.user_ids:
            await self.membership_repo.add_members(
                community.id, payload.user_ids, CommunityMembershipAddedViaEnum.MANUAL
            )

        if payload.course_snapshot_id is not None:
            user_ids = await membership.list_course_member_ids(self.session, payload.course_snapshot_id)
            await self.membership_repo.add_members(
                community.id, user_ids, CommunityMembershipAddedViaEnum.COURSE_SNAPSHOT, payload.course_snapshot_id
            )

        await self.session.commit()

    async def remove_member(self, community_id: uuid.UUID, user_id: uuid.UUID, admin: User) -> None:
        community = await self._get_community_or_404(community_id)
        if community.type != CommunityTypeEnum.CUSTOM:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only custom communities support manual membership")
        removed = await self.membership_repo.remove_membership(community.id, user_id)
        if not removed:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "This user is not a member of the community")
        await self.session.commit()

    async def list_members(
        self, community_id: uuid.UUID, pagination: PaginationParams, requester: User
    ) -> tuple[list[CommunityMemberReadDTO], int]:
        community = await self._get_community_or_404(community_id)
        await self.assert_member(community, requester)

        member_ids = await membership.list_member_ids(self.session, community)
        total = len(member_ids)
        start = pagination.offset
        end = start + pagination.limit
        page_ids = member_ids[start:end]

        rows: list[CommunityMemberReadDTO] = []
        if page_ids:
            online_ids = set(await presence.online_subset(_PRESENCE_NAMESPACE, page_ids))
            membership_by_user: dict[uuid.UUID, tuple[CommunityMembershipAddedViaEnum | None, uuid.UUID | None]] = {}
            if community.type == CommunityTypeEnum.CUSTOM:
                membership_rows, _ = await self.membership_repo.list_membership_rows(
                    community.id, PaginationParams(page=1, page_size=len(page_ids) or 1)
                )
                membership_by_user = {
                    m.user_id: (m.added_via, m.added_from_course_id) for m in membership_rows
                }

            for user_id in page_ids:
                user = await self.user_repo.get_by_id(user_id)
                if user is None:
                    continue
                added_via, added_from_course_id = membership_by_user.get(user_id, (None, None))
                rows.append(
                    CommunityMemberReadDTO(
                        user=UserReadDTO.model_validate(user),
                        added_via=added_via,
                        added_from_course_id=added_from_course_id,
                        is_online=user_id in online_ids,
                    )
                )
        return rows, total

    # -- attachments ---------------------------------------------------------------

    async def get_attachment_upload_url(
        self, community_id: uuid.UUID, payload: CommunityAttachmentUploadRequestDTO, user: User
    ) -> CommunityAttachmentUploadResponseDTO:
        community = await self._get_community_or_404(community_id)
        await self.assert_member(community, user)

        r2 = get_r2_client()
        storage_key = r2.build_community_attachment_key(community.id, payload.file_name)
        upload_url = r2.generate_upload_url(storage_key, payload.content_type)
        return CommunityAttachmentUploadResponseDTO(upload_url=upload_url, storage_key=storage_key)

    # -- messaging -----------------------------------------------------------------

    async def post_message(
        self, community_id: uuid.UUID, payload: CommunityMessageCreateDTO, user: User
    ) -> CommunityMessageReadDTO:
        community = await self._get_community_or_404(community_id)
        await self.assert_member(community, user)

        if payload.reply_to_message_id is not None:
            parent = await self.message_repo.get_message_by_id(payload.reply_to_message_id)
            if parent is None or parent.community_id != community.id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "The message being replied to was not found")

        if payload.resource_reference_id is not None:
            resource = await self.resource_repo.get_by_id(payload.resource_reference_id)
            if resource is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "The shared resource was not found")

        message = CommunityMessage(
            community_id=community.id,
            sender_id=user.id,
            body=payload.body,
            reply_to_message_id=payload.reply_to_message_id,
            resource_reference_id=payload.resource_reference_id,
            attachment_storage_key=payload.attachment_storage_key,
            attachment_file_name=payload.attachment_file_name,
            attachment_mime_type=payload.attachment_mime_type,
            attachment_file_size_bytes=payload.attachment_file_size_bytes,
        )
        await self.message_repo.create(message)
        await self.session.commit()

        message_dto = await self._build_message_dto(message)
        await publish_event(
            _CHANNEL_NAMESPACE, community.id, {"type": "message", "data": message_dto.model_dump(mode="json")}
        )
        return message_dto

    async def list_messages(
        self, community_id: uuid.UUID, user: User, pagination: PaginationParams
    ) -> tuple[list[CommunityMessageReadDTO], int]:
        community = await self._get_community_or_404(community_id)
        await self.assert_member(community, user)

        items, total = await self.message_repo.list_for_community(community_id, pagination)
        senders, reply_parents, resources = await self.message_repo.bulk_load_context(items)
        return [self._message_to_dto(m, senders, reply_parents, resources) for m in items], total

    # -- presence ------------------------------------------------------------------

    async def list_online_members(self, community_id: uuid.UUID, user: User) -> CommunityOnlineMembersReadDTO:
        community = await self._get_community_or_404(community_id)
        await self.assert_member(community, user)
        member_ids = await membership.list_member_ids(self.session, community)
        online_ids = await presence.online_subset(_PRESENCE_NAMESPACE, member_ids)
        return CommunityOnlineMembersReadDTO(online_user_ids=online_ids)
