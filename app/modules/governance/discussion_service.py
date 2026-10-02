import re
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import get_r2_client
from app.modules.governance.dto import (
    EvidenceFinalizeDTO,
    EvidenceLinkCreateDTO,
    EvidenceUploadRequestDTO,
    EvidenceUploadResponseDTO,
    ReviewCommentCreateDTO,
    ReviewCommentReadDTO,
    ReviewEvidenceReadDTO,
)
from app.modules.governance.entity import CourseRevision, ReviewComment, ReviewEvidence
from app.modules.governance.enums import CLOSED_STATUSES
from app.modules.governance.notifier import GovernanceNotifier
from app.modules.governance.presenter import UserDirectory
from app.modules.governance.revision_service import RevisionService, stage_views
from app.modules.governance.workflow import current_stage
from app.modules.notification.entity import NotificationTypeEnum
from app.modules.user.entity import User

_ANCHOR_TYPES = {"course", "section", "item", "question"}


class DiscussionService:
    """Review comments (threaded, optionally anchored to one part of the course)
    and supporting evidence. Anyone who can view the revision may take part."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.revisions = RevisionService(session)

    async def _load(self, revision_id: uuid.UUID, actor: User) -> CourseRevision:
        revision = await self.revisions.get_revision(revision_id)
        course = await self.revisions.get_course(revision.course_id)
        await self.revisions.ensure_can_view(actor, course)
        return revision

    async def _current_stage_id(self, revision: CourseRevision) -> uuid.UUID | None:
        current = current_stage(stage_views(await self.revisions.round_stages(revision)))
        return current.id if current else None

    # -- comments ----------------------------------------------------------------------

    async def list_comments(self, revision_id: uuid.UUID, actor: User) -> list[ReviewCommentReadDTO]:
        await self._load(revision_id, actor)
        rows = (
            await self.session.execute(
                select(ReviewComment)
                .where(ReviewComment.revision_id == revision_id, ReviewComment.deleted_at.is_(None))
                .order_by(ReviewComment.created_at)
            )
        ).scalars().all()
        users = UserDirectory(self.session)
        await users.load(r.author_id for r in rows)
        return [_comment_dto(r, users) for r in rows]

    async def add_comment(
        self, revision_id: uuid.UUID, payload: ReviewCommentCreateDTO, actor: User
    ) -> ReviewCommentReadDTO:
        revision = await self._load(revision_id, actor)
        if revision.status in CLOSED_STATUSES:
            raise HTTPException(status.HTTP_409_CONFLICT, "This revision is closed")
        if payload.anchor_type is not None and payload.anchor_type not in _ANCHOR_TYPES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"anchor_type must be one of {sorted(_ANCHOR_TYPES)}")
        if payload.parent_id is not None:
            parent = await self.session.get(ReviewComment, payload.parent_id)
            if parent is None or parent.revision_id != revision.id:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Parent comment not found")

        comment = ReviewComment(
            revision_id=revision.id,
            stage_id=await self._current_stage_id(revision),
            parent_id=payload.parent_id,
            author_id=actor.id,
            body=payload.body,
            anchor_type=payload.anchor_type,
            anchor_id=payload.anchor_id,
            created_by=actor.id,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(comment)
        await self.session.commit()

        # Everyone involved so far hears about it, except the commenter.
        notifier = GovernanceNotifier(self.session)
        stages = await self.revisions.all_stages(revision)
        involved = {*await self.revisions.contributor_ids(revision)}
        involved |= {s.assigned_reviewer_id for s in stages if s.assigned_reviewer_id}
        involved |= {s.decided_by for s in stages if s.decided_by}
        course = await self.revisions.get_course(revision.course_id)
        notifier.queue(
            involved, NotificationTypeEnum.REVIEW_COMMENT_ADDED,
            f"New review comment: {course.title}", payload.body[:200],
            f"/dashboard/approval-centre/revisions/{revision.id}", exclude={actor.id},
            revision_id=revision.id,
        )
        await notifier.flush()

        users = UserDirectory(self.session)
        await users.load([actor.id])
        return _comment_dto(comment, users)

    async def resolve_comment(self, comment_id: uuid.UUID, actor: User) -> ReviewCommentReadDTO:
        comment = await self.session.get(ReviewComment, comment_id)
        if comment is None or comment.deleted_at is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found")
        await self._load(comment.revision_id, actor)
        comment.resolved_at = datetime.now(timezone.utc)
        comment.resolved_by = actor.id
        await self.session.commit()
        users = UserDirectory(self.session)
        await users.load([comment.author_id])
        return _comment_dto(comment, users)

    # -- evidence ----------------------------------------------------------------------

    async def list_evidence(self, revision_id: uuid.UUID, actor: User) -> list[ReviewEvidenceReadDTO]:
        await self._load(revision_id, actor)
        rows = (
            await self.session.execute(
                select(ReviewEvidence)
                .where(ReviewEvidence.revision_id == revision_id, ReviewEvidence.deleted_at.is_(None))
                .order_by(ReviewEvidence.created_at)
            )
        ).scalars().all()
        users = UserDirectory(self.session)
        await users.load(r.uploaded_by for r in rows)
        r2 = get_r2_client() if any(r.storage_key and r.is_uploaded for r in rows) else None
        return [_evidence_dto(r, users, r2) for r in rows]

    async def request_upload(
        self, revision_id: uuid.UUID, payload: EvidenceUploadRequestDTO, actor: User
    ) -> EvidenceUploadResponseDTO:
        revision = await self._load(revision_id, actor)
        if revision.status in CLOSED_STATUSES:
            raise HTTPException(status.HTTP_409_CONFLICT, "This revision is closed")
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", payload.file_name)[:200]
        storage_key = f"governance/{revision.course_id}/{revision.id}/{uuid.uuid4()}-{safe_name}"
        evidence = ReviewEvidence(
            revision_id=revision.id,
            stage_id=await self._current_stage_id(revision),
            uploaded_by=actor.id,
            title=payload.title,
            storage_key=storage_key,
            file_name=payload.file_name,
            mime_type=payload.content_type,
            is_uploaded=False,
            created_by=actor.id,
        )
        self.session.add(evidence)
        await self.session.flush()
        upload_url = get_r2_client().generate_upload_url(storage_key, payload.content_type)
        await self.session.commit()
        return EvidenceUploadResponseDTO(evidence_id=evidence.id, upload_url=upload_url, storage_key=storage_key)

    async def finalize_upload(
        self, evidence_id: uuid.UUID, payload: EvidenceFinalizeDTO, actor: User
    ) -> ReviewEvidenceReadDTO:
        evidence = await self.session.get(ReviewEvidence, evidence_id)
        if evidence is None or evidence.deleted_at is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Evidence not found")
        if evidence.uploaded_by != actor.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the uploader can finalize this evidence")
        evidence.is_uploaded = True
        if payload.mime_type is not None:
            evidence.mime_type = payload.mime_type
        if payload.file_size_bytes is not None:
            evidence.file_size_bytes = payload.file_size_bytes
        await self.session.commit()
        users = UserDirectory(self.session)
        await users.load([actor.id])
        return _evidence_dto(evidence, users, get_r2_client())

    async def add_link(
        self, revision_id: uuid.UUID, payload: EvidenceLinkCreateDTO, actor: User
    ) -> ReviewEvidenceReadDTO:
        revision = await self._load(revision_id, actor)
        if revision.status in CLOSED_STATUSES:
            raise HTTPException(status.HTTP_409_CONFLICT, "This revision is closed")
        evidence = ReviewEvidence(
            revision_id=revision.id,
            stage_id=await self._current_stage_id(revision),
            uploaded_by=actor.id,
            title=payload.title,
            url=payload.url,
            is_uploaded=True,
            created_by=actor.id,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(evidence)
        await self.session.commit()
        users = UserDirectory(self.session)
        await users.load([actor.id])
        return _evidence_dto(evidence, users, None)


def _comment_dto(comment: ReviewComment, users: UserDirectory) -> ReviewCommentReadDTO:
    return ReviewCommentReadDTO(
        id=comment.id,
        created_at=comment.created_at,
        revision_id=comment.revision_id,
        stage_id=comment.stage_id,
        parent_id=comment.parent_id,
        author=users.get(comment.author_id),
        body=comment.body,
        anchor_type=comment.anchor_type,
        anchor_id=comment.anchor_id,
        resolved_at=comment.resolved_at,
        resolved_by=comment.resolved_by,
    )


def _evidence_dto(evidence: ReviewEvidence, users: UserDirectory, r2) -> ReviewEvidenceReadDTO:
    download_url = None
    if evidence.storage_key and evidence.is_uploaded and r2 is not None:
        download_url = r2.generate_download_url(evidence.storage_key)
    return ReviewEvidenceReadDTO(
        id=evidence.id,
        created_at=evidence.created_at,
        stage_id=evidence.stage_id,
        uploaded_by=users.get(evidence.uploaded_by),
        title=evidence.title,
        url=evidence.url,
        file_name=evidence.file_name,
        mime_type=evidence.mime_type,
        file_size_bytes=evidence.file_size_bytes,
        is_uploaded=evidence.is_uploaded,
        download_url=download_url,
    )
