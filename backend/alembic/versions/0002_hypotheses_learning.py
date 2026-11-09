"""demand hypotheses, learned order adjustments, discounted sales

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'demand_hypotheses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(length=100), nullable=True),
        sa.Column('sku', sa.String(length=30), nullable=True),
        sa.Column('factor', sa.Float(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('baseline_total', sa.Float(), nullable=False),
        sa.Column('proposal_id', sa.Integer(), nullable=True),
        sa.Column('created_by', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['proposal_id'], ['proposals.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('demand_hypotheses', schema=None) as b:
        b.create_index(b.f('ix_demand_hypotheses_category'), ['category'], unique=False)
        b.create_index(b.f('ix_demand_hypotheses_sku'), ['sku'], unique=False)
        b.create_index(b.f('ix_demand_hypotheses_end_date'), ['end_date'], unique=False)
        b.create_index(b.f('ix_demand_hypotheses_status'), ['status'], unique=False)

    op.create_table(
        'order_adjustments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(length=100), nullable=False),
        sa.Column('factor', sa.Float(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('proposal_id', sa.Integer(), nullable=True),
        sa.Column('created_by', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['proposal_id'], ['proposals.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('order_adjustments', schema=None) as b:
        b.create_index(b.f('ix_order_adjustments_category'), ['category'], unique=False)
        b.create_index(b.f('ix_order_adjustments_active'), ['active'], unique=False)

    with op.batch_alter_table('daily_sales', schema=None) as b:
        b.add_column(sa.Column('discounted_qty', sa.Integer(), server_default='0', nullable=False))
        b.add_column(sa.Column('discount_pct', sa.Float(), server_default='0', nullable=False))
        b.add_column(sa.Column('evening_qty', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('daily_sales', schema=None) as b:
        b.drop_column('evening_qty')
        b.drop_column('discount_pct')
        b.drop_column('discounted_qty')
    op.drop_table('order_adjustments')
    op.drop_table('demand_hypotheses')
