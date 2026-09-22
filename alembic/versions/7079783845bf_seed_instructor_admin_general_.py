"""seed Instructor/Admin General singleton communities

Revision ID: 7079783845bf
Revises: e9525e3adde2
Create Date: 2026-09-22 00:00:02.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7079783845bf'
down_revision: Union[str, None] = 'e9525e3adde2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO communities (id, type, name, is_active, created_at)
        SELECT gen_random_uuid(), 'INSTRUCTOR_GENERAL', 'Instructor Community', true, now()
        WHERE NOT EXISTS (SELECT 1 FROM communities WHERE type = 'INSTRUCTOR_GENERAL')
        """
    )
    op.execute(
        """
        INSERT INTO communities (id, type, name, is_active, created_at)
        SELECT gen_random_uuid(), 'ADMIN_GENERAL', 'Admin Community', true, now()
        WHERE NOT EXISTS (SELECT 1 FROM communities WHERE type = 'ADMIN_GENERAL')
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM communities WHERE type = 'ADMIN_GENERAL'")
    op.execute("DELETE FROM communities WHERE type = 'INSTRUCTOR_GENERAL'")
