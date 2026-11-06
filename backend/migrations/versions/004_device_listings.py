"""Unlisted demo-dealer products created by device negotiation scans."""
import sqlalchemy as sa
from alembic import op
revision='004'
down_revision='003'
def upgrade():
    # 001 builds tables from the current models, so fresh databases already have the column.
    if 'listed' not in {c['name'] for c in sa.inspect(op.get_bind()).get_columns('products')}:
        op.add_column('products',sa.Column('listed',sa.Boolean(),nullable=False,server_default=sa.true()))
def downgrade():
    op.drop_column('products','listed')
