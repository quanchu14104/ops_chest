"""demand hypothesis scope frozen at approval, evening markdown kept apart from all-day markdown

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('demand_hypotheses', schema=None) as b:
        b.add_column(sa.Column('scope_product_ids', sa.JSON(), nullable=True))
    with op.batch_alter_table('lots', schema=None) as b:
        b.add_column(sa.Column('evening_markdown_pct', sa.Float(), server_default='0', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('lots', schema=None) as b:
        b.drop_column('evening_markdown_pct')
    with op.batch_alter_table('demand_hypotheses', schema=None) as b:
        b.drop_column('scope_product_ids')
