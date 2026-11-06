"""Single-use World authorization attempts and minimal identity bindings."""
from alembic import op
from backend.models import Base
revision='003'
down_revision='002'
TABLES=['world_attempts','world_verifications']
def upgrade():Base.metadata.create_all(op.get_bind(),tables=[Base.metadata.tables[n] for n in TABLES])
def downgrade():Base.metadata.drop_all(op.get_bind(),tables=[Base.metadata.tables[n] for n in TABLES])
