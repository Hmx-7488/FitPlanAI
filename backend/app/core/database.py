from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
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
    """Add columns and invariants introduced after the first SQLite schema."""
    from sqlalchemy import text

    migrations = {
        "users": {
            "target_weeks": "ALTER TABLE users ADD COLUMN target_weeks INTEGER",
            "body_fat_rate": "ALTER TABLE users ADD COLUMN body_fat_rate FLOAT",
            "activity_level": "ALTER TABLE users ADD COLUMN activity_level VARCHAR(20) DEFAULT 'medium'",
            "diet_preference": "ALTER TABLE users ADD COLUMN diet_preference VARCHAR(50) DEFAULT 'balanced'",
            "goal_type": "ALTER TABLE users ADD COLUMN goal_type VARCHAR(20) DEFAULT 'fat_loss'",
            "forbidden_foods": "ALTER TABLE users ADD COLUMN forbidden_foods TEXT DEFAULT '[]'",
            "injuries": "ALTER TABLE users ADD COLUMN injuries TEXT DEFAULT '[]'",
            "allergies": "ALTER TABLE users ADD COLUMN allergies TEXT DEFAULT '[]'",
            "training_days_per_week": "ALTER TABLE users ADD COLUMN training_days_per_week INTEGER DEFAULT 3",
            "session_duration_minutes": "ALTER TABLE users ADD COLUMN session_duration_minutes INTEGER DEFAULT 60",
            "training_location": "ALTER TABLE users ADD COLUMN training_location VARCHAR(20) DEFAULT 'gym'",
            "equipment": "ALTER TABLE users ADD COLUMN equipment TEXT DEFAULT '[]'",
            "training_experience": "ALTER TABLE users ADD COLUMN training_experience VARCHAR(20) DEFAULT 'beginner'",
            "preferred_training_time": "ALTER TABLE users ADD COLUMN preferred_training_time VARCHAR(20) DEFAULT 'morning'",
            "region_preference": "ALTER TABLE users ADD COLUMN region_preference VARCHAR(30) DEFAULT 'balanced'",
            "meal_scenario": "ALTER TABLE users ADD COLUMN meal_scenario VARCHAR(30) DEFAULT 'home_cooking'",
            "prep_time_limit_minutes": "ALTER TABLE users ADD COLUMN prep_time_limit_minutes INTEGER DEFAULT 30",
            "created_at": "ALTER TABLE users ADD COLUMN created_at DATETIME",
        },
        "plans": {
            "calorie_info_json": "ALTER TABLE plans ADD COLUMN calorie_info_json TEXT DEFAULT '{}'",
            "macros_json": "ALTER TABLE plans ADD COLUMN macros_json TEXT DEFAULT '{}'",
            "workout_plan_json": "ALTER TABLE plans ADD COLUMN workout_plan_json TEXT DEFAULT ''",
            "meal_plan_json": "ALTER TABLE plans ADD COLUMN meal_plan_json TEXT DEFAULT ''",
            "supplements_json": "ALTER TABLE plans ADD COLUMN supplements_json TEXT DEFAULT ''",
            "summary": "ALTER TABLE plans ADD COLUMN summary TEXT DEFAULT ''",
            "created_at": "ALTER TABLE plans ADD COLUMN created_at DATETIME",
        },
        "user_memories": {
            "active_slot": "ALTER TABLE user_memories ADD COLUMN active_slot VARCHAR(80)",
            "index_revision": "ALTER TABLE user_memories ADD COLUMN index_revision INTEGER NOT NULL DEFAULT 0",
        },
        "recipe_image_jobs": {
            "lease_owner": "ALTER TABLE recipe_image_jobs ADD COLUMN lease_owner VARCHAR(80)",
            "lease_expires_at": "ALTER TABLE recipe_image_jobs ADD COLUMN lease_expires_at DATETIME",
        },
    }
    for table, columns in migrations.items():
        existing = {
            row[1]
            for row in sync_conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        }
        if not existing:
            continue
        for column, ddl in columns.items():
            if column not in existing:
                sync_conn.execute(text(ddl))

    _archive_domain_duplicates_and_add_unique_indexes(sync_conn)
    _ensure_conversation_summary_unique_indexes(sync_conn)
    _ensure_memory_active_slot_index(sync_conn)


def _archive_domain_duplicates_and_add_unique_indexes(sync_conn) -> None:
    """Archive every superseded legacy row before enforcing business keys."""
    from sqlalchemy import text

    def has_unique_index(table: str, columns: tuple[str, ...]) -> bool:
        for row in sync_conn.execute(text(f"PRAGMA index_list({table})")).fetchall():
            if not row[2]:
                continue
            index_name = str(row[1]).replace("'", "''")
            indexed = tuple(
                item[2]
                for item in sync_conn.execute(
                    text(f"PRAGMA index_info('{index_name}')")
                ).fetchall()
            )
            if indexed == columns:
                return True
        return False

    if sync_conn.execute(text("PRAGMA table_info(checkins)")).fetchall():
        sync_conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS checkin_duplicates_archive (
                original_id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                date VARCHAR(10) NOT NULL,
                foods TEXT,
                exercises TEXT,
                weight FLOAT,
                note TEXT,
                created_at DATETIME,
                archived_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                archive_reason VARCHAR(80) NOT NULL
            )
            """
        ))
        sync_conn.execute(text(
            """
            INSERT OR IGNORE INTO checkin_duplicates_archive (
                original_id, user_id, date, foods, exercises, weight, note,
                created_at, archive_reason
            )
            SELECT id, user_id, date, foods, exercises, weight, note, created_at,
                   'duplicate_before_unique_constraint'
            FROM checkins
            WHERE id NOT IN (
                SELECT MAX(id) FROM checkins GROUP BY user_id, date
            )
            """
        ))
        sync_conn.execute(text(
            """
            DELETE FROM checkins
            WHERE id NOT IN (
                SELECT MAX(id) FROM checkins GROUP BY user_id, date
            )
            """
        ))
        if not has_unique_index("checkins", ("user_id", "date")):
            sync_conn.execute(text(
                """
                CREATE UNIQUE INDEX uq_checkin_user_date
                ON checkins (user_id, date)
                """
            ))

    if sync_conn.execute(text("PRAGMA table_info(meal_logs)")).fetchall():
        sync_conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS meal_log_duplicates_archive (
                original_id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                date VARCHAR(10) NOT NULL,
                meal_type VARCHAR(20) NOT NULL,
                image_path TEXT,
                items_json TEXT,
                meal_total_json TEXT,
                created_at DATETIME,
                archived_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                archive_reason VARCHAR(80) NOT NULL
            )
            """
        ))
        sync_conn.execute(text(
            """
            INSERT OR IGNORE INTO meal_log_duplicates_archive (
                original_id, user_id, date, meal_type, image_path, items_json,
                meal_total_json, created_at, archive_reason
            )
            SELECT id, user_id, date, meal_type, image_path, items_json,
                   meal_total_json, created_at,
                   'duplicate_before_unique_constraint'
            FROM meal_logs
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM meal_logs
                GROUP BY user_id, date, meal_type
            )
            """
        ))
        sync_conn.execute(text(
            """
            DELETE FROM meal_logs
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM meal_logs
                GROUP BY user_id, date, meal_type
            )
            """
        ))
        if not has_unique_index(
            "meal_logs", ("user_id", "date", "meal_type")
        ):
            sync_conn.execute(text(
                """
                CREATE UNIQUE INDEX uq_meal_log_user_date_type
                ON meal_logs (user_id, date, meal_type)
                """
            ))


def _ensure_memory_active_slot_index(sync_conn) -> None:
    """Normalize early M4 rows before adding the active-memory invariant."""
    from sqlalchemy import text

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

    sync_conn.execute(text("UPDATE user_memories SET active_slot = NULL"))
    sync_conn.execute(text(
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
    ))
    sync_conn.execute(text(
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
    ))
    sync_conn.execute(text(
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
    ))
    sync_conn.execute(text(
        """
        CREATE UNIQUE INDEX uq_user_memory_active_slot
        ON user_memories (user_id, memory_key, active_slot)
        WHERE active_slot IS NOT NULL
        """
    ))


def _ensure_conversation_summary_unique_indexes(sync_conn) -> None:
    """Preserve summary history while normalizing duplicate claim rows."""
    from sqlalchemy import text

    if not sync_conn.execute(
        text("PRAGMA table_info(chat_conversation_summaries)")
    ).fetchall():
        return

    indexes = {
        row[1]
        for row in sync_conn.execute(
            text("PRAGMA index_list(chat_conversation_summaries)")
        ).fetchall()
    }
    if "uq_chat_summary_pending_conversation" not in indexes:
        sync_conn.execute(text(
            """
            UPDATE chat_conversation_summaries
            SET status = 'failed',
                error_type = 'LeaseSuperseded',
                updated_at = CURRENT_TIMESTAMP
            WHERE status = 'pending'
              AND id NOT IN (
                SELECT MAX(id)
                FROM chat_conversation_summaries
                WHERE status = 'pending'
                GROUP BY conversation_id
              )
            """
        ))
        sync_conn.execute(text(
            """
            CREATE UNIQUE INDEX uq_chat_summary_pending_conversation
            ON chat_conversation_summaries (conversation_id)
            WHERE status = 'pending'
            """
        ))

    if "uq_chat_summary_terminal_cursor" not in indexes:
        sync_conn.execute(text(
            """
            UPDATE chat_conversation_summaries
            SET status = 'failed',
                error_type = 'LeaseSuperseded',
                updated_at = CURRENT_TIMESTAMP
            WHERE status IN ('completed', 'superseded')
              AND id NOT IN (
                SELECT MAX(id)
                FROM chat_conversation_summaries
                WHERE status IN ('completed', 'superseded')
                GROUP BY conversation_id, covered_through_message_id
              )
            """
        ))
        sync_conn.execute(text(
            """
            CREATE UNIQUE INDEX uq_chat_summary_terminal_cursor
            ON chat_conversation_summaries (
                conversation_id, covered_through_message_id
            )
            WHERE status IN ('completed', 'superseded')
            """
        ))
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_additive_columns)
