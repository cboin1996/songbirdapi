import asyncio
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context
from songbirdapi.models import Base
from songbirdapi.settings import SongbirdServerConfig

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override the static alembic.ini url with the runtime DSN built from env vars
# (POSTGRES_HOST, POSTGRES_PORT, etc.) so migrations work in both local dev and
# the docker container where the host is "postgres" rather than "localhost".
try:
    config.set_main_option("sqlalchemy.url", SongbirdServerConfig().postgres_dsn)
except Exception:
    # If settings can't load (e.g. env not present), fall back to alembic.ini default.
    pass

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
