"""Initial catalog, authentication and negotiation persistence."""
from alembic import op
from backend.models import Base
revision = '001'
down_revision = None

TABLES = ['users','sessions','products','negotiations','messages','offers','quotes','saved_products','audit']
def upgrade(): Base.metadata.create_all(op.get_bind(), tables=[Base.metadata.tables[n] for n in TABLES])
def downgrade(): Base.metadata.drop_all(op.get_bind(), tables=[Base.metadata.tables[n] for n in TABLES])
