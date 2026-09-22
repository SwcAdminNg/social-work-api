"""set existing faq items to ACCOUNT visibility

Revision ID: f3a4b5c6d7e8
Revises: 3e89f463599d
Create Date: 2026-09-22 00:00:04.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f3a4b5c6d7e8'
down_revision: Union[str, None] = '3e89f463599d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Every FAQ article that currently exists switches from GENERAL (public,
    # visible to anonymous callers) to ACCOUNT (requires a signed-in user).
    # New articles created after this migration still default to GENERAL.
    op.execute("UPDATE faq_items SET visibility = 'ACCOUNT' WHERE visibility = 'GENERAL'")


def downgrade() -> None:
    # Not reversible: we can't distinguish articles that were GENERAL before
    # this migration from ones an admin deliberately moved to ACCOUNT after.
    pass
