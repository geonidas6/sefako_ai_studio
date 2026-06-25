from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def create_tables():
    # Import all models to ensure they are registered
    from app.models import user, project, llm_config, department, workflow_event, git_integration  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_git_integration_profile_column)
    print("✅ Tables créées")


def _ensure_git_integration_profile_column(sync_conn):
    inspector = inspect(sync_conn)
    if not inspector.has_table("git_integrations"):
        return
    columns = {column["name"] for column in inspector.get_columns("git_integrations")}
    if "profile_json" not in columns:
        sync_conn.execute(text("ALTER TABLE git_integrations ADD COLUMN profile_json TEXT"))
