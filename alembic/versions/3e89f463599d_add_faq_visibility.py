"""add visibility (GENERAL/ACCOUNT) to faq_items

Revision ID: 3e89f463599d
Revises: 7079783845bf
Create Date: 2026-09-22 00:00:03.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3e89f463599d'
down_revision: Union[str, None] = '7079783845bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    faq_visibility_enum = postgresql.ENUM(
        'GENERAL', 'ACCOUNT', name='faq_visibility_enum', create_type=False,
    )
    faq_visibility_enum.create(op.get_bind(), checkfirst=True)

    # Defaulted to GENERAL (public) so every existing FAQ article stays visible to
    # anonymous callers exactly as before this change - admins can move specific
    # articles to ACCOUNT-only afterwards.
    op.add_column(
        'faq_items',
        sa.Column(
            'visibility', faq_visibility_enum, nullable=False, server_default='GENERAL'
        ),
    )


def downgrade() -> None:
    op.drop_column('faq_items', 'visibility')

    bind = op.get_bind()
    sa.Enum(name='faq_visibility_enum').drop(bind, checkfirst=True)
