"""add notifications table

Revision ID: 89dfd67bd971
Revises: e2f3a4b5c6d7
Create Date: 2026-09-08 06:25:47.600743

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '89dfd67bd971'
down_revision: Union[str, None] = 'e2f3a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('notifications',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('type', sa.Enum('SIGNUP_WELCOME', 'LOGIN', 'PASSWORD_RESET_REQUESTED', 'PASSWORD_RESET_COMPLETED', 'PROFILE_PICTURE_UPDATED', 'TWO_FACTOR_ENABLED', 'ACCOUNT_SUSPENDED', 'ACCOUNT_UNSUSPENDED', 'ROLE_CHANGED', 'PAYMENT_SUCCESSFUL', 'SUBSCRIPTION_RENEWED', 'SUBSCRIPTION_RENEWAL_FAILED', 'SUBSCRIPTION_EXPIRING_SOON', 'SUBSCRIPTION_EXPIRED', 'COURSE_ENROLLED', 'COURSE_COMPLETED', 'CERTIFICATE_ISSUED', 'LIVE_SESSION_SCHEDULED', 'LIVE_SESSION_RESCHEDULED', 'LIVE_SESSION_REMINDER', 'COURSE_REVIEW_REPLIED', 'COMMUNITY_NEW_MESSAGE', 'SUPPORT_TICKET_MESSAGE', 'SUPPORT_TICKET_STATUS_CHANGED', 'SUPPORT_TICKET_ASSIGNED', 'NEW_USER_SIGNUP', 'NEW_PAYMENT', 'NEW_CONTACT_MESSAGE', 'NEW_SUPPORT_TICKET', 'NEW_COURSE_REVIEW', 'ADMIN_INVITED', 'ADMIN_INVITE_ACCEPTED', name='notification_type_enum'), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('body', sa.Text(), nullable=True),
    sa.Column('link', sa.String(length=1000), nullable=True),
    sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('is_read', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('deleted_by', sa.UUID(), nullable=True),
    sa.Column('restored_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notifications_user_id'), 'notifications', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_notifications_user_id'), table_name='notifications')
    op.drop_table('notifications')
