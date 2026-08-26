"""add student profile picture to certificates

Revision ID: 5f7a9c0d1e2b
Revises: 3ac37d7818c2
Create Date: 2026-08-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5f7a9c0d1e2b'
down_revision: Union[str, None] = '3ac37d7818c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('certificates', sa.Column('student_profile_picture_url', sa.String(length=1000), nullable=True))
    op.execute(
        """
        UPDATE certificates
        SET student_profile_picture_url = users.profile_picture_url
        FROM users
        WHERE certificates.user_id = users.id
          AND users.profile_picture_url IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_column('certificates', 'student_profile_picture_url')
