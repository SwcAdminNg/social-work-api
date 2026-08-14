"""add ESSAY_SUBMITTED/ESSAY_GRADED to activity_type_enum

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-08-14 00:00:00.000002

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e4f5a6b7c8d9'
down_revision: Union[str, None] = 'd3e4f5a6b7c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE activity_type_enum ADD VALUE IF NOT EXISTS 'ESSAY_SUBMITTED'")
    op.execute("ALTER TYPE activity_type_enum ADD VALUE IF NOT EXISTS 'ESSAY_GRADED'")


def downgrade() -> None:
    # Postgres can't cheaply drop enum values; left in place as unused legacy
    # values (harmless).
    pass
