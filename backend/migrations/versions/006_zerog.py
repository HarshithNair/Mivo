"""0G decision log and 0G Storage evidence references."""
from alembic import op
from backend.models import Base
import backend.integrations.zerog.models  # noqa: F401  registers the tables on Base
revision = '006'
down_revision = '005'
TABLES = ['zerog_decisions', 'zerog_evidence']
def upgrade(): Base.metadata.create_all(op.get_bind(), tables=[Base.metadata.tables[n] for n in TABLES])
def downgrade(): Base.metadata.drop_all(op.get_bind(), tables=[Base.metadata.tables[n] for n in TABLES])
