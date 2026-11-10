"""shelf capacity, display minimum, supplier delivery days and closures

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('products', schema=None) as b:
        b.add_column(sa.Column('max_stock_qty', sa.Integer(), nullable=True))
        b.add_column(sa.Column('min_display_qty', sa.Integer(), server_default='0', nullable=False))
    with op.batch_alter_table('suppliers', schema=None) as b:
        b.add_column(sa.Column('delivery_weekdays', sa.JSON(), nullable=True))
    op.create_table(
        'supplier_closures',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('supplier_id', sa.Integer(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('reason', sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('supplier_closures', schema=None) as b:
        b.create_index(b.f('ix_supplier_closures_supplier_id'), ['supplier_id'], unique=False)


def downgrade() -> None:
    op.drop_table('supplier_closures')
    with op.batch_alter_table('suppliers', schema=None) as b:
        b.drop_column('delivery_weekdays')
    with op.batch_alter_table('products', schema=None) as b:
        b.drop_column('min_display_qty')
        b.drop_column('max_stock_qty')
