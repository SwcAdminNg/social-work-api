"""contact us: mentor applications and structured form details

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-11-05 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The mentorship page's "Become a mentor" form.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE contact_us_category_enum ADD VALUE IF NOT EXISTS 'MENTOR_APPLICATION'")

    # Extra answers from richer forms (country, stage, pathway, time zone...),
    # stored as an ordered list of {"label", "value"} pairs.
    op.add_column(
        'contact_us_messages',
        sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('contact_us_messages', 'details')
    # Postgres cannot drop a single enum value; fold mentor applications into
    # MENTORSHIP and rebuild the type without MENTOR_APPLICATION.
    op.execute(
        "UPDATE contact_us_messages SET category = 'MENTORSHIP' WHERE category::text = 'MENTOR_APPLICATION'"
    )
    op.execute("ALTER TYPE contact_us_category_enum RENAME TO contact_us_category_enum_old")
    op.execute(
        "CREATE TYPE contact_us_category_enum AS ENUM "
        "('GENERAL', 'MENTORSHIP', 'PRICING', 'COURSES', 'ACCOUNT_SUPPORT', 'PARTNERSHIP', 'OTHER')"
    )
    op.execute(
        "ALTER TABLE contact_us_messages ALTER COLUMN category TYPE contact_us_category_enum "
        "USING category::text::contact_us_category_enum"
    )
    op.execute("DROP TYPE contact_us_category_enum_old")
