"""contact us: make phone optional and record the page a message came from

Revision ID: d8e9f0a1b2c3
Revises: c4d5e6f7a8b9
Create Date: 2026-11-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8e9f0a1b2c3'
down_revision: Union[str, None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The public sites make the phone number optional, so the column must
    # accept messages without one.
    op.alter_column(
        'contact_us_messages',
        'phone_number',
        existing_type=sa.String(length=20),
        nullable=True,
    )
    # The path of the page whose form sent the message (e.g. "/contact",
    # "/policy-and-advocacy"), so admins can see where enquiries come from.
    op.add_column(
        'contact_us_messages',
        sa.Column('source_page', sa.String(length=255), nullable=True),
    )
    op.create_index(
        'ix_contact_us_messages_source_page',
        'contact_us_messages',
        ['source_page'],
    )


def downgrade() -> None:
    op.drop_index('ix_contact_us_messages_source_page', table_name='contact_us_messages')
    op.drop_column('contact_us_messages', 'source_page')
    op.execute("UPDATE contact_us_messages SET phone_number = '' WHERE phone_number IS NULL")
    op.alter_column(
        'contact_us_messages',
        'phone_number',
        existing_type=sa.String(length=20),
        nullable=False,
    )
