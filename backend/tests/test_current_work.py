import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.main import app
from app.api.meal import _food_match_rank, _normalize_meal_items
from app.graph.workflow import (
    _build_constraint_fallback_meal,
    _build_constraint_fallback_workout,
    _exercise_conflicts_with_injuries,
    _sanitize_agent_plan_output,
    _sort_food_candidates_for_preference,
    review_workout_adjustment,
)
from app.models.user import Checkin, Exercise, Food, MealLog, Plan, User
from app.services.supplement_service import (
    _condition_conflicts,
    _source_conflicts,
    _validate_llm_recommendations,
    generate_supplement_recommendations,
)
from app.tools.calorie_tools import calc_macros


class SupplementRecommendationTests(unittest.TestCase):
    def setUp(self):
        self.candidates = [
            {
                "name": "肌酸",
                "name_en": "creatine monohydrate",
                "triggers": ["muscle_gain", "strength"],
                "dosage": "每天 5g",
                "timing": "随餐",
                "contraindications": ["肾功能异常"],
            }
        ]

    def test_llm_cannot_invent_supplement_or_override_canonical_fields(self):
        raw_items = [
            {
                "name": "神奇燃脂药",
                "reason": "模型虚构内容",
                "dosage": "无限量",
            },
            {
                "name": "肌酸",
                "reason": "  配合增肌训练使用。  ",
                "dosage": "每天 100g",
                "timing": "空腹",
                "contraindications": [],
            },
        ]

        result = _validate_llm_recommendations(raw_items, self.candidates)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "肌酸")
        self.assertEqual(result[0]["dosage"], "每天 5g")
        self.assertEqual(result[0]["timing"], "随餐")
        self.assertEqual(result[0]["contraindications"], ["肾功能异常"])

    def test_matching_medical_condition_is_filtered(self):
        supplement = {"contraindications": ["严重肾功能不全"]}
        self.assertTrue(_condition_conflicts(supplement, ["肾功能异常"]))
        self.assertFalse(_condition_conflicts(supplement, ["膝关节疼痛"]))

        shellfish = {"contraindications": ["贝壳类过敏（选植物源）"]}
        self.assertTrue(_condition_conflicts(shellfish, ["海鲜过敏"]))

    def test_source_and_vegetarian_filters_are_deterministic(self):
        fish_oil = {"name": "鱼油（Omega-3）", "source_tags": ["fish"]}
        glucosamine = {"name": "氨基葡萄糖", "source_tags": ["shellfish"]}
        self.assertTrue(_source_conflicts(fish_oil, ["不吃鱼"], "balanced"))
        self.assertTrue(_source_conflicts(fish_oil, [], "vegetarian"))
        self.assertTrue(_source_conflicts(glucosamine, ["海鲜过敏"], "balanced"))

    def test_profile_schema_english_allergies_filter_matching_sources(self):
        cases = (
            ("fish", "fish"),
            ("milk", "milk"),
            ("shrimp", "shellfish"),
        )
        for restriction, source_tag in cases:
            with self.subTest(restriction=restriction, source_tag=source_tag):
                self.assertTrue(_source_conflicts(
                    {"source_tags": [source_tag]},
                    [restriction],
                    "balanced",
                ))

    def test_invalid_llm_output_falls_back_to_safe_candidates(self):
        llm = MagicMock()
        llm.invoke.return_value.content = '[{"name":"虚构补剂","reason":"不可信"}]'
        with (
            patch("app.services.supplement_service._match_supplements", return_value=self.candidates),
            patch("app.services.supplement_service.retrieve_knowledge", return_value=[]),
            patch("app.services.supplement_service.ChatOpenAI", return_value=llm),
        ):
            result = asyncio.run(generate_supplement_recommendations("muscle_gain", []))

        self.assertEqual([item["name"] for item in result], ["肌酸"])
        self.assertEqual(result[0]["dosage"], "每天 5g")

    def test_supplement_data_failure_degrades_to_empty_recommendations(self):
        with patch(
            "app.services.supplement_service._match_supplements",
            side_effect=json.JSONDecodeError("bad data", "", 0),
        ):
            result = asyncio.run(generate_supplement_recommendations("muscle_gain", []))

        self.assertEqual(result, [])

    def test_knowledge_failure_keeps_deterministic_candidates_for_local_fallback(self):
        llm = MagicMock()
        llm.invoke.side_effect = RuntimeError("provider unavailable")
        with (
            patch("app.services.supplement_service._match_supplements", return_value=self.candidates),
            patch("app.services.supplement_service.retrieve_knowledge", side_effect=OSError("index unavailable")),
            patch("app.services.supplement_service.ChatOpenAI", return_value=llm),
        ):
            result = asyncio.run(generate_supplement_recommendations("muscle_gain", []))

        self.assertEqual([item["name"] for item in result], ["肌酸"])


class ApiDatabaseTestCase(unittest.TestCase):
    database_name = "api-test.db"

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / self.database_name
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

        async def override_db():
            async with self.session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        asyncio.run(self.prepare_database())
        self.client = TestClient(app)

    async def prepare_database(self):
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        asyncio.run(self.engine.dispose())
        self.temp_dir.cleanup()


class WorkoutAdjustmentEndpointTests(ApiDatabaseTestCase):
    database_name = "workout-adjustment.db"

    async def prepare_database(self):
        await super().prepare_database()
        async with self.session_factory() as session:
            session.add_all([
                User(id=1, gender="male", age=30, height=175, weight=75, target_weight=70),
                User(id=2, gender="female", age=28, height=165, weight=60, target_weight=55),
                Checkin(id=1, user_id=1, date="2026-08-11"),
                Plan(
                    id=1,
                    user_id=1,
                    daily_calorie_target=2000,
                    calorie_info_json='{"tdee":2500,"target_calories":2000}',
                    macros_json='{"protein_g":120,"carbs_g":200,"fat_g":60}',
                    meal_plan="meal",
                    workout_plan="old workout",
                ),
                Exercise(
                    id="0025", name="barbell bench press", name_zh="杠铃卧推",
                    body_part="chest", equipment="barbell",
                ),
            ])
            await session.commit()

    def post_adjustment(
        self,
        payload: object,
        user_id: int = 1,
        plan_id: int = 1,
        source_checkin_id: int = 1,
        base_workout_plan_json: str = "",
    ):
        return self.client.post(
            "/api/plan/adjust-workout",
            json={
                "user_id": user_id,
                "plan_id": plan_id,
                "source_checkin_id": source_checkin_id,
                "base_workout_plan_json": base_workout_plan_json,
                "adjusted_workout_plan_json": json.dumps(payload, ensure_ascii=False),
            },
        )

    def test_valid_plan_is_normalized_and_written(self):
        payload = {
            "weekly_plan": [{
                "day": 1,
                "theme": "chest",
                "duration_minutes": 60,
                "exercises": [{
                    "exercise_id": "0025",
                    "sets": 3,
                    "reps": "8-12",
                    "_flagged_for_replacement": "肩部不适",
                }],
                "cardio": {"type": "bike", "duration_minutes": 20},
            }],
        }

        response = self.post_adjustment(payload)

        self.assertEqual(response.status_code, 200)
        stored = json.loads(response.json()["workout_plan_json"])
        self.assertEqual(stored["weekly_plan"][0]["exercises"][0]["sets"], 3)
        self.assertEqual(
            stored["weekly_plan"][0]["exercises"][0]["_flagged_for_replacement"],
            "肩部不适",
        )
        self.assertIn("0025 3x8-12", response.json()["workout_plan"])

    def test_malformed_nested_plan_is_rejected_without_server_error(self):
        response = self.post_adjustment({"weekly_plan": "not-a-list"})
        self.assertEqual(response.status_code, 400)

        response = self.post_adjustment({
            "weekly_plan": [{"day": 1, "theme": "chest", "cardio": {"type": "bike"}}]
        })
        self.assertEqual(response.status_code, 400)

    def test_all_rest_plan_is_rejected(self):
        response = self.post_adjustment({
            "weekly_plan": [{"day": 1, "theme": "rest"}],
        })

        self.assertEqual(response.status_code, 400)

    def test_empty_week_and_out_of_range_sets_are_rejected(self):
        self.assertEqual(self.post_adjustment({"weekly_plan": []}).status_code, 400)
        response = self.post_adjustment({
            "weekly_plan": [{
                "day": 1,
                "theme": "chest",
                "exercises": [{"exercise_id": "0025", "sets": 99, "reps": "8"}],
            }]
        })
        self.assertEqual(response.status_code, 400)

    def test_duplicate_days_rest_content_and_unknown_exercise_are_rejected(self):
        duplicate = {
            "weekly_plan": [
                {"day": 1, "theme": "rest"},
                {"day": 1, "theme": "rest"},
            ]
        }
        self.assertEqual(self.post_adjustment(duplicate).status_code, 400)

        rest_with_exercise = {
            "weekly_plan": [{
                "day": 1,
                "theme": "rest",
                "exercises": [{"exercise_id": "0025", "sets": 3, "reps": "8"}],
            }]
        }
        self.assertEqual(self.post_adjustment(rest_with_exercise).status_code, 400)

        unknown = {
            "weekly_plan": [{
                "day": 1,
                "theme": "chest",
                "exercises": [{"exercise_id": "9999", "sets": 3, "reps": "8"}],
            }]
        }
        self.assertEqual(self.post_adjustment(unknown).status_code, 400)

    def test_empty_negative_and_extreme_reps_are_rejected(self):
        for reps in ("", -1, 1001):
            payload = {
                "weekly_plan": [{
                    "day": 1,
                    "theme": "chest",
                    "exercises": [{"exercise_id": "0025", "sets": 3, "reps": reps}],
                }]
            }
            self.assertEqual(self.post_adjustment(payload).status_code, 400)

    def test_user_without_plan_returns_404(self):
        response = self.post_adjustment({
            "weekly_plan": [{"day": 1, "theme": "rest"}]
        }, user_id=2)
        self.assertEqual(response.status_code, 404)

    def test_stale_plan_id_is_rejected_without_overwriting_latest_plan(self):
        async def add_newer_plan():
            async with self.session_factory() as session:
                session.add(Plan(
                    id=2,
                    user_id=1,
                    daily_calorie_target=2000,
                    calorie_info_json='{"tdee":2500,"target_calories":2000}',
                    macros_json='{"protein_g":120,"carbs_g":200,"fat_g":60}',
                    meal_plan="meal",
                    workout_plan="new workout",
                    workout_plan_json='{"weekly_plan":[{"day":1,"theme":"rest"}]}',
                    created_at=datetime(2099, 8, 11, 12, 0),
                ))
                await session.commit()

        asyncio.run(add_newer_plan())
        payload = {
            "weekly_plan": [{
                "day": 1,
                "theme": "chest",
                "exercises": [{"exercise_id": "0025", "sets": 3, "reps": "8"}],
            }],
        }

        response = self.post_adjustment(payload, plan_id=1)

        self.assertEqual(response.status_code, 409)

        async def latest_workout_json():
            async with self.session_factory() as session:
                return (await session.get(Plan, 2)).workout_plan_json

        self.assertEqual(
            asyncio.run(latest_workout_json()),
            '{"weekly_plan":[{"day":1,"theme":"rest"}]}',
        )

    def test_stale_same_plan_baseline_is_rejected_without_overwrite(self):
        first_payload = {
            "weekly_plan": [{
                "day": 1,
                "theme": "chest",
                "exercises": [{"exercise_id": "0025", "sets": 3, "reps": "8"}],
            }],
        }
        stale_payload = {
            "weekly_plan": [{
                "day": 1,
                "theme": "chest",
                "exercises": [{"exercise_id": "0025", "sets": 5, "reps": "5"}],
            }],
        }

        first_response = self.post_adjustment(first_payload, base_workout_plan_json="")
        stale_response = self.post_adjustment(stale_payload, base_workout_plan_json="")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(stale_response.status_code, 409)

        async def stored_workout():
            async with self.session_factory() as session:
                stored_plan = await session.get(Plan, 1)
                return stored_plan.workout_plan_json, stored_plan.workout_plan

        stored_json, stored_text = asyncio.run(stored_workout())
        stored = json.loads(stored_json)
        self.assertEqual(stored["weekly_plan"][0]["exercises"][0]["sets"], 3)
        self.assertIn("0025 3x8", stored_text)
        self.assertNotIn("0025 5x5", stored_text)

    def test_workout_adjustment_requires_concurrency_baseline(self):
        response = self.client.post(
            "/api/plan/adjust-workout",
            json={
                "user_id": 1,
                "plan_id": 1,
                "adjusted_workout_plan_json": '{"weekly_plan":[]}',
            },
        )

        self.assertEqual(response.status_code, 422)

        oversized = self.post_adjustment(
            {"weekly_plan": []},
            base_workout_plan_json="x" * 100_001,
        )
        self.assertEqual(oversized.status_code, 422)


class MealDailySummaryTests(ApiDatabaseTestCase):
    database_name = "meal-summary.db"

    async def prepare_database(self):
        await super().prepare_database()
        async with self.session_factory() as session:
            session.add(User(
                id=1,
                gender="male",
                age=30,
                height=175,
                weight=75,
                target_weight=70,
                activity_level="medium",
                goal_type="fat_loss",
            ))
            session.add_all([
                MealLog(
                    id=1, user_id=1, date="2026-08-10", meal_type="breakfast",
                    meal_total_json='{"calories_kcal":300,"protein_g":20,"carbs_g":30,"fat_g":10}',
                    items_json='[{"dish_name":"鸡蛋"}]', created_at=datetime(2026, 8, 10, 8, 0),
                ),
                MealLog(
                    id=2, user_id=1, date="2026-08-10", meal_type="lunch",
                    meal_total_json='{"calories_kcal":500,"protein_g":30,"carbs_g":60,"fat_g":15}',
                    items_json='[]', created_at=datetime(2026, 8, 10, 12, 0),
                ),
                MealLog(
                    id=4, user_id=1, date="2026-08-09", meal_type="dinner",
                    meal_total_json='{"calories_kcal":900,"protein_g":50,"carbs_g":100,"fat_g":25}',
                    items_json='[]', created_at=datetime(2026, 8, 9, 19, 0),
                ),
                MealLog(
                    id=5, user_id=1, date="2026-08-10", meal_type="legacy",
                    meal_total_json='{"calories_kcal":9999}', items_json='[]',
                    created_at=datetime(2026, 8, 10, 20, 0),
                ),
            ])
            await session.commit()

    def test_summary_groups_meals_and_isolates_date(self):
        response = self.client.get("/api/meal/daily-summary/1?date=2026-08-10")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["meal_count"], 2)
        self.assertEqual(data["consumed_kcal"], 800)
        self.assertEqual(data["consumed"]["protein_g"], 50)
        self.assertEqual(data["meals"]["lunch"]["id"], 2)
        self.assertNotIn("legacy", data["meals"])

    def test_invalid_date_is_rejected(self):
        response = self.client.get("/api/meal/daily-summary/1?date=2026-8-10")
        self.assertEqual(response.status_code, 400)

    def test_unknown_user_returns_404(self):
        response = self.client.get("/api/meal/daily-summary/99?date=2026-08-10")
        self.assertEqual(response.status_code, 404)


class MealOutputValidationTests(unittest.TestCase):
    def test_rejects_non_numeric_negative_and_extreme_values(self):
        for bad_item in (
            {"dish_name": "鸡胸肉", "estimated_portion_g": "many", "calories_kcal": 10},
            {"dish_name": "鸡胸肉", "estimated_portion_g": 100, "calories_kcal": -1},
            {"dish_name": "鸡胸肉", "estimated_portion_g": 100, "calories_kcal": 99999},
        ):
            with self.assertRaises(ValueError):
                _normalize_meal_items([bad_item])

        with self.assertRaises(ValueError):
            _normalize_meal_items([{"dish_name": "未知菜", "estimated_portion_g": 100}])

    def test_numeric_strings_are_normalized_without_type_error(self):
        result = _normalize_meal_items([{
            "dish_name": "鸡胸肉",
            "estimated_portion_g": "120",
            "calories_kcal": "198",
            "protein_g": "37",
            "carbs_g": 0,
            "fat_g": "4.3",
        }])
        self.assertEqual(result[0]["estimated_portion_g"], 120.0)
        self.assertEqual(result[0]["calories_kcal"], 198.0)

    def test_exact_dish_name_outranks_common_dish_reference(self):
        ingredient = Food(
            id=1, name_zh="鸡蛋", category="protein", calories_kcal=144,
            protein_g=13, carbs_g=3, fat_g=9, common_dishes='["番茄炒蛋"]',
        )
        exact = Food(
            id=2, name_zh="番茄炒蛋", category="dish", calories_kcal=100,
            protein_g=5, carbs_g=7, fat_g=6,
        )
        self.assertLess(_food_match_rank(exact, "番茄炒蛋"), _food_match_rank(ingredient, "番茄炒蛋"))


class AgentPlanValidationTests(unittest.TestCase):
    def assert_executable_meal_plan(self, plan, foods, target_kcal, target_macros):
        food_by_id = {food["id"]: food for food in foods}
        meals = plan["meals"]
        self.assertGreaterEqual(len({meal["meal_type"] for meal in meals}), 2)
        self.assertTrue(all(len(meal["items"]) <= 4 for meal in meals))
        items = [item for meal in meals for item in meal["items"]]
        self.assertTrue(items)
        self.assertLessEqual(max(item["portion_g"] for item in items), 600)
        self.assertLessEqual(sum(item["portion_g"] for item in items), 3000)

        totals = {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
        for item in items:
            food = food_by_id[item["food_id"]]
            factor = item["portion_g"] / 100
            totals["calories"] += food["calories_kcal"] * factor
            for nutrient in ("protein_g", "carbs_g", "fat_g"):
                totals[nutrient] += food[nutrient] * factor
        self.assertTrue(0.85 <= totals["calories"] / target_kcal <= 1.15)
        for nutrient in ("protein_g", "carbs_g", "fat_g"):
            self.assertTrue(0.85 <= totals[nutrient] / target_macros[nutrient] <= 1.15)

    def test_local_meal_fallback_matches_calorie_and_macro_targets(self):
        foods = [
            {"id": 1, "name": "鸡胸肉", "calories_kcal": 165, "protein_g": 31, "carbs_g": 0, "fat_g": 3.6},
            {"id": 2, "name": "米饭", "calories_kcal": 130, "protein_g": 2.7, "carbs_g": 28, "fat_g": 0.3},
            {"id": 3, "name": "橄榄油", "calories_kcal": 900, "protein_g": 0, "carbs_g": 0, "fat_g": 100},
        ]
        macros = {"protein_g": 150, "carbs_g": 250, "fat_g": 45}
        fallback = {
            "meal_plan": _build_constraint_fallback_meal(foods, 2000, macros),
            "workout_plan": _build_constraint_fallback_workout([], 1, 60),
        }

        result = _sanitize_agent_plan_output(
            fallback,
            foods,
            [],
            2000,
            enforce_target=True,
            target_macros=macros,
            training_constraints={"training_days_per_week": 1, "session_duration_minutes": 60},
        )

        self.assert_executable_meal_plan(result["meal_plan"], foods, 2000, macros)

    def test_local_meal_fallback_handles_real_low_carb_candidates_with_bounds(self):
        raw_foods = json.loads(
            (Path(__file__).parent.parent / "data" / "foods" / "foods_zh.json").read_text(
                encoding="utf-8-sig"
            )
        )
        foods = [
            {
                "id": food["id"],
                "name": food["name_zh"],
                "category": food["category"],
                "calories_kcal": food["calories_kcal"],
                "protein_g": food["protein_g"],
                "carbs_g": food["carbs_g"],
                "fat_g": food["fat_g"],
            }
            for food in raw_foods
            if "low_carb" in food.get("diet_tags", [])
        ]
        macros = {"protein_g": 140, "carbs_g": 80, "fat_g": 102}

        plan = _build_constraint_fallback_meal(foods, 1800, macros)

        self.assert_executable_meal_plan(plan, foods, 1800, macros)

    def test_production_low_carb_macros_are_feasible_with_real_candidates(self):
        raw_foods = json.loads(
            (Path(__file__).parent.parent / "data" / "foods" / "foods_zh.json").read_text(
                encoding="utf-8-sig"
            )
        )
        foods = [
            {
                "id": food["id"],
                "name": food["name_zh"],
                "category": food["category"],
                "calories_kcal": food["calories_kcal"],
                "protein_g": food["protein_g"],
                "carbs_g": food["carbs_g"],
                "fat_g": food["fat_g"],
                "diet_tags": food.get("diet_tags", []),
            }
            for food in raw_foods
        ]
        foods = _sort_food_candidates_for_preference(foods, "low_carb")

        self.assertEqual(foods[0]["category"], "fat")
        self.assertTrue(any("low_carb" not in food["diet_tags"] for food in foods))

        for goal_type in ("fat_loss", "muscle_gain"):
            for target_calories in (1400, 1800, 2200, 3000):
                with self.subTest(goal_type=goal_type, target_calories=target_calories):
                    macros = calc_macros(
                        target_calories,
                        70,
                        "medium",
                        goal_type,
                        diet_preference="low_carb",
                    )

                    plan = _build_constraint_fallback_meal(
                        foods, target_calories, macros,
                    )

                    self.assertLessEqual(
                        macros["carbs_g"], round(target_calories * 0.20 / 4),
                    )
                    self.assert_executable_meal_plan(
                        plan, foods, target_calories, macros,
                    )

    def test_local_meal_fallback_fails_when_targets_are_impossible_within_bounds(self):
        foods = [{
            "id": 1,
            "name": "黄瓜",
            "calories_kcal": 16,
            "protein_g": 0.8,
            "carbs_g": 2.9,
            "fat_g": 0.2,
        }]

        with self.assertRaisesRegex(ValueError, "无法在可执行份量边界内"):
            _build_constraint_fallback_meal(
                foods,
                2000,
                {"protein_g": 150, "carbs_g": 250, "fat_g": 45},
            )

    def test_local_workout_fallback_satisfies_user_constraints(self):
        fallback = _build_constraint_fallback_workout(
            [{"id": f"e{i}"} for i in range(1, 6)],
            training_days_per_week=3,
            session_duration_minutes=45,
        )

        self.assertEqual(len(fallback["weekly_plan"]), 3)
        for day in fallback["weekly_plan"]:
            self.assertEqual(len(day["exercises"]), 4)
            self.assertEqual(day["duration_minutes"], 45)

    def test_untrusted_ids_and_values_are_removed_and_database_values_win(self):
        food_candidates = [{
            "id": 1, "name": "鸡胸肉", "calories_kcal": 165,
            "protein_g": 31, "carbs_g": 0, "fat_g": 3.6,
        }]
        exercise_candidates = [{"id": "0025"}]
        raw = {
            "meal_plan": {"meals": [{
                "meal_type": "lunch",
                "items": [
                    {"food_id": 999, "name": "虚构食物", "portion_g": 100, "calories": -500},
                    {"food_id": 1, "name": "被篡改", "portion_g": 200, "calories": 1},
                ],
            }]},
            "workout_plan": {"weekly_plan": [{
                "day": 1,
                "theme": "chest",
                "exercises": [
                    {"exercise_id": "9999", "sets": 100, "reps": "all"},
                    {"exercise_id": "0025", "sets": 3, "reps": "8-12"},
                ],
            }]},
        }

        result = _sanitize_agent_plan_output(
            raw, food_candidates, exercise_candidates, 2000, enforce_target=False
        )

        items = result["meal_plan"]["meals"][0]["items"]
        self.assertEqual([item["food_id"] for item in items], [1])
        self.assertEqual(items[0]["name"], "鸡胸肉")
        self.assertEqual(items[0]["calories"], 330.0)
        exercises = result["workout_plan"]["weekly_plan"][0]["exercises"]
        self.assertEqual([exercise["exercise_id"] for exercise in exercises], ["0025"])

    def test_target_tolerance_and_training_day_are_mandatory(self):
        foods = [{
            "id": 1, "name": "鸡胸肉", "calories_kcal": 400,
            "protein_g": 20, "carbs_g": 0, "fat_g": 2,
        }]
        exercises = [{"id": "0025"}]
        low_calorie = {
            "meal_plan": {"meals": [{
                "meal_type": "lunch",
                "items": [{"food_id": 1, "portion_g": 100}],
            }]},
            "workout_plan": {"weekly_plan": [{"day": 1, "theme": "rest"}]},
        }
        with self.assertRaises(ValueError):
            _sanitize_agent_plan_output(
                low_calorie, foods, exercises, 2000, enforce_target=True
            )

        all_rest = json.loads(json.dumps(low_calorie))
        all_rest["meal_plan"]["meals"][0]["items"][0]["portion_g"] = 500
        with self.assertRaisesRegex(ValueError, "only rest days"):
            _sanitize_agent_plan_output(
                all_rest, foods, exercises, 2000, enforce_target=True
            )

    def test_trusted_macros_must_be_within_tolerance(self):
        foods = [{
            "id": 1, "name": "米饭", "calories_kcal": 200,
            "protein_g": 1, "carbs_g": 24, "fat_g": 0.2,
        }]
        raw = {
            "meal_plan": {"meals": [{
                "meal_type": "lunch",
                "items": [{"food_id": 1, "portion_g": 500}],
            }]},
            "workout_plan": {"weekly_plan": [{
                "day": 1,
                "theme": "full body",
                "duration_minutes": 60,
                "exercises": [{"exercise_id": "manual", "sets": 3, "reps": "8"}],
            }]},
        }

        with self.assertRaisesRegex(ValueError, "protein"):
            _sanitize_agent_plan_output(
                raw,
                foods,
                [],
                1000,
                enforce_target=True,
                target_macros={"protein_g": 100, "carbs_g": 240, "fat_g": 50},
            )

    def test_macro_tolerance_uses_inclusive_fifteen_percent_boundaries(self):
        foods = [{
            "id": 1,
            "name": "边界测试食物",
            "calories_kcal": 100,
            "protein_g": 20,
            "carbs_g": 20,
            "fat_g": 20,
        }]
        workout = {
            "weekly_plan": [{
                "day": 1,
                "theme": "full body",
                "duration_minutes": 60,
                "exercises": [{"exercise_id": "manual", "sets": 3, "reps": "8"}],
            }],
        }
        for ratio, accepted in ((0.84, False), (0.85, True), (1.15, True), (1.16, False)):
            with self.subTest(ratio=ratio):
                plan = {
                    "meal_plan": {"meals": [{
                        "meal_type": "lunch",
                        "items": [{"food_id": 1, "portion_g": ratio * 500}],
                    }]},
                    "workout_plan": workout,
                }
                if accepted:
                    _sanitize_agent_plan_output(
                        plan,
                        foods,
                        [],
                        0,
                        enforce_target=True,
                        target_macros={"protein_g": 100, "carbs_g": 100, "fat_g": 100},
                    )
                else:
                    with self.assertRaisesRegex(ValueError, "protein"):
                        _sanitize_agent_plan_output(
                            plan,
                            foods,
                            [],
                            0,
                            enforce_target=True,
                            target_macros={"protein_g": 100, "carbs_g": 100, "fat_g": 100},
                        )

    def test_training_constraints_reject_wrong_day_count_exercise_count_and_duration(self):
        foods = [{
            "id": 1, "name": "测试餐", "calories_kcal": 100,
            "protein_g": 10, "carbs_g": 10, "fat_g": 2,
        }]
        exercises = [{"id": f"e{i}"} for i in range(1, 5)]
        meal_plan = {"meals": [{
            "meal_type": "lunch",
            "items": [{"food_id": 1, "portion_g": 100}],
        }]}
        constraints = {"training_days_per_week": 2, "session_duration_minutes": 60}
        valid_exercises = [
            {"exercise_id": f"e{i}", "sets": 3, "reps": "8"}
            for i in range(1, 5)
        ]
        cases = (
            ([{"day": 1, "theme": "full body", "duration_minutes": 60,
               "exercises": valid_exercises}], "training days"),
            ([{"day": day, "theme": "full body", "duration_minutes": 60,
               "exercises": valid_exercises[:3]} for day in (1, 2)], "exercises"),
            ([{"day": day, "theme": "full body", "duration_minutes": 120,
               "exercises": valid_exercises} for day in (1, 2)], "duration"),
        )

        for weekly_plan, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                with self.assertRaisesRegex(ValueError, expected_error):
                    _sanitize_agent_plan_output(
                        {"meal_plan": meal_plan, "workout_plan": {"weekly_plan": weekly_plan}},
                        foods,
                        exercises,
                        100,
                        enforce_target=False,
                        training_constraints=constraints,
                    )

    def test_injury_coarse_filter_blocks_named_unsafe_exercises(self):
        squat = SimpleNamespace(
            name="barbell squat", name_zh="杠铃深蹲", body_part="upper legs", target="quads"
        )
        row = SimpleNamespace(
            name="cable row", name_zh="坐姿划船", body_part="back", target="lats"
        )
        self.assertTrue(_exercise_conflicts_with_injuries(squat, ["膝盖疼痛"]))
        self.assertFalse(_exercise_conflicts_with_injuries(row, ["膝盖疼痛"]))

    def test_injury_coarse_filter_accepts_profile_schema_english_tags(self):
        squat = SimpleNamespace(
            name="barbell squat", name_zh="杠铃深蹲", body_part="upper legs", target="quads"
        )
        deadlift = SimpleNamespace(
            name="barbell deadlift", name_zh="杠铃硬拉", body_part="back", target="glutes"
        )
        self.assertTrue(_exercise_conflicts_with_injuries(squat, ["knee_pain"]))
        self.assertTrue(_exercise_conflicts_with_injuries(deadlift, ["back_pain"]))


class FrontendWorkoutAdjustmentContractTests(unittest.TestCase):
    def test_frontend_passes_original_json_and_locks_before_first_await(self):
        frontend_root = Path(__file__).parents[2] / "frontend" / "src"
        api_source = (frontend_root / "api" / "index.ts").read_text(encoding="utf-8")
        type_source = (frontend_root / "types" / "index.ts").read_text(encoding="utf-8")
        view_source = (frontend_root / "views" / "HistoryView.vue").read_text(encoding="utf-8")
        function_source = view_source.split("async function applyWorkoutAdjust()", 1)[1].split(
            "function dismissWorkoutAdjust()", 1
        )[0]

        self.assertIn("base_workout_plan_json: string", type_source)
        self.assertIn("base_workout_plan_json: baseWorkoutPlanJson", api_source)
        self.assertNotIn("planRes.workout_plan_json", function_source)
        self.assertIn("review.value?.source_workout_plan_json", function_source)
        self.assertIn("review.value?.source_checkin_id", function_source)
        self.assertIn("baseWorkoutPlanJson", function_source)
        self.assertIn("if (applyingWorkoutAdjust.value) return", function_source)
        self.assertLess(
            function_source.index("applyingWorkoutAdjust.value = true"),
            function_source.index("await "),
        )


class WorkoutAdjustmentTriggerTests(unittest.TestCase):
    def test_profile_schema_english_injury_tags_trigger_replacements(self):
        for injury in ("knee_pain", "back_pain"):
            with self.subTest(injury=injury):
                result = review_workout_adjustment({
                    "user_profile": {"injuries": [injury], "goal_type": "fat_loss"},
                    "checkin_history": [],
                })
                changes = result["workout_adjustment"]["changes"]
                self.assertTrue(any(change["action"] == "replace" for change in changes))

    def test_normal_rest_days_and_short_weight_window_do_not_trigger(self):
        history = [
            "日期: 2026-08-01 | 体重: 75kg | 运动: 计划休息日",
            "日期: 2026-08-03 | 体重: 75kg | 运动: 主动恢复",
            "日期: 2026-08-05 | 体重: 75kg | 运动: 休息",
            "日期: 2026-08-07 | 体重: 75kg | 运动: 拉伸",
        ]
        result = review_workout_adjustment({
            "user_profile": {"injuries": [], "goal_type": "fat_loss"},
            "checkin_history": history,
        })
        self.assertIsNone(result["workout_adjustment"])

    def test_checkin_pain_context_triggers_injury_but_exercise_name_alone_does_not(self):
        painful = review_workout_adjustment({
            "user_profile": {"injuries": [], "goal_type": "fat_loss"},
            "checkin_history": ["日期: 2026-08-11 | 运动: 拉伸 | 备注: 今天深蹲后膝盖疼痛"],
        })
        normal = review_workout_adjustment({
            "user_profile": {"injuries": [], "goal_type": "fat_loss"},
            "checkin_history": ["日期: 2026-08-11 | 运动: 膝盖主导深蹲、肩推训练完成 | 备注: 状态良好"],
        })

        self.assertTrue(any(
            change["action"] == "replace"
            for change in painful["workout_adjustment"]["changes"]
        ))
        self.assertIsNone(normal["workout_adjustment"])

    def test_fourteen_day_plateau_can_trigger_cardio_adjustment(self):
        history = [
            "日期: 2026-08-01 | 体重: 75kg | 运动: 完成",
            "日期: 2026-08-06 | 体重: 75.1kg | 运动: 完成",
            "日期: 2026-08-11 | 体重: 75kg | 运动: 完成",
            "日期: 2026-08-15 | 体重: 75kg | 运动: 完成",
        ]
        result = review_workout_adjustment({
            "user_profile": {"injuries": [], "goal_type": "fat_loss"},
            "checkin_history": history,
        })
        changes = result["workout_adjustment"]["changes"]
        self.assertTrue(any(change["action"] == "increase_cardio" for change in changes))


class CheckinReviewWindowTests(ApiDatabaseTestCase):
    database_name = "checkin-review-window.db"

    async def prepare_database(self):
        await super().prepare_database()
        async with self.session_factory() as session:
            session.add(User(
                id=1, gender="male", age=30, height=175, weight=75,
                target_weight=70, goal_type="fat_loss",
            ))
            start = datetime(2026, 7, 1)
            for index in range(15):
                day = start + timedelta(days=index)
                session.add(Checkin(
                    user_id=1,
                    date=day.date().isoformat(),
                    weight=75,
                    exercises="完成训练",
                ))
            await session.commit()

    def test_service_window_makes_fourteen_day_plateau_reachable(self):
        async def review_side_effect(user_profile, checkin_history):
            adjustment = review_workout_adjustment({
                "user_profile": user_profile,
                "checkin_history": checkin_history,
            })
            return {
                "review_summary": "测试复盘",
                "next_day_advice": "测试建议",
                **adjustment,
            }

        with patch(
            "app.services.checkin_service.run_review_workflow",
            new=AsyncMock(side_effect=review_side_effect),
        ):
            response = self.client.get("/api/checkin/review/1")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["checkin_count"], 15)
        self.assertTrue(any(
            change["action"] == "increase_cardio"
            for change in data["workout_adjustment"]["changes"]
        ))


if __name__ == "__main__":
    unittest.main()
