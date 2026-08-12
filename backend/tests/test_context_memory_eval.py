import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.evals.context_memory import (
    CURRENT_HISTORY_QUERY_LIMIT,
    build_current_baseline_context,
    load_cases,
    run_baseline,
)
from app.models.user import ChatConversation, ChatMessage, User
from app.services.chat_service import _load_agent_context
from app.services.token_estimator import estimate_tokens


class ContextMemoryFixtureTests(unittest.TestCase):
    def test_fixture_ids_are_unique_and_expected_baseline_is_reproducible(self):
        cases = load_cases()
        ids = [case["id"] for case in cases]
        self.assertEqual(len(ids), len(set(ids)))

        report = run_baseline()
        self.assertEqual(report["metrics"]["total_cases"], 6)
        self.assertEqual(report["metrics"]["facts_visible"], 3)
        self.assertEqual(report["metrics"]["context_availability_rate"], 50.0)
        self.assertEqual(report["metrics"]["safety_cases"], 2)
        self.assertEqual(report["metrics"]["safety_facts_visible"], 1)
        self.assertEqual(
            report["metrics"]["fixture_expectations_matched"],
            report["metrics"]["total_cases"],
        )

    def test_current_policy_has_only_nine_prior_message_slots(self):
        case = next(
            item for item in load_cases() if item["id"] == "early_goal_truncated"
        )
        context = build_current_baseline_context(case)
        self.assertEqual(
            len(context["visible_history"]),
            CURRENT_HISTORY_QUERY_LIMIT - 1,
        )
        self.assertNotIn("十二周减重六公斤", context["searchable_text"])

    def test_authoritative_profile_is_visible_even_when_history_is_long(self):
        case = next(
            item
            for item in load_cases()
            if item["id"] == "profile_allergy_authoritative"
        )
        context = build_current_baseline_context(case)
        self.assertIn("花生严重过敏", context["searchable_text"])

    def test_cross_session_message_is_not_visible(self):
        case = next(
            item
            for item in load_cases()
            if item["id"] == "cross_session_preference_unavailable"
        )
        context = build_current_baseline_context(case)
        self.assertNotIn("不吃香菜", context["searchable_text"])

    def test_token_estimate_is_stable_and_nonzero(self):
        self.assertEqual(estimate_tokens("减脂 ABCD"), 3)
        self.assertGreater(estimate_tokens("用户档案：花生严重过敏"), 0)

    def test_unknown_fixture_schema_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir) / "invalid.json"
            fixture.write_text(
                json.dumps({"schema_version": 2, "cases": [{}]}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "schema_version"):
                load_cases(fixture)


class CurrentChatContextLoaderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "context-loader.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
        )
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_loader_returns_available_rows_in_ascending_order_for_builder(self):
        async with self.session_factory() as session:
            session.add(
                User(
                    id=1,
                    gender="male",
                    age=30,
                    height=175,
                    weight=75,
                    target_weight=70,
                )
            )
            conversation = ChatConversation(user_id=1, title="baseline")
            session.add(conversation)
            await session.flush()
            session.add_all(
                [
                    ChatMessage(
                        conversation_id=conversation.id,
                        role="user" if index % 2 else "assistant",
                        content=f"message-{index:02d}",
                    )
                    for index in range(1, 13)
                ]
            )
            await session.commit()

            _, _, history = await _load_agent_context(
                session,
                conversation,
                "chat",
                {},
            )

        self.assertEqual(len(history), 12)
        self.assertEqual(history[0].content, "message-01")
        self.assertEqual(history[-1].content, "message-12")
