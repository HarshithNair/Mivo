"""Device BUY payments (USDC on Arc Testnet, verified on-chain)."""
from alembic import op
from backend.models import Base
import backend.buy_payments.models  # noqa: F401  registers buy_payments on Base
revision = '005'
down_revision = '004'
TABLES = ['buy_payments']
# create_all skips tables that already exist, so this is safe on any database state.
def upgrade(): Base.metadata.create_all(op.get_bind(), tables=[Base.metadata.tables[n] for n in TABLES])
def downgrade(): Base.metadata.drop_all(op.get_bind(), tables=[Base.metadata.tables[n] for n in TABLES])
