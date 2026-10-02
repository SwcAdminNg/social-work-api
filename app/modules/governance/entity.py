import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_entity import BaseEntity
from app.core.database import Base
from app.modules.governance.enums import (
    ContentStatusEnum,
    ReviewDecisionEnum,
    ReviewStageEnum,
    ReviewStageStatusEnum,
    RevisionKindEnum,
    RiskLevelEnum,
)
from app.modules.governance.permissions import StaffRoleEnum


class StaffRoleAssignment(BaseEntity):
    """Grants one governance role to a user, either platform-wide (`course_id`
    null) or for a single course (e.g. Course Lead of course X). A user can hold
    several rows. Revoking stamps `revoked_at` instead of deleting, so the grant
    history stays auditable."""

    __tablename__ = "staff_role_assignments"
    __table_args__ = (
        # One active grant per (user, role, scope). Revoked rows don't count, so a
        # role can be re-granted later. NULL course_id is coalesced so two global
        # grants of the same role still collide.
        Index(
            "uq_staff_role_assignment_active",
            "user_id",
            "role",
            text("coalesce(course_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            unique=True,
            postgresql_where=text("revoked_at IS NULL AND deleted_at IS NULL"),
        ),
        Index("ix_staff_role_assignments_role_course", "role", "course_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[StaffRoleEnum] = mapped_column(
        Enum(StaffRoleEnum, name="staff_role_enum", native_enum=True), nullable=False
    )
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=True, index=True
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class GovernanceAuditLog(Base):
    """Append-only record of every governance decision (framework section 7:
    who acted, on what item and version, when, the decision, the rationale and
    the resulting status). Deliberately not a BaseEntity - there is nothing to
    soft-delete or update, and a database trigger (see the migration) rejects
    UPDATE and DELETE outright."""

    __tablename__ = "governance_audit_log"
    __table_args__ = (
        Index("ix_governance_audit_log_course_occurred", "course_id", "occurred_at"),
        Index("ix_governance_audit_log_entity", "entity_type", "entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    # Snapshot of the actor's permission codes at the moment they acted - roles
    # can be revoked later, this keeps "were they allowed to?" answerable.
    actor_permissions: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    course_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    revision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    version_label: Mapped[str | None] = mapped_column(String(20), nullable=True)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(60), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(60), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class CourseRevision(BaseEntity):
    """One proposed change to a course travelling through review - the unit the
    Approval Centre lists. For a never-published course the live rows *are* the
    draft (kind INITIAL); for a published course its sections/items are cloned
    into a hidden working copy tagged with this revision's id (kind CHANGE)."""

    __tablename__ = "course_revisions"
    __table_args__ = (
        # At most one open working copy per course.
        Index(
            "uq_course_open_revision",
            "course_id",
            unique=True,
            postgresql_where=text(
                "status NOT IN ('PUBLISHED','ARCHIVED','REJECTED','WITHDRAWN') AND deleted_at IS NULL"
            ),
        ),
        Index("ix_course_revisions_status", "status"),
    )

    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False, index=True
    )
    kind: Mapped[RevisionKindEnum] = mapped_column(
        Enum(RevisionKindEnum, name="revision_kind_enum", native_enum=True), nullable=False
    )
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    status: Mapped[ContentStatusEnum] = mapped_column(
        Enum(ContentStatusEnum, name="content_status_enum", native_enum=True),
        nullable=False,
        default=ContentStatusEnum.DRAFT,
    )
    current_stage: Mapped[ReviewStageEnum | None] = mapped_column(
        Enum(ReviewStageEnum, name="review_stage_enum", native_enum=True), nullable=True
    )
    # Increments each time the author resubmits after a return; stage rows are per round.
    round: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    computed_risk: Mapped[RiskLevelEnum | None] = mapped_column(
        Enum(RiskLevelEnum, name="risk_level_enum", native_enum=True), nullable=True
    )
    declared_risk: Mapped[RiskLevelEnum | None] = mapped_column(
        Enum(RiskLevelEnum, name="risk_level_enum", native_enum=True), nullable=True
    )
    effective_risk: Mapped[RiskLevelEnum | None] = mapped_column(
        Enum(RiskLevelEnum, name="risk_level_enum", native_enum=True), nullable=True
    )
    risk_flags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list, server_default="{}")
    risk_reasons: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list, server_default="{}")
    # Head of Learning lowered the risk below what was computed (audited).
    risk_override_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    risk_override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    touches_assessment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    required_stages: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list, server_default="{}")

    base_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    proposed_version_label: Mapped[str | None] = mapped_column(String(20), nullable=True)
    published_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # ROLLBACK revisions: the version whose content is being restored.
    rollback_to_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Pending edits to the course row's academic fields (title, description,
    # learning outcomes, certificate settings...) - applied on publish.
    course_changes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    # The change list captured at (re)submission, so the diff stays viewable even
    # after the working copy is merged or discarded.
    diff_snapshot: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Optimistic concurrency token - bumped on every workflow transition.
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class RevisionContributor(BaseEntity):
    """Everyone who edited the working copy. Separation of duties treats every
    contributor as an author: none of them may approve any stage of it."""

    __tablename__ = "revision_contributors"
    __table_args__ = (UniqueConstraint("revision_id", "user_id", name="uq_revision_contributor"),)

    revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_revisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    first_edit_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_edit_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReviewStage(BaseEntity):
    """One required review stage of one round of a revision."""

    __tablename__ = "review_stages"
    __table_args__ = (
        UniqueConstraint("revision_id", "round", "stage", name="uq_review_stage_round"),
        Index("ix_review_stages_open", "status", "stage"),
    )

    revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_revisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[ReviewStageEnum] = mapped_column(
        Enum(ReviewStageEnum, name="review_stage_enum", native_enum=True), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ReviewStageStatusEnum] = mapped_column(
        Enum(ReviewStageStatusEnum, name="review_stage_status_enum", native_enum=True),
        nullable=False,
        default=ReviewStageStatusEnum.PENDING,
    )
    assigned_reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # "Approve with minor changes" conditions the next stage must confirm.
    conditions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")


class ReviewDecision(BaseEntity):
    """Immutable, typed log of every decision (the audit log holds the same
    facts generically; this table backs the Approval Centre's recent views)."""

    __tablename__ = "review_decisions"
    __table_args__ = (Index("ix_review_decisions_actor_created", "actor_id", "created_at"),)

    revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_revisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("review_stages.id", ondelete="SET NULL"), nullable=True
    )
    stage: Mapped[ReviewStageEnum | None] = mapped_column(
        Enum(ReviewStageEnum, name="review_stage_enum", native_enum=True), nullable=True
    )
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[ReviewDecisionEnum] = mapped_column(
        Enum(ReviewDecisionEnum, name="review_decision_enum", native_enum=True), nullable=False
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    conditions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    from_status: Mapped[ContentStatusEnum] = mapped_column(
        Enum(ContentStatusEnum, name="content_status_enum", native_enum=True), nullable=False
    )
    to_status: Mapped[ContentStatusEnum] = mapped_column(
        Enum(ContentStatusEnum, name="content_status_enum", native_enum=True), nullable=False
    )
    version_label: Mapped[str | None] = mapped_column(String(20), nullable=True)


class ReviewComment(BaseEntity):
    """Threaded reviewer/author discussion, optionally anchored to one part of
    the course (section/item/question by its live identity id)."""

    __tablename__ = "review_comments"

    revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_revisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("review_stages.id", ondelete="SET NULL"), nullable=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("review_comments.id", ondelete="CASCADE"), nullable=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    anchor_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    anchor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class ReviewEvidence(BaseEntity):
    """A file or link a reviewer attaches to support their decision."""

    __tablename__ = "review_evidence"

    revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_revisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("review_stages.id", ondelete="SET NULL"), nullable=True
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_uploaded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")


class CourseVersion(BaseEntity):
    """A published release of a course (1.0 initial, 1.1 minor, 2.0 major).
    Never overwritten: each publish adds a row with a full JSON snapshot of the
    content as learners saw it, used for history, diffing and rollback."""

    __tablename__ = "course_versions"
    __table_args__ = (UniqueConstraint("course_id", "major", "minor", name="uq_course_version"),)

    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False, index=True
    )
    major: Mapped[int] = mapped_column(Integer, nullable=False)
    minor: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(20), nullable=False)
    revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_revisions.id"), nullable=True
    )
    # Null only for the pre-governance baseline until the backfill script (or the
    # first working copy) captures it.
    snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewer_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_level: Mapped[RiskLevelEnum | None] = mapped_column(
        Enum(RiskLevelEnum, name="risk_level_enum", native_enum=True), nullable=True
    )
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
