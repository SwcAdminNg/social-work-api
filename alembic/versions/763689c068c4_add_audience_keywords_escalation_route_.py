"""add audience keywords escalation route and related articles to faq items

Revision ID: 763689c068c4
Revises: 89dfd67bd971
Create Date: 2026-09-17 17:34:09.920420

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '763689c068c4'
down_revision: Union[str, None] = '89dfd67bd971'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

faq_audience_enum = postgresql.ENUM('STUDENT', 'INSTRUCTOR', 'BOTH', name='faq_audience_enum')


def upgrade() -> None:
    faq_audience_enum.create(op.get_bind(), checkfirst=True)
    op.add_column('faq_items', sa.Column('audience', faq_audience_enum, server_default='BOTH', nullable=False))
    op.add_column('faq_items', sa.Column('keywords', sa.ARRAY(sa.String()), server_default='{}', nullable=False))
    op.add_column('faq_items', sa.Column('escalation_route', sa.String(length=150), nullable=True))
    op.add_column('faq_items', sa.Column('related_article_ids', sa.ARRAY(sa.UUID()), server_default='{}', nullable=False))


def downgrade() -> None:
    op.drop_column('faq_items', 'related_article_ids')
    op.drop_column('faq_items', 'escalation_route')
    op.drop_column('faq_items', 'keywords')
    op.drop_column('faq_items', 'audience')
    faq_audience_enum.drop(op.get_bind(), checkfirst=True)
