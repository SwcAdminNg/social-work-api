"""add submitted_by to course_revisions

Records who last submitted a revision for review, so a return lands with the
person who sent it in (not just whoever happened to edit the working copy).

Revision ID: e7a8b9c0d1f2
Revises: d1f2a3b4c5e6
Create Date: 2026-10-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e7a8b9c0d1f2'
down_revision: Union[str, None] = 'd1f2a3b4c5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'course_revisions',
        sa.Column('submitted_by', postgresql.UUID(as_uuid=True), nullable=True),
    )
    # Best effort for in-flight revisions: the actor of the latest SUBMITTED audit row.
    op.execute(
        """
        UPDATE course_revisions r
        SET submitted_by = a.actor_id
        FROM (
            SELECT DISTINCT ON (revision_id) revision_id, actor_id
            FROM governance_audit_log
            WHERE action = 'SUBMITTED' AND revision_id IS NOT NULL AND actor_id IS NOT NULL
            ORDER BY revision_id, occurred_at DESC
        ) a
        WHERE a.revision_id = r.id AND r.submitted_by IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column('course_revisions', 'submitted_by')
