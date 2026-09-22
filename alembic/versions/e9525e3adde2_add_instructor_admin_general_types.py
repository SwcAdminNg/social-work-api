"""add INSTRUCTOR_GENERAL/ADMIN_GENERAL to community_type_enum

Revision ID: e9525e3adde2
Revises: 8c89897f198b
Create Date: 2026-09-22 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e9525e3adde2'
down_revision: Union[str, None] = '8c89897f198b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Added in their own migration/transaction - Postgres won't let a just-added
    # enum value be used (e.g. in the data backfill INSERT in the next migration)
    # within the same transaction it was added in.
    op.execute("ALTER TYPE community_type_enum ADD VALUE IF NOT EXISTS 'INSTRUCTOR_GENERAL'")
    op.execute("ALTER TYPE community_type_enum ADD VALUE IF NOT EXISTS 'ADMIN_GENERAL'")


def downgrade() -> None:
    # Postgres can't cheaply drop enum values; left in place as unused legacy
    # values (harmless).
    pass
