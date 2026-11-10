"""lot pull state, waste/adjust reasons, receiving detail, sell-by days

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('lots', schema=None) as b:
        b.add_column(sa.Column('pulled_qty', sa.Integer(), nullable=True))
        b.add_column(sa.Column('pulled_date', sa.Date(), nullable=True))
    with op.batch_alter_table('stock_movements', schema=None) as b:
        b.add_column(sa.Column('reason', sa.String(length=20), nullable=True))
    with op.batch_alter_table('products', schema=None) as b:
        b.add_column(sa.Column('pull_days_before_expiry', sa.Integer(), server_default='0', nullable=False))
    with op.batch_alter_table('po_lines', schema=None) as b:
        b.add_column(sa.Column('rejected_qty', sa.Integer(), nullable=True))
        b.add_column(sa.Column('reject_reason', sa.String(length=30), nullable=True))
        b.add_column(sa.Column('short_qty', sa.Integer(), nullable=True))
        b.add_column(sa.Column('actual_unit_cost', sa.Integer(), nullable=True))
    # Du lieu cu: moi lan huy deu la hang het han; ngay ban cuoi theo goi y cua nhom vong doi
    op.execute("UPDATE stock_movements SET reason = 'EXPIRED' WHERE type = 'WASTE'")
    op.execute("UPDATE products SET pull_days_before_expiry = 1 WHERE freshness_class = 'SHORT'")
    op.execute("UPDATE products SET pull_days_before_expiry = 7 WHERE freshness_class = 'LONG'")


def downgrade() -> None:
    with op.batch_alter_table('po_lines', schema=None) as b:
        b.drop_column('actual_unit_cost')
        b.drop_column('short_qty')
        b.drop_column('reject_reason')
        b.drop_column('rejected_qty')
    with op.batch_alter_table('products', schema=None) as b:
        b.drop_column('pull_days_before_expiry')
    with op.batch_alter_table('stock_movements', schema=None) as b:
        b.drop_column('reason')
    with op.batch_alter_table('lots', schema=None) as b:
        b.drop_column('pulled_date')
        b.drop_column('pulled_qty')
