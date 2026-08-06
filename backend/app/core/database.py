from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session


def _ensure_additive_columns(sync_conn) -> None:
    """轻量增量迁移：为老库补充后加的列（create_all 不会改已有表）。

    只追加可空列，绝不修改或删除既有结构，保证存量数据无损。
    """
    from sqlalchemy import text

    migrations = {
        "users": {
            "target_weeks": "ALTER TABLE users ADD COLUMN target_weeks INTEGER",
        },
    }
    for table, columns in migrations.items():
        existing = {
            row[1]
            for row in sync_conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        }
        if not existing:
            continue  # 表还不存在，由 create_all 创建完整结构
        for column, ddl in columns.items():
            if column not in existing:
                sync_conn.execute(text(ddl))


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_additive_columns)
