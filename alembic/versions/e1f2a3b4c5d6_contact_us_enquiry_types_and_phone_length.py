"""contact us: enquiry types from the new contact form and a longer phone column

Revision ID: e1f2a3b4c5d6
Revises: d8e9f0a1b2c3
Create Date: 2026-11-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'd8e9f0a1b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The contact form's enquiry types: Course Enquiry (existing COURSES),
# Mentorship (existing), Account or Learning Support, Partnership or
# Organisational Enquiry, and Other. SQLAlchemy stores enum member names.
NEW_CATEGORIES = ("ACCOUNT_SUPPORT", "PARTNERSHIP", "OTHER")


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block on older
    # Postgres versions, so run it in autocommit mode.
    with op.get_context().autocommit_block():
        for value in NEW_CATEGORIES:
            op.execute(f"ALTER TYPE contact_us_category_enum ADD VALUE IF NOT EXISTS '{value}'")

    # International numbers with spaces or brackets can exceed 20 characters.
    op.alter_column(
        'contact_us_messages',
        'phone_number',
        existing_type=sa.String(length=20),
        type_=sa.String(length=32),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.execute(
        "UPDATE contact_us_messages SET phone_number = LEFT(phone_number, 20) "
        "WHERE length(phone_number) > 20"
    )
    op.alter_column(
        'contact_us_messages',
        'phone_number',
        existing_type=sa.String(length=32),
        type_=sa.String(length=20),
        existing_nullable=True,
    )
    # Postgres cannot drop enum values; fold the new types back into GENERAL
    # and rebuild the type without them.
    op.execute(
        "UPDATE contact_us_messages SET category = 'GENERAL' "
        "WHERE category::text IN ('ACCOUNT_SUPPORT', 'PARTNERSHIP', 'OTHER')"
    )
    op.execute("ALTER TYPE contact_us_category_enum RENAME TO contact_us_category_enum_old")
    op.execute("CREATE TYPE contact_us_category_enum AS ENUM ('GENERAL', 'MENTORSHIP', 'PRICING', 'COURSES')")
    op.execute(
        "ALTER TABLE contact_us_messages ALTER COLUMN category TYPE contact_us_category_enum "
        "USING category::text::contact_us_category_enum"
    )
    op.execute("DROP TYPE contact_us_category_enum_old")
