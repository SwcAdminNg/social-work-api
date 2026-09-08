"""store daily.co recording id instead of a stored (expiring) playback url

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-09-09 10:00:00.000000

daily.co only issues short-lived signed access-links for a recording (expiring
within at most a few hours), so persisting one in `recording_playback_url` meant
every recording became a dead link shortly after being marked ready. Storing the
recording id instead lets the API mint a fresh access-link on every request, the
same way CourseDocument's download URL is never stored either.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('course_live_sessions', sa.Column('recording_id', sa.String(length=255), nullable=True))
    op.drop_column('course_live_sessions', 'recording_playback_url')


def downgrade() -> None:
    op.add_column('course_live_sessions', sa.Column('recording_playback_url', sa.String(length=1000), nullable=True))
    op.drop_column('course_live_sessions', 'recording_id')
