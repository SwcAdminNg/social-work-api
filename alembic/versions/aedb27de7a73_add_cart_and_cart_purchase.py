"""add cart_items, transaction_items, and coupon fields on transactions

Revision ID: aedb27de7a73
Revises: 081e2fe2d490
Create Date: 2026-09-02 12:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'aedb27de7a73'
down_revision: Union[str, None] = '081e2fe2d490'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE transaction_type_enum ADD VALUE IF NOT EXISTS 'CART_PURCHASE'")

    op.create_table(
        'cart_items',
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('course_id', sa.UUID(), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('deleted_by', sa.UUID(), nullable=True),
        sa.Column('restored_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'course_id', name='uq_cart_items_user_course'),
    )
    op.create_index(op.f('ix_cart_items_user_id'), 'cart_items', ['user_id'], unique=False)
    op.create_index(op.f('ix_cart_items_course_id'), 'cart_items', ['course_id'], unique=False)

    op.create_table(
        'transaction_items',
        sa.Column('transaction_id', sa.UUID(), nullable=False),
        sa.Column('course_id', sa.UUID(), nullable=False),
        sa.Column('unit_price', sa.Numeric(10, 2), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('deleted_by', sa.UUID(), nullable=True),
        sa.Column('restored_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_transaction_items_transaction_id'), 'transaction_items', ['transaction_id'], unique=False)
    op.create_index(op.f('ix_transaction_items_course_id'), 'transaction_items', ['course_id'], unique=False)

    op.add_column('transactions', sa.Column('coupon_id', sa.UUID(), nullable=True))
    op.add_column('transactions', sa.Column('subtotal_amount', sa.Numeric(10, 2), nullable=True))
    op.add_column('transactions', sa.Column('discount_amount', sa.Numeric(10, 2), server_default='0', nullable=False))
    op.create_foreign_key(
        'fk_transactions_coupon_id', 'transactions', 'coupons', ['coupon_id'], ['id'], ondelete='SET NULL'
    )


def downgrade() -> None:
    op.drop_constraint('fk_transactions_coupon_id', 'transactions', type_='foreignkey')
    op.drop_column('transactions', 'discount_amount')
    op.drop_column('transactions', 'subtotal_amount')
    op.drop_column('transactions', 'coupon_id')

    op.drop_index(op.f('ix_transaction_items_course_id'), table_name='transaction_items')
    op.drop_index(op.f('ix_transaction_items_transaction_id'), table_name='transaction_items')
    op.drop_table('transaction_items')

    op.drop_index(op.f('ix_cart_items_course_id'), table_name='cart_items')
    op.drop_index(op.f('ix_cart_items_user_id'), table_name='cart_items')
    op.drop_table('cart_items')

    # Postgres can't cheaply drop enum values; CART_PURCHASE is left in place as an
    # unused legacy value (harmless), same convention as other enum-add migrations.
