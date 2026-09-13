import json
import os
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

from sibase.models import Base

config = json.loads(Path(os.environ["SIBASE_MIGRATION_SETTINGS"]).read_text())
engine = create_engine(config["url"], poolclass=pool.NullPool)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
