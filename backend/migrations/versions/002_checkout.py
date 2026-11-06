"""Wallet ownership, immutable checkout intents and verified receipts."""
from alembic import op
from backend.models import Base
revision='002'
down_revision='001'
TABLES=['wallet_challenges','wallet_connections','checkout_intents','payments','orders']
def upgrade(): Base.metadata.create_all(op.get_bind(),tables=[Base.metadata.tables[n] for n in TABLES])
def downgrade(): Base.metadata.drop_all(op.get_bind(),tables=[Base.metadata.tables[n] for n in TABLES])
