from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from backend.config import settings

url = settings.sqlalchemy_url
if url.startswith('sqlite'):
    engine = create_engine(url, connect_args={'check_same_thread': False})
    @event.listens_for(engine, 'connect')
    def sqlite_setup(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA busy_timeout=5000')
else:
    # Serverless instances are short-lived; let the provider's pooler (e.g. Neon) pool connections.
    engine = create_engine(url, poolclass=NullPool if settings.vercel else None, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)
def get_db():
    with SessionLocal() as db:
        yield db
