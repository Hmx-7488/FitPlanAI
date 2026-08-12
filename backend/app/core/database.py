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
        "plans": {
            "workout_plan_json": "ALTER TABLE plans ADD COLUMN workout_plan_json TEXT DEFAULT ''",
            "meal_plan_json": "ALTER TABLE plans ADD COLUMN meal_plan_json TEXT DEFAULT ''",
            "supplements_json": "ALTER TABLE plans ADD COLUMN supplements_json TEXT DEFAULT ''",
        },
        "user_memories": {
            "active_slot": "ALTER TABLE user_memories ADD COLUMN active_slot VARCHAR(80)",
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

    memory_columns = {
        row[1]
        for row in sync_conn.execute(text("PRAGMA table_info(user_memories)")).fetchall()
    }
    if "active_slot" not in memory_columns:
        return
    memory_indexes = {
        row[1]
        for row in sync_conn.execute(text("PRAGMA index_list(user_memories)")).fetchall()
    }
    if "uq_user_memory_active_slot" in memory_indexes:
        return

    # Normalize an early M4 development database before adding the invariant:
    # one active confirmed value per (user_id, memory_key), while exact
    # candidates retain a fingerprint-scoped slot.
    sync_conn.execute(text("UPDATE user_memories SET active_slot = NULL"))
    sync_conn.execute(
        text(
            """
            UPDATE user_memories
            SET valid_until = CURRENT_TIMESTAMP
            WHERE confirmation_status = 'confirmed'
              AND deleted_at IS NULL
              AND (valid_until IS NULL OR valid_until > CURRENT_TIMESTAMP)
              AND id NOT IN (
                SELECT MAX(id)
                FROM user_memories
                WHERE confirmation_status = 'confirmed'
                  AND deleted_at IS NULL
                  AND (valid_until IS NULL OR valid_until > CURRENT_TIMESTAMP)
                GROUP BY user_id, memory_key
              )
            """
        )
    )
    sync_conn.execute(
        text(
            """
            UPDATE user_memories
            SET active_slot = 'active'
            WHERE id IN (
                SELECT MAX(id)
                FROM user_memories
                WHERE confirmation_status = 'confirmed'
                  AND deleted_at IS NULL
                  AND (valid_until IS NULL OR valid_until > CURRENT_TIMESTAMP)
                GROUP BY user_id, memory_key
            )
            """
        )
    )
    sync_conn.execute(
        text(
            """
            UPDATE user_memories
            SET active_slot = 'candidate:' || substr(content_fingerprint, 1, 32)
            WHERE id IN (
                SELECT MAX(id)
                FROM user_memories
                WHERE confirmation_status = 'candidate'
                  AND deleted_at IS NULL
                  AND (valid_until IS NULL OR valid_until > CURRENT_TIMESTAMP)
                GROUP BY user_id, memory_key, content_fingerprint
            )
            """
        )
    )
    sync_conn.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_user_memory_active_slot
            ON user_memories (user_id, memory_key, active_slot)
            WHERE active_slot IS NOT NULL
            """
        )
    )


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_additive_columns)
