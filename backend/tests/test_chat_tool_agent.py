import asyncio
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agent.chat_tool_agent import _bounded_envelope, run_chat_tool_agent
from app.agent.read_tools import ChatReadToolContext, _source, build_chat_read_tools
from app.core.config import Settings
from app.core.database import Base
from app.models.user import Checkin, MealLog, Plan, User
from app.schemas.chat import ChatMessageCreate


class _BoundPlanner:
    def __init__(
        self,
        response=None,
        error: Exception | None = None,
        delay: float = 0,
    ):
        self.response = response
        self.error = error
        self.delay = delay

    async def ainvoke(self, _messages):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.response


class _Planner:
    def __init__(
        self,
        response=None,
        error: Exception | None = None,
        delay: float = 0,
    ):
        self.response = response
        self.error = error
        self.delay = delay
        self.bound_tools = []

    def bind_tools(self, tools, **_kwargs):
        self.bound_tools = list(tools)
        return _BoundPlanner(self.response, self.error, self.delay)


class ChatToolAgentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "chat-tools.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
        )
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with self.session_factory() as db:
            db.add_all([
                User(
                    id=1,
                    gender="male",
                    age=30,
                    height=175,
                    weight=75,
                    target_weight=70,
                    injuries='["膝盖疼痛"]',
                ),
                User(
                    id=2,
                    gender="female",
                    age=28,
                    height=165,
                    weight=60,
                    target_weight=55,
                ),
                Plan(
                    id=11,
                    user_id=1,
                    daily_calorie_target=1900,
                    calorie_info_json='{"tdee":2400}',
                    macros_json='{"protein_g":140}',
                    meal_plan="user-one-meals",
                    workout_plan="user-one-workout",
                    summary="user-one-summary",
                    created_at=datetime(2026, 8, 12),
                ),
                Plan(
                    id=22,
                    user_id=2,
                    daily_calorie_target=1500,
                    meal_plan="private-user-two-meals",
                    workout_plan="private-user-two-workout",
                    created_at=datetime(2026, 8, 13),
                ),
                Checkin(
                    user_id=1,
                    date="2026-08-13",
                    foods="鸡胸肉",
                    exercises="深蹲",
                    weight=74.5,
                    note="状态正常",
                ),
                MealLog(
                    user_id=1,
                    date="2026-08-13",
                    meal_type="lunch",
                    items_json='[{"name":"鸡胸肉"}]',
                    meal_total_json=(
                        '{"calories_kcal":520,"protein_g":45,'
                        '"carbs_g":50,"fat_g":14}'
                    ),
                ),
            ])
            await db.commit()

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temp_dir.cleanup()

    def _context(self, db):
        return ChatReadToolContext(
            db=db,
            user_id=1,
            conversation_id=9,
            source_message_id=12,
        )

    async def test_tool_schemas_never_expose_identity_or_sql(self):
        async with self.session_factory() as db:
            tools = build_chat_read_tools(self._context(db))

        self.assertEqual(len(tools), 8)
        for tool in tools.values():
            schema = json.dumps(tool.args_schema.model_json_schema()).lower()
            self.assertNotIn("user_id", schema)
            self.assertNotIn("sql", schema)

    async def test_personal_tools_are_server_scoped_to_current_user(self):
        async with self.session_factory() as db:
            tools = build_chat_read_tools(self._context(db))
            profile = await tools["get_user_profile"].ainvoke({})
            plan = await tools["get_latest_plan"].ainvoke({"section": "all"})
            checkins = await tools["get_recent_checkins"].ainvoke({"limit": 7})
            meals = await tools["get_meal_summary"].ainvoke(
                {"date": "2026-08-13"}
            )

        serialized = json.dumps(
            [profile, plan, checkins, meals],
            ensure_ascii=False,
        )
        self.assertIn("user-one-summary", serialized)
        self.assertIn("膝盖疼痛", serialized)
        self.assertIn("520", serialized)
        self.assertNotIn("private-user-two", serialized)

    async def test_selected_tool_is_executed_and_traceable(self):
        response = AIMessage(
            content="",
            tool_calls=[{
                "name": "get_latest_plan",
                "args": {"section": "nutrition"},
                "id": "call-plan",
                "type": "tool_call",
            }],
        )
        planner = _Planner(response=response)
        async with self.session_factory() as db:
            report = await run_chat_tool_agent(
                context=self._context(db),
                user_message="我的热量目标是多少",
                current_page="chat",
                planner=planner,
                max_calls=4,
                timeout_seconds=2,
            )

        self.assertFalse(report.degraded)
        self.assertEqual(report.selected_count, 1)
        self.assertEqual(report.traces[0].tool_name, "get_latest_plan")
        self.assertEqual(report.traces[0].status, "completed")
        self.assertEqual(report.artifacts[0]["reference_id"], "tool:call-1")
        self.assertIn("1900", report.artifacts[0]["content"])

    async def test_call_budget_and_unknown_tool_are_enforced(self):
        names = [
            "unknown_database_tool",
            "get_user_profile",
            "get_latest_plan",
            "get_recent_checkins",
            "get_meal_summary",
            "search_foods",
            "search_exercises",
            "search_knowledge",
        ]
        calls = [
            {
                "name": names[index],
                "args": {"section": "summary"} if index == 2 else {},
                "id": f"call-{index}",
                "type": "tool_call",
            }
            for index in range(8)
        ]
        async with self.session_factory() as db:
            report = await run_chat_tool_agent(
                context=self._context(db),
                user_message="把所有数据都查出来",
                current_page="chat",
                planner=_Planner(response=AIMessage(content="", tool_calls=calls)),
                max_calls=3,
                timeout_seconds=2,
            )

        self.assertEqual(report.selected_count, 3)
        self.assertEqual(len(report.traces), 3)
        self.assertEqual(report.traces[0].status, "failed")
        self.assertEqual(report.traces[0].error_code, "TOOL_NOT_ALLOWED")
        self.assertNotIn("database", report.traces[0].summary.lower())

    async def test_planner_failure_returns_safe_legacy_degradation(self):
        async with self.session_factory() as db:
            report = await run_chat_tool_agent(
                context=self._context(db),
                user_message="测试",
                current_page="chat",
                planner=_Planner(error=RuntimeError("secret planner stack")),
                max_calls=4,
                timeout_seconds=2,
            )

        self.assertTrue(report.degraded)
        self.assertEqual(report.degradation_reason, "PLANNER_ERROR")
        self.assertNotIn("secret planner stack", json.dumps(report.to_dict()))

    def test_page_context_rejects_oversized_or_deep_browser_data(self):
        with self.assertRaises(ValueError):
            ChatMessageCreate(
                user_id=1,
                content="测试",
                page_context={"payload": "x" * 10001},
            )
        with self.assertRaises(ValueError):
            ChatMessageCreate(
                user_id=1,
                content="测试",
                page_context={
                    "a": {"b": {"c": {"d": {"e": {"f": {"g": 1}}}}}}
                },
            )

    def test_chat_message_rejects_whitespace_only_content(self):
        with self.assertRaises(ValidationError):
            ChatMessageCreate(user_id=1, content="   \n\t")

    def test_tool_source_urls_only_allow_http_protocols(self):
        self.assertEqual(
            _source("knowledge", 1, "可信", "https://example.com/a")["url"],
            "https://example.com/a",
        )
        self.assertEqual(
            _source("knowledge", 2, "异常", "javascript:alert(1)")["url"],
            "",
        )

    def test_tool_envelope_bounds_untrusted_metadata(self):
        envelope = _bounded_envelope(
            {
                "content": {"value": "x" * 2000},
                "sources": [{
                    "source_type": "knowledge" * 20,
                    "source_id": "1" * 500,
                    "title": "标题" * 500,
                    "url": "javascript:alert(1)",
                }],
                "citations": [{
                    "chunk_id": "c" * 500,
                    "title": "资料" * 500,
                    "source_url": "data:text/html,unsafe",
                }],
            },
            500,
        )
        self.assertTrue(envelope["content"]["truncated"])
        self.assertLessEqual(len(envelope["sources"][0]["title"]), 160)
        self.assertEqual(envelope["sources"][0]["url"], "")
        self.assertEqual(envelope["citations"][0]["source_url"], "")

    def test_tool_runtime_settings_reject_unsafe_bounds(self):
        invalid_settings = (
            {"CHAT_TOOL_MAX_CALLS": 0},
            {"CHAT_TOOL_TIMEOUT_SECONDS": 0},
            {"CHAT_TOOL_RESULT_MAX_CHARS": 499},
        )
        for overrides in invalid_settings:
            with self.subTest(overrides=overrides), self.assertRaises(
                ValidationError
            ):
                Settings(**overrides)

    async def test_planner_timeout_degrades_without_exposing_details(self):
        async with self.session_factory() as db:
            report = await run_chat_tool_agent(
                context=self._context(db),
                user_message="测试慢路由",
                current_page="chat",
                planner=_Planner(delay=0.2),
                timeout_seconds=0.1,
            )

        self.assertTrue(report.degraded)
        self.assertEqual(report.degradation_reason, "PLANNER_ERROR")

    async def test_tool_timeout_rolls_back_shared_session(self):
        class NoArgs(BaseModel):
            pass

        async def slow_tool():
            await asyncio.sleep(1)

        fake_db = SimpleNamespace(rollback=AsyncMock())
        tool = StructuredTool.from_function(
            coroutine=slow_tool,
            name="get_user_profile",
            description="slow test tool",
            args_schema=NoArgs,
        )
        response = AIMessage(
            content="",
            tool_calls=[{
                "name": "get_user_profile",
                "args": {},
                "id": "slow-call",
                "type": "tool_call",
            }],
        )
        with patch(
            "app.agent.chat_tool_agent.build_chat_read_tools",
            return_value={"get_user_profile": tool},
        ):
            report = await run_chat_tool_agent(
                context=SimpleNamespace(db=fake_db),
                user_message="读取档案",
                current_page="chat",
                planner=_Planner(response=response),
                timeout_seconds=0.1,
            )

        self.assertEqual(report.traces[0].error_code, "TOOL_TIMEOUT")
        self.assertTrue(report.degraded)
        self.assertEqual(report.degradation_reason, "TOOL_EXECUTION_FAILED")
        fake_db.rollback.assert_awaited_once()

    async def test_client_cancellation_during_tool_rolls_back_session(self):
        class NoArgs(BaseModel):
            pass

        started = asyncio.Event()

        async def waiting_tool():
            started.set()
            await asyncio.Event().wait()

        fake_db = SimpleNamespace(rollback=AsyncMock())
        tool = StructuredTool.from_function(
            coroutine=waiting_tool,
            name="get_user_profile",
            description="cancellable test tool",
            args_schema=NoArgs,
        )
        response = AIMessage(
            content="",
            tool_calls=[{
                "name": "get_user_profile",
                "args": {},
                "id": "cancel-call",
                "type": "tool_call",
            }],
        )
        with patch(
            "app.agent.chat_tool_agent.build_chat_read_tools",
            return_value={"get_user_profile": tool},
        ):
            task = asyncio.create_task(run_chat_tool_agent(
                context=SimpleNamespace(db=fake_db),
                user_message="读取档案",
                current_page="chat",
                planner=_Planner(response=response),
                timeout_seconds=10,
            ))
            await asyncio.wait_for(started.wait(), timeout=1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        fake_db.rollback.assert_awaited_once()

    async def test_duplicate_model_call_ids_are_replaced_with_unique_ids(self):
        response = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "get_latest_plan",
                    "args": {"section": "nutrition"},
                    "id": "duplicate",
                    "type": "tool_call",
                },
                {
                    "name": "get_recent_checkins",
                    "args": {"limit": 7},
                    "id": "duplicate",
                    "type": "tool_call",
                },
            ],
        )
        async with self.session_factory() as db:
            report = await run_chat_tool_agent(
                context=self._context(db),
                user_message="结合计划和打卡分析",
                current_page="history",
                planner=_Planner(response=response),
                timeout_seconds=2,
            )

        call_ids = [trace.call_id for trace in report.traces]
        references = [artifact["reference_id"] for artifact in report.artifacts]
        self.assertEqual(len(call_ids), 2)
        self.assertEqual(len(set(call_ids)), 2)
        self.assertEqual(len(set(references)), 2)


if __name__ == "__main__":
    unittest.main()
