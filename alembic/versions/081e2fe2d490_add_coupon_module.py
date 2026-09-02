"""add coupon module (coupons, coupon_redemptions)

Revision ID: 081e2fe2d490
Revises: c2d3e4f5a6b7
Create Date: 2026-09-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '081e2fe2d490'
down_revision: Union[str, None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    coupon_discount_type_enum = postgresql.ENUM(
        'PERCENTAGE', 'FIXED_AMOUNT', name='coupon_discount_type_enum', create_type=False,
    )
    coupon_discount_type_enum.create(op.get_bind(), checkfirst=True)

    # course_category_enum already exists (created by the course module) - referenced
    # here without create_type so this migration doesn't try to recreate it.
    course_category_enum = postgresql.ENUM(name='course_category_enum', create_type=False)

    op.create_table(
        'coupons',
        sa.Column('code', sa.String(length=40), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('discount_type', coupon_discount_type_enum, nullable=False),
        sa.Column('discount_value', sa.Numeric(10, 2), nullable=False),
        sa.Column('max_discount_amount', sa.Numeric(10, 2), nullable=True),
        sa.Column('min_order_amount', sa.Numeric(10, 2), nullable=True),
        sa.Column('valid_from', sa.DateTime(timezone=True), nullable=True),
        sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('max_redemptions', sa.Integer(), nullable=True),
        sa.Column('max_redemptions_per_user', sa.Integer(), server_default='1', nullable=False),
        sa.Column('times_redeemed', sa.Integer(), server_default='0', nullable=False),
        sa.Column('applicable_course_ids', postgresql.ARRAY(sa.UUID()), nullable=True),
        sa.Column('applicable_category', course_category_enum, nullable=True),
        sa.Column('new_users_only', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('deleted_by', sa.UUID(), nullable=True),
        sa.Column('restored_by', sa.UUID(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_coupons_code'), 'coupons', ['code'], unique=True)

    op.create_table(
        'coupon_redemptions',
        sa.Column('coupon_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('transaction_id', sa.UUID(), nullable=False),
        sa.Column('discount_amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('deleted_by', sa.UUID(), nullable=True),
        sa.Column('restored_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['coupon_id'], ['coupons.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_coupon_redemptions_coupon_id'), 'coupon_redemptions', ['coupon_id'], unique=False)
    op.create_index(op.f('ix_coupon_redemptions_user_id'), 'coupon_redemptions', ['user_id'], unique=False)
    op.create_index(
        op.f('ix_coupon_redemptions_transaction_id'), 'coupon_redemptions', ['transaction_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_coupon_redemptions_transaction_id'), table_name='coupon_redemptions')
    op.drop_index(op.f('ix_coupon_redemptions_user_id'), table_name='coupon_redemptions')
    op.drop_index(op.f('ix_coupon_redemptions_coupon_id'), table_name='coupon_redemptions')
    op.drop_table('coupon_redemptions')

    op.drop_index(op.f('ix_coupons_code'), table_name='coupons')
    op.drop_table('coupons')

    bind = op.get_bind()
    sa.Enum(name='coupon_discount_type_enum').drop(bind, checkfirst=True)
