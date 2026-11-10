"""supplier return lifecycle, inventory snapshots, category policies, listing and count dates

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('supplier_agreements', schema=None) as b:
        b.add_column(sa.Column('return_mode', sa.String(length=10), server_default='CREDIT', nullable=False))
    with op.batch_alter_table('products', schema=None) as b:
        b.add_column(sa.Column('listed_date', sa.Date(), nullable=True))
        b.add_column(sa.Column('last_counted_date', sa.Date(), nullable=True))
    op.create_table(
        'supplier_returns',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=30), nullable=False),
        sa.Column('supplier_id', sa.Integer(), nullable=False),
        sa.Column('proposal_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('mode', sa.String(length=10), nullable=False),
        sa.Column('credit_pct', sa.Float(), nullable=False),
        sa.Column('items', sa.JSON(), nullable=False),
        sa.Column('est_credit', sa.Integer(), nullable=False),
        sa.Column('credit_value', sa.Integer(), nullable=True),
        sa.Column('requested_date', sa.Date(), nullable=False),
        sa.Column('confirmed_date', sa.Date(), nullable=True),
        sa.Column('picked_up_date', sa.Date(), nullable=True),
        sa.Column('credited_date', sa.Date(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['proposal_id'], ['proposals.id']),
        sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )
    with op.batch_alter_table('supplier_returns', schema=None) as b:
        b.create_index(b.f('ix_supplier_returns_supplier_id'), ['supplier_id'], unique=False)
        b.create_index(b.f('ix_supplier_returns_status'), ['status'], unique=False)
    op.create_table(
        'inventory_snapshots',
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('value', sa.Integer(), nullable=False),
        sa.Column('units', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('date'),
    )
    op.create_table(
        'category_policies',
        sa.Column('category', sa.String(length=100), nullable=False),
        sa.Column('markdown_allowed', sa.Boolean(), nullable=False),
        sa.Column('max_markdown_pct', sa.Float(), nullable=False),
        sa.Column('daypart_shares', sa.JSON(), nullable=True),
        sa.Column('markdown_hour', sa.Integer(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('category'),
    )


def downgrade() -> None:
    op.drop_table('category_policies')
    op.drop_table('inventory_snapshots')
    op.drop_table('supplier_returns')
    with op.batch_alter_table('products', schema=None) as b:
        b.drop_column('last_counted_date')
        b.drop_column('listed_date')
    with op.batch_alter_table('supplier_agreements', schema=None) as b:
        b.drop_column('return_mode')
