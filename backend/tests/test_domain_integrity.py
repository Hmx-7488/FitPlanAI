import asyncio
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.sql.dml import Update

from app.api.meal import IngredientItem
from app.core.database import Base, _ensure_additive_columns, get_db
from app.main import app
from app.models.user import Checkin, Food, MealLog, MealRecognition, Plan, User
from app.schemas.checkin import CheckinCreate
from app.schemas.profile import ProfileCreate, ProfileUpdate


class DomainRequestValidationTests(unittest.TestCase):
    def test_profile_rejects_impossible_health_values_and_unknown_enums(self):
        invalid_payloads = (
            {"gender": "unknown"},
            {"age": -5},
            {"height": 0},
            {"weight": -1},
            {"activity_level": "extreme"},
        )
        base = {
            "gender": "male",
            "age": 30,
            "height": 175,
            "weight": 75,
            "target_weight": 70,
        }

        for override in invalid_payloads:
            with self.subTest(override=override), self.assertRaises(ValidationError):
                ProfileCreate(**{**base, **override})

    def test_checkin_rejects_non_iso_date_negative_weight_and_oversized_text(self):
        for override in (
            {"date": "not-a-date"},
            {"weight": -1},
            {"note": "x" * 2001},
        ):
            with self.subTest(override=override), self.assertRaises(ValidationError):
                CheckinCreate(**{
                    "user_id": 1,
                    "date": "2026-08-12",
                    **override,
                })

    def test_confirmed_ingredient_rejects_untrusted_ranges(self):
        for override in (
            {"estimated_weight_g": -10},
            {"confidence": 42},
            {"display_name": "x" * 101},
        ):
            payload = {
                "name": "chicken",
                "display_name": "鸡胸肉",
                "estimated_weight_g": 100,
                "confidence": 0.9,
                **override,
            }
            with self.subTest(override=override), self.assertRaises(ValidationError):
                IngredientItem(**payload)

    def test_profile_update_can_clear_only_nullable_fields(self):
        update = ProfileUpdate(target_weeks=None, body_fat_rate=None)
        self.assertEqual(
            update.model_dump(exclude_unset=True),
            {"target_weeks": None, "body_fat_rate": None},
        )
        with self.assertRaises(ValidationError):
            ProfileUpdate(weight=None)


class LegacyDomainMigrationTests(unittest.TestCase):
    def test_migration_adds_all_columns_and_archives_duplicates_before_unique_indexes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = create_engine(f"sqlite:///{Path(temp_dir) / 'legacy.db'}")
            try:
                with engine.begin() as conn:
                    conn.execute(text(
                        "CREATE TABLE users (id INTEGER PRIMARY KEY, gender VARCHAR(10), "
                        "age INTEGER, height FLOAT, weight FLOAT, target_weight FLOAT)"
                    ))
                    conn.execute(text(
                        "CREATE TABLE plans (id INTEGER PRIMARY KEY, user_id INTEGER, "
                        "daily_calorie_target INTEGER, meal_plan TEXT, workout_plan TEXT)"
                    ))
                    conn.execute(text(
                        "CREATE TABLE checkins (id INTEGER PRIMARY KEY, user_id INTEGER, "
                        "date VARCHAR(10), foods TEXT, exercises TEXT, weight FLOAT, "
                        "note TEXT, created_at DATETIME)"
                    ))
                    conn.execute(text(
                        "CREATE TABLE meal_logs (id INTEGER PRIMARY KEY, user_id INTEGER, "
                        "date VARCHAR(10), meal_type VARCHAR(20), image_path TEXT, "
                        "items_json TEXT, meal_total_json TEXT, created_at DATETIME)"
                    ))
                    conn.execute(text(
                        "CREATE TABLE recipe_image_jobs (id INTEGER PRIMARY KEY, "
                        "status VARCHAR(20), updated_at DATETIME)"
                    ))
                    conn.execute(text(
                        "INSERT INTO checkins VALUES "
                        "(1,1,'2026-08-12','old','','', '', '2026-08-12 08:00:00'),"
                        "(2,1,'2026-08-12','new','','', '', '2026-08-12 09:00:00')"
                    ))
                    conn.execute(text(
                        "INSERT INTO meal_logs VALUES "
                        "(1,1,'2026-08-12','lunch','old.jpg','[]','{}','2026-08-12 12:00:00'),"
                        "(2,1,'2026-08-12','lunch','new.jpg','[]','{}','2026-08-12 12:30:00')"
                    ))

                    _ensure_additive_columns(conn)
                    _ensure_additive_columns(conn)

                    user_columns = {
                        row[1] for row in conn.execute(text("PRAGMA table_info(users)"))
                    }
                    plan_columns = {
                        row[1] for row in conn.execute(text("PRAGMA table_info(plans)"))
                    }
                    recipe_job_columns = {
                        row[1]
                        for row in conn.execute(
                            text("PRAGMA table_info(recipe_image_jobs)")
                        )
                    }
                    self.assertTrue({
                        "target_weeks", "body_fat_rate", "activity_level",
                        "diet_preference", "goal_type", "forbidden_foods", "injuries",
                        "allergies", "training_days_per_week", "session_duration_minutes",
                        "training_location", "equipment", "training_experience",
                        "preferred_training_time", "region_preference", "meal_scenario",
                        "prep_time_limit_minutes", "created_at",
                    }.issubset(user_columns))
                    self.assertTrue({
                        "calorie_info_json", "macros_json", "meal_plan_json",
                        "workout_plan_json", "supplements_json", "summary", "created_at",
                    }.issubset(plan_columns))
                    self.assertTrue(
                        {"lease_owner", "lease_expires_at"}.issubset(
                            recipe_job_columns
                        )
                    )
                    self.assertEqual(
                        conn.execute(text("SELECT COUNT(*) FROM checkin_duplicates_archive")).scalar(),
                        1,
                    )
                    self.assertEqual(
                        conn.execute(text("SELECT foods FROM checkins")).scalar(),
                        "new",
                    )
                    self.assertEqual(
                        conn.execute(text("SELECT COUNT(*) FROM meal_log_duplicates_archive")).scalar(),
                        1,
                    )
                    self.assertEqual(
                        conn.execute(text("SELECT image_path FROM meal_logs")).scalar(),
                        "new.jpg",
                    )

                    with self.assertRaises(IntegrityError):
                        conn.execute(text(
                            "INSERT INTO checkins "
                            "(id,user_id,date,foods,exercises,note) "
                            "VALUES (3,1,'2026-08-12','','','')"
                        ))
            finally:
                engine.dispose()

    def test_summary_migration_preserves_rows_and_normalizes_duplicate_claims(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = create_engine(f"sqlite:///{Path(temp_dir) / 'summary-legacy.db'}")
            try:
                with engine.begin() as conn:
                    conn.execute(text(
                        """
                        CREATE TABLE chat_conversation_summaries (
                            id INTEGER PRIMARY KEY,
                            conversation_id INTEGER NOT NULL,
                            summary_json TEXT,
                            summary_text TEXT,
                            covered_through_message_id INTEGER NOT NULL,
                            source_message_count INTEGER,
                            estimated_tokens INTEGER,
                            model VARCHAR(100),
                            status VARCHAR(20),
                            error_type VARCHAR(100),
                            created_at DATETIME,
                            updated_at DATETIME
                        )
                        """
                    ))
                    conn.execute(text(
                        """
                        INSERT INTO chat_conversation_summaries VALUES
                        (1, 7, '{}', '', 10, 2, 0, 'm', 'pending', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                        (2, 7, '{}', '', 12, 2, 0, 'm', 'pending', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                        (3, 7, '{}', 'old', 8, 2, 1, 'm', 'completed', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                        (4, 7, '{}', 'new', 8, 2, 1, 'm', 'superseded', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """
                    ))

                    _ensure_additive_columns(conn)
                    _ensure_additive_columns(conn)

                    rows = conn.execute(text(
                        "SELECT id, status, error_type FROM chat_conversation_summaries ORDER BY id"
                    )).fetchall()
                    self.assertEqual(len(rows), 4)
                    self.assertEqual(rows[0][1:], ("failed", "LeaseSuperseded"))
                    self.assertEqual(rows[1][1], "pending")
                    self.assertEqual(rows[2][1:], ("failed", "LeaseSuperseded"))
                    self.assertEqual(rows[3][1], "superseded")

                    index_names = {
                        row[1]
                        for row in conn.execute(text(
                            "PRAGMA index_list(chat_conversation_summaries)"
                        ))
                    }
                    self.assertIn("uq_chat_summary_pending_conversation", index_names)
                    self.assertIn("uq_chat_summary_terminal_cursor", index_names)

                    with self.assertRaises(IntegrityError):
                        conn.execute(text(
                            """
                            INSERT INTO chat_conversation_summaries (
                                id, conversation_id, covered_through_message_id, status
                            ) VALUES (5, 7, 20, 'pending')
                            """
                        ))
            finally:
                engine.dispose()


class DomainApiIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "domain.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

        async def override_db():
            async with self.sessions() as session:
                yield session

        app.dependency_overrides[get_db] = override_db

        async def prepare():
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await conn.run_sync(_ensure_additive_columns)
            async with self.sessions() as session:
                session.add(User(
                    id=1,
                    gender="male",
                    age=30,
                    height=175,
                    weight=75,
                    target_weight=70,
                    target_weeks=8,
                    body_fat_rate=20,
                    activity_level="medium",
                    diet_preference="balanced",
                    goal_type="fat_loss",
                ))
                session.add(Plan(
                    id=1,
                    user_id=1,
                    daily_calorie_target=1800,
                    calorie_info_json=json.dumps({
                        "bmr": 1700,
                        "tdee": 2400,
                        "target_calories": 1800,
                        "deficit": 600,
                    }),
                    macros_json="{}",
                    meal_plan="meal",
                    workout_plan="workout",
                    workout_plan_json='{"weekly_plan":[]}',
                    created_at=datetime(2026, 8, 12, 8, 0),
                ))
                session.add(Checkin(
                    id=10,
                    user_id=1,
                    date="2026-08-11",
                    note="baseline",
                ))
                session.add_all([
                    Food(
                        id=1,
                        name_zh="鸡胸肉",
                        aliases="[]",
                        category="protein",
                        calories_kcal=133,
                        protein_g=31,
                        carbs_g=0,
                        fat_g=1.2,
                        diet_tags='["high_protein", "low_carb"]',
                        common_dishes="[]",
                    ),
                    Food(
                        id=2,
                        name_zh="米饭",
                        aliases="[]",
                        category="carb",
                        calories_kcal=116,
                        protein_g=2.6,
                        carbs_g=25.9,
                        fat_g=0.3,
                        diet_tags="[]",
                        common_dishes="[]",
                    ),
                ])
                await session.commit()

        asyncio.run(prepare())
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        asyncio.run(self.engine.dispose())
        self.temp_dir.cleanup()

    def test_checkin_is_an_upsert_and_nullable_profile_fields_can_be_cleared(self):
        first = self.client.post("/api/checkin/create", json={
            "user_id": 1,
            "date": "2026-08-12",
            "foods": "old",
        })
        second = self.client.post("/api/checkin/create", json={
            "user_id": 1,
            "date": "2026-08-12",
            "foods": "new",
        })
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(first.json()["id"], second.json()["id"])

        async def check_count():
            async with self.sessions() as session:
                statement = select(Checkin).where(Checkin.date == "2026-08-12")
                rows = list((await session.execute(statement)).scalars().all())
                count = len(rows)
                row = rows[0]
                return count, row.foods

        self.assertEqual(asyncio.run(check_count()), (1, "new"))

        response = self.client.patch("/api/profile/1", json={
            "target_weeks": None,
            "body_fat_rate": None,
        })
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["target_weeks"])
        self.assertIsNone(response.json()["body_fat_rate"])

    def test_latest_plan_is_the_single_calorie_source_for_dashboard_and_meals(self):
        dashboard = self.client.get("/api/dashboard/1")
        summary = self.client.get("/api/meal/daily-summary/1?date=2026-08-12")
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(dashboard.json()["meal_summary"]["target_kcal"], 1800)
        self.assertEqual(summary.json()["daily_target_kcal"], 1800)
        self.assertEqual(summary.json()["estimated_tdee_kcal"], 2400)

    def test_review_carries_plan_and_checkin_source_versions(self):
        async def seed():
            async with self.sessions() as session:
                session.add(Checkin(
                    id=50,
                    user_id=1,
                    date="2026-08-12",
                    weight=75,
                    note="状态正常",
                ))
                await session.commit()

        asyncio.run(seed())
        with patch(
            "app.services.checkin_service.run_review_workflow",
            new=AsyncMock(return_value={
                "review_summary": "复盘",
                "next_day_advice": "保持",
            }),
        ):
            response = self.client.get("/api/checkin/review/1")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["source_plan_id"], 1)
        self.assertEqual(data["source_daily_calorie_target"], 1800)
        self.assertEqual(data["source_workout_plan_json"], '{"weekly_plan":[]}')
        self.assertEqual(data["source_checkin_id"], 50)

    def test_calorie_adjustment_uses_latest_plan_and_atomic_baseline(self):
        payload = {
            "user_id": 1,
            "plan_id": 1,
            "source_checkin_id": 10,
            "base_daily_calorie_target": 1800,
            "daily_calorie_target": 1700,
        }
        first = self.client.post("/api/plan/adjust-calories", json=payload)
        stale = self.client.post("/api/plan/adjust-calories", json={
            **payload,
            "daily_calorie_target": 1600,
        })
        self.assertEqual(first.status_code, 200)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(first.json()["daily_calorie_target"], 1700)

    def test_calorie_and_workout_adjustments_reject_plan_inserted_after_initial_read(self):
        class InterleavingSession:
            def __init__(self, inner):
                self.inner = inner
                self.injected = False

            def __getattr__(self, name):
                return getattr(self.inner, name)

            async def execute(self, statement, *args, **kwargs):
                if isinstance(statement, Update) and not self.injected:
                    self.injected = True
                    self.inner.add(Plan(
                        user_id=1,
                        daily_calorie_target=1900,
                        calorie_info_json='{"tdee":2400,"target_calories":1900}',
                        macros_json="{}",
                        meal_plan="new meal",
                        workout_plan="new workout",
                        workout_plan_json='{"weekly_plan":[]}',
                        created_at=datetime(2099, 1, 1),
                    ))
                    await self.inner.flush()
                return await self.inner.execute(statement, *args, **kwargs)

        async def override_interleaving_db():
            async with self.sessions() as session:
                yield InterleavingSession(session)

        app.dependency_overrides[get_db] = override_interleaving_db
        calorie = self.client.post("/api/plan/adjust-calories", json={
            "user_id": 1,
            "plan_id": 1,
            "source_checkin_id": 10,
            "base_daily_calorie_target": 1800,
            "daily_calorie_target": 1700,
        })
        workout = self.client.post("/api/plan/adjust-workout", json={
            "user_id": 1,
            "plan_id": 1,
            "source_checkin_id": 10,
            "base_workout_plan_json": '{"weekly_plan":[]}',
            "adjusted_workout_plan_json": json.dumps({
                "weekly_plan": [{
                    "day": 1,
                    "theme": "cardio",
                    "cardio": {"type": "walk", "duration_minutes": 20},
                }],
            }),
        })
        self.assertEqual(calorie.status_code, 409)
        self.assertEqual(workout.status_code, 409)

    def test_adjustments_reject_review_after_a_new_checkin(self):
        async def add_checkin():
            async with self.sessions() as session:
                session.add(Checkin(
                    id=11,
                    user_id=1,
                    date="2026-08-12",
                    note="new evidence",
                ))
                await session.commit()

        asyncio.run(add_checkin())
        calorie = self.client.post("/api/plan/adjust-calories", json={
            "user_id": 1,
            "plan_id": 1,
            "source_checkin_id": 10,
            "base_daily_calorie_target": 1800,
            "daily_calorie_target": 1700,
        })
        workout = self.client.post("/api/plan/adjust-workout", json={
            "user_id": 1,
            "plan_id": 1,
            "source_checkin_id": 10,
            "base_workout_plan_json": '{"weekly_plan":[]}',
            "adjusted_workout_plan_json": json.dumps({
                "weekly_plan": [{
                    "day": 1,
                    "theme": "cardio",
                    "cardio": {"type": "walk", "duration_minutes": 20},
                }],
            }),
        })

        self.assertEqual(calorie.status_code, 409)
        self.assertEqual(workout.status_code, 409)

    def test_adjustment_rejects_review_after_same_day_checkin_is_edited(self):
        updated = self.client.post("/api/checkin/create", json={
            "user_id": 1,
            "date": "2026-08-11",
            "note": "edited evidence",
        })
        self.assertEqual(updated.status_code, 200)
        self.assertNotEqual(updated.json()["id"], 10)

        response = self.client.post("/api/plan/adjust-calories", json={
            "user_id": 1,
            "plan_id": 1,
            "source_checkin_id": 10,
            "base_daily_calorie_target": 1800,
            "daily_calorie_target": 1700,
        })
        self.assertEqual(response.status_code, 409)

    def test_food_diet_tags_are_applied_as_an_and_filter(self):
        response = self.client.get("/api/foods?diet_tags=high_protein,low_carb")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["items"][0]["name_zh"], "鸡胸肉")

        high_protein_only = self.client.get("/api/foods?diet_tags=high_protein")
        self.assertEqual(high_protein_only.status_code, 200)
        self.assertEqual(high_protein_only.json()["total"], 1)

    def test_food_diet_tags_reject_wildcards_and_unknown_values(self):
        for query in ("%", "_", "unknown", "high_protein,%"):
            with self.subTest(query=query):
                response = self.client.get("/api/foods", params={"diet_tags": query})
                self.assertEqual(response.status_code, 400)

    def test_calculate_keeps_confirmed_name_and_weight_and_cleans_replaced_image(self):
        upload_dir = Path(self.temp_dir.name) / "meals"
        upload_dir.mkdir()
        old_image = upload_dir / "old.png"
        new_image = upload_dir / "new.png"
        old_image.write_bytes(b"old")
        new_image.write_bytes(b"new")

        async def seed():
            async with self.sessions() as session:
                session.add(MealLog(
                    user_id=1,
                    date="2026-08-12",
                    meal_type="lunch",
                    image_path=str(old_image),
                    items_json="[]",
                    meal_total_json="{}",
                ))
                session.add(MealRecognition(
                    id="recognition-1",
                    user_id=1,
                    meal_type="lunch",
                    image_path=str(new_image),
                    ingredients_json="[]",
                ))
                await session.commit()

        asyncio.run(seed())
        llm = MagicMock()
        llm.invoke.return_value = SimpleNamespace(content=json.dumps({
            "items": [{
                "dish_name": "模型改写名称",
                "estimated_portion_g": 500,
                "calories_kcal": 665,
                "protein_g": 155,
                "carbs_g": 0,
                "fat_g": 6,
            }],
        }, ensure_ascii=False))

        with (
            patch("app.api.meal.get_vision_llm", return_value=llm),
            patch("app.api.meal.UPLOAD_DIR", upload_dir),
            patch("app.api.meal._today", return_value="2026-08-12"),
        ):
            response = self.client.post("/api/meal/calculate", json={
                "recognition_id": "recognition-1",
                "meal_type": "lunch",
                "ingredients": [{
                    "name": "chicken",
                    "display_name": "鸡胸肉",
                    "estimated_weight_g": 100,
                    "confidence": 0.9,
                }],
            })

        self.assertEqual(response.status_code, 200)
        item = response.json()["items"][0]
        self.assertEqual(item["dish_name"], "鸡胸肉")
        self.assertEqual(item["estimated_portion_g"], 100)
        self.assertEqual(response.json()["meal_total"]["calories_kcal"], 133)
        self.assertFalse(old_image.exists())
        self.assertTrue(new_image.exists())

    def test_failed_analyze_write_removes_new_upload_and_keeps_existing_meal(self):
        upload_dir = Path(self.temp_dir.name) / "failed-analyze"
        upload_dir.mkdir()
        old_image = upload_dir / "old.png"
        old_image.write_bytes(b"old")

        async def seed():
            async with self.sessions() as session:
                session.add(MealLog(
                    user_id=1,
                    date="2026-08-12",
                    meal_type="lunch",
                    image_path=str(old_image),
                    items_json="[]",
                    meal_total_json='{"calories_kcal":100}',
                ))
                await session.commit()

        asyncio.run(seed())

        class FailingCommitSession:
            def __init__(self, inner):
                self.inner = inner

            def __getattr__(self, name):
                return getattr(self.inner, name)

            async def commit(self):
                raise RuntimeError("write failed")

        async def override_failing_db():
            async with self.sessions() as session:
                yield FailingCommitSession(session)

        app.dependency_overrides[get_db] = override_failing_db
        items = [{
            "dish_name": "鸡胸肉",
            "estimated_portion_g": 100,
            "calories_kcal": 133,
            "protein_g": 31,
            "carbs_g": 0,
            "fat_g": 1.2,
        }]
        with (
            patch("app.api.meal.UPLOAD_DIR", upload_dir),
            patch("app.api.meal._today", return_value="2026-08-12"),
            patch("app.api.meal.validate_image", return_value=("image/png", 100, 100)),
            patch("app.api.meal.recognize_food_items", new=AsyncMock(return_value=items)),
        ):
            response = self.client.post(
                "/api/meal/analyze",
                data={"user_id": "1", "meal_type": "lunch"},
                files={"image": ("meal.png", b"fake-image", "image/png")},
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(list(upload_dir.iterdir()), [old_image])

        async def stored_path():
            async with self.sessions() as session:
                return (await session.execute(select(MealLog.image_path))).scalar_one()

        self.assertEqual(asyncio.run(stored_path()), str(old_image))

    def test_failed_calculate_write_keeps_recognition_and_both_images(self):
        upload_dir = Path(self.temp_dir.name) / "failed-calculate"
        upload_dir.mkdir()
        old_image = upload_dir / "old.png"
        new_image = upload_dir / "new.png"
        old_image.write_bytes(b"old")
        new_image.write_bytes(b"new")

        async def seed():
            async with self.sessions() as session:
                session.add(MealLog(
                    user_id=1,
                    date="2026-08-12",
                    meal_type="dinner",
                    image_path=str(old_image),
                    items_json="[]",
                    meal_total_json="{}",
                ))
                session.add(MealRecognition(
                    id="recognition-fail",
                    user_id=1,
                    meal_type="dinner",
                    image_path=str(new_image),
                    ingredients_json="[]",
                ))
                await session.commit()

        asyncio.run(seed())

        class FailingCommitSession:
            def __init__(self, inner):
                self.inner = inner

            def __getattr__(self, name):
                return getattr(self.inner, name)

            async def commit(self):
                raise RuntimeError("write failed")

        async def override_failing_db():
            async with self.sessions() as session:
                yield FailingCommitSession(session)

        app.dependency_overrides[get_db] = override_failing_db
        llm = MagicMock()
        llm.invoke.return_value = SimpleNamespace(content=json.dumps({
            "items": [{
                "dish_name": "鸡胸肉",
                "estimated_portion_g": 100,
                "calories_kcal": 133,
                "protein_g": 31,
                "carbs_g": 0,
                "fat_g": 1.2,
            }],
        }, ensure_ascii=False))
        with (
            patch("app.api.meal.get_vision_llm", return_value=llm),
            patch("app.api.meal.UPLOAD_DIR", upload_dir),
            patch("app.api.meal._today", return_value="2026-08-12"),
        ):
            response = self.client.post("/api/meal/calculate", json={
                "recognition_id": "recognition-fail",
                "meal_type": "dinner",
                "ingredients": [{
                    "name": "chicken",
                    "display_name": "鸡胸肉",
                    "estimated_weight_g": 100,
                    "confidence": 0.9,
                }],
            })

        self.assertEqual(response.status_code, 500)
        self.assertTrue(old_image.exists())
        self.assertTrue(new_image.exists())

        async def stored_state():
            async with self.sessions() as session:
                meal_path = (await session.execute(
                    select(MealLog.image_path).where(MealLog.meal_type == "dinner")
                )).scalar_one()
                recognition = await session.get(MealRecognition, "recognition-fail")
                return meal_path, recognition is not None

        self.assertEqual(asyncio.run(stored_state()), (str(old_image), True))

    def test_internal_exception_details_are_not_returned(self):
        with patch(
            "app.api.checkin.create_checkin",
            new=AsyncMock(side_effect=RuntimeError("database-password-marker")),
        ):
            response = self.client.post("/api/checkin/create", json={
                "user_id": 1,
                "date": "2026-08-12",
            })
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("database-password-marker", response.text)


if __name__ == "__main__":
    unittest.main()
