import tempfile
import unittest
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.graph.chat_workflow import assess_risk
from app.main import app
from app.models.user import ChatMessage, User
from app.services import chat_service
from app.agent.chat_tool_agent import ToolAgentReport, ToolTrace


class ChatWorkflowTests(unittest.TestCase):
    def test_high_risk_message_is_flagged(self):
        state = {"user_message": "我每天500大卡能不能更快减脂"}
        result = assess_risk(state)
        self.assertEqual(result["risk_level"], "high")
        self.assertIn("不能替代", result["risk_notice"])

    def test_normal_message_is_not_flagged(self):
        result = assess_risk({"user_message": "减脂期蛋白质怎么安排"})
        self.assertEqual(result["risk_level"], "normal")
        self.assertEqual(result["risk_notice"], "")


class ChatApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "chat-test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        self.session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

        async def override_db():
            async with self.session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = override_db

        async def prepare():
            async with self.engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with self.session_factory() as session:
                session.add_all([
                    User(
                        id=1, gender="male", age=30, height=175, weight=75,
                        target_weight=70,
                    ),
                    User(
                        id=2, gender="female", age=28, height=165, weight=60,
                        target_weight=55,
                    ),
                ])
                await session.commit()

        import asyncio
        asyncio.run(prepare())
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        import asyncio
        asyncio.run(self.engine.dispose())
        self.temp_dir.cleanup()

    def test_create_list_detail_and_archive(self):
        created = self.client.post(
            "/api/chat/conversations",
            json={"user_id": 1, "title": "训练问题"},
        )
        self.assertEqual(created.status_code, 200)
        conversation_id = created.json()["id"]

        listing = self.client.get("/api/chat/conversations?user_id=1")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.json()), 1)

        detail = self.client.get(
            f"/api/chat/conversations/{conversation_id}?user_id=1"
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["messages"], [])

        archived = self.client.delete(
            f"/api/chat/conversations/{conversation_id}?user_id=1"
        )
        self.assertEqual(archived.status_code, 200)
        self.assertEqual(
            self.client.get("/api/chat/conversations?user_id=1").json(), []
        )

    def test_cross_user_access_is_hidden(self):
        created = self.client.post(
            "/api/chat/conversations",
            json={"user_id": 1},
        ).json()
        conversation_id = created["id"]

        detail = self.client.get(
            f"/api/chat/conversations/{conversation_id}?user_id=2"
        )
        self.assertEqual(detail.status_code, 404)

        stream = self.client.post(
            f"/api/chat/conversations/{conversation_id}/messages/stream",
            json={"user_id": 2, "content": "读取其他用户会话"},
        )
        self.assertEqual(stream.status_code, 404)

    def test_stream_rejects_oversized_page_context(self):
        created = self.client.post(
            "/api/chat/conversations",
            json={"user_id": 1},
        ).json()

        response = self.client.post(
            f"/api/chat/conversations/{created['id']}/messages/stream",
            json={
                "user_id": 1,
                "content": "解释当前页面",
                "page_context": {"payload": "x" * 10001},
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_stream_completion_runs_summary_background_check(self):
        created = self.client.post(
            "/api/chat/conversations",
            json={"user_id": 1},
        ).json()
        conversation_id = created["id"]
        compacted = []

        async def fake_stream_chat_message(**_kwargs):
            yield {
                "event": "done",
                "data": {"id": 1},
                "internal": {"source_message_id": 77},
            }

        async def fake_compact(target_conversation_id):
            compacted.append(target_conversation_id)

        extracted = []

        async def fake_extract(target_conversation_id, source_message_id):
            extracted.append((target_conversation_id, source_message_id))
            return 0

        with patch(
            "app.api.chat.stream_chat_message",
            new=fake_stream_chat_message,
        ), patch(
            "app.api.chat.compact_conversation_if_needed",
            new=fake_compact,
        ), patch(
            "app.api.chat.extract_and_persist_user_memory",
            new=fake_extract,
        ):
            response = self.client.post(
                f"/api/chat/conversations/{conversation_id}/messages/stream",
                json={"user_id": 1, "content": "测试后台摘要"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: done", response.text)
        self.assertEqual(compacted, [conversation_id])
        self.assertEqual(extracted, [(conversation_id, 77)])


class _FakeStreamingLlm:
    def __init__(self, chunks=None, error: Exception | None = None):
        self.chunks = chunks or []
        self.error = error
        self.messages = []

    async def astream(self, messages):
        self.messages = list(messages)
        if self.error:
            raise self.error
        for chunk in self.chunks:
            yield SimpleNamespace(content=chunk)


class _BoundToolPlanner:
    def __init__(self, response):
        self.response = response

    async def ainvoke(self, _messages):
        return self.response


class _ToolPlanner:
    def __init__(self, response):
        self.response = response

    def bind_tools(self, _tools, **_kwargs):
        return _BoundToolPlanner(self.response)


class ChatStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "chat-stream-test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        self.session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False
        )
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with self.session_factory() as session:
            session.add(User(
                id=1, gender="male", age=30, height=175, weight=75,
                target_weight=70,
            ))
            await session.commit()
            self.conversation = await chat_service.create_conversation(session, 1)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temp_dir.cleanup()

    @staticmethod
    def _graph_result():
        return {
            "user_message": "蛋白质怎么吃",
            "current_page": "chat",
            "profile": {},
            "latest_plan": None,
            "page_context": {},
            "risk_level": "normal",
            "risk_notice": "",
            "retrieved_knowledge": [{
                "chunk_id": "chunk-1",
                "title": "蛋白质建议",
                "content": "按体重安排蛋白质。",
                "category": "fat_loss_standards",
                "source_name": "测试来源",
                "source_url": "",
                "evidence_level": "guideline",
                "score": 0.9,
            }],
            "citations": [{
                "chunk_id": "chunk-1",
                "title": "蛋白质建议",
                "category": "fat_loss_standards",
                "source_name": "测试来源",
                "source_url": "",
                "evidence_level": "guideline",
                "score": 0.9,
            }],
        }

    async def test_completed_stream_persists_answer_and_citations(self):
        async with self.session_factory() as session:
            with patch.object(
                chat_service,
                "run_chat_tool_agent",
                new=AsyncMock(return_value=ToolAgentReport(
                    degraded=True,
                    degradation_reason="PLANNER_ERROR",
                )),
            ), patch.object(
                chat_service._CHAT_GRAPH,
                "ainvoke",
                new=AsyncMock(return_value=self._graph_result()),
            ), patch.object(
                chat_service,
                "_chat_llm",
                return_value=_FakeStreamingLlm(["你好", "世界"]),
            ):
                events = [
                    event async for event in chat_service.stream_chat_message(
                        session, self.conversation.id, 1, "蛋白质怎么吃"
                    )
                ]

            self.assertEqual(
                [event["event"] for event in events],
                ["meta", "delta", "delta", "citations", "done"],
            )
            statement = (
                select(ChatMessage)
                .where(ChatMessage.role == "assistant")
                .order_by(desc(ChatMessage.id))
                .limit(1)
            )
            message = (await session.execute(statement)).scalar_one()
            self.assertEqual(message.content, "你好世界")
            self.assertEqual(message.status, "completed")
            self.assertIn("chunk-1", message.citations_json)
            meta = events[0]["data"]
            self.assertIn("context_budget", meta)
            self.assertTrue(meta["context_budget"]["within_budget"])
            self.assertEqual(meta["context_budget"]["knowledge_included"], 1)
            self.assertEqual(meta["context_budget"]["artifact_full"], 1)
            self.assertEqual(
                meta["context_budget"]["artifacts"][0]["reference_id"],
                "chunk-1",
            )

    async def test_tool_trace_is_streamed_and_persisted_with_sources(self):
        report = ToolAgentReport(
            traces=[ToolTrace(
                call_id="call-plan",
                tool_name="get_latest_plan",
                label="当前计划",
                status="completed",
                summary="已读取当前计划",
                source_count=1,
                sources=[{
                    "source_type": "plan",
                    "source_id": "11",
                    "title": "当前计划 #11",
                    "url": "",
                }],
            )],
            artifacts=[{
                "kind": "tool",
                "title": "当前计划",
                "content": '{"daily_calorie_target":1900}',
                "reference_id": "tool:call-plan",
                "score": 1.0,
            }],
            selected_count=1,
        )
        fake_llm = _FakeStreamingLlm(["目标是 1900 千卡"])
        async with self.session_factory() as session:
            with patch.object(
                chat_service,
                "run_chat_tool_agent",
                new=AsyncMock(return_value=report),
            ), patch.object(
                chat_service,
                "_chat_llm",
                return_value=fake_llm,
            ):
                events = [
                    event async for event in chat_service.stream_chat_message(
                        session, self.conversation.id, 1, "我的热量目标是多少"
                    )
                ]

            self.assertEqual(
                [event["event"] for event in events],
                ["meta", "tool", "delta", "citations", "done"],
            )
            tool_event = events[1]["data"]
            self.assertEqual(tool_event["tool_name"], "get_latest_plan")
            self.assertTrue(tool_event["included_in_answer"])
            statement = (
                select(ChatMessage)
                .where(ChatMessage.role == "assistant")
                .order_by(desc(ChatMessage.id))
                .limit(1)
            )
            message = (await session.execute(statement)).scalar_one()
            context = json.loads(message.context_json)
            self.assertEqual(context["tool_calls"][0]["call_id"], "call-plan")
            serialized_context = "\n".join(
                str(item.content) for item in fake_llm.messages
            )
            self.assertIn('"daily_calorie_target":1900', serialized_context)
            self.assertNotIn("权威用户档案", serialized_context)
            self.assertNotIn("当前有效计划", serialized_context)

    async def test_model_failure_persists_failed_status(self):
        async with self.session_factory() as session:
            with patch.object(
                chat_service,
                "run_chat_tool_agent",
                new=AsyncMock(return_value=ToolAgentReport(
                    degraded=True,
                    degradation_reason="PLANNER_ERROR",
                )),
            ), patch.object(
                chat_service._CHAT_GRAPH,
                "ainvoke",
                new=AsyncMock(return_value=self._graph_result()),
            ), patch.object(
                chat_service,
                "_chat_llm",
                return_value=_FakeStreamingLlm(error=RuntimeError("model down")),
            ):
                events = [
                    event async for event in chat_service.stream_chat_message(
                        session, self.conversation.id, 1, "测试失败"
                    )
                ]

            self.assertEqual(events[-1]["event"], "error")
            statement = (
                select(ChatMessage)
                .where(ChatMessage.role == "assistant")
                .order_by(desc(ChatMessage.id))
                .limit(1)
            )
            message = (await session.execute(statement)).scalar_one()
            self.assertEqual(message.status, "failed")
            self.assertNotIn("model down", events[-1]["data"]["message"])

    async def test_cancelled_stream_persists_stopped_status(self):
        async with self.session_factory() as session:
            with patch.object(
                chat_service,
                "run_chat_tool_agent",
                new=AsyncMock(return_value=ToolAgentReport(
                    degraded=True,
                    degradation_reason="PLANNER_ERROR",
                )),
            ), patch.object(
                chat_service._CHAT_GRAPH,
                "ainvoke",
                new=AsyncMock(return_value=self._graph_result()),
            ), patch.object(
                chat_service,
                "_chat_llm",
                return_value=_FakeStreamingLlm(error=asyncio.CancelledError()),
            ):
                with self.assertRaises(asyncio.CancelledError):
                    async for _event in chat_service.stream_chat_message(
                        session, self.conversation.id, 1, "停止生成"
                    ):
                        pass

            statement = (
                select(ChatMessage)
                .where(ChatMessage.role == "assistant")
                .order_by(desc(ChatMessage.id))
                .limit(1)
            )
            message = (await session.execute(statement)).scalar_one()
            self.assertEqual(message.status, "stopped")

    async def test_tool_cancellation_after_rollback_persists_stopped_status(self):
        async def cancel_after_session_rollback(**kwargs):
            await kwargs["context"].db.rollback()
            raise asyncio.CancelledError()

        async with self.session_factory() as session:
            with patch.object(
                chat_service,
                "run_chat_tool_agent",
                new=cancel_after_session_rollback,
            ):
                with self.assertRaises(asyncio.CancelledError):
                    async for _event in chat_service.stream_chat_message(
                        session,
                        self.conversation.id,
                        1,
                        "在工具查询时停止",
                    ):
                        pass

            statement = (
                select(ChatMessage)
                .where(ChatMessage.role == "assistant")
                .order_by(desc(ChatMessage.id))
                .limit(1)
            )
            message = (await session.execute(statement)).scalar_one()
            self.assertEqual(message.status, "stopped")

    async def test_tool_timeout_isolated_session_allows_answer_to_complete(self):
        class NoArgs(BaseModel):
            pass

        async def slow_tool():
            await asyncio.sleep(1)

        tool = StructuredTool.from_function(
            coroutine=slow_tool,
            name="get_user_profile",
            description="slow isolated database tool",
            args_schema=NoArgs,
        )
        planner = _ToolPlanner(AIMessage(
            content="",
            tool_calls=[{
                "name": "get_user_profile",
                "args": {},
                "id": "provider-id",
                "type": "tool_call",
            }],
        ))
        agent_settings = SimpleNamespace(
            CHAT_TOOL_MAX_CALLS=4,
            CHAT_TOOL_TIMEOUT_SECONDS=0.1,
            CHAT_TOOL_RESULT_MAX_CHARS=6000,
        )

        async with self.session_factory() as session:
            with patch(
                "app.agent.chat_tool_agent.build_chat_read_tools",
                return_value={"get_user_profile": tool},
            ), patch(
                "app.agent.chat_tool_agent.get_settings",
                return_value=agent_settings,
            ), patch.object(
                chat_service,
                "_chat_planner_llm",
                return_value=planner,
            ), patch.object(
                chat_service,
                "_chat_llm",
                return_value=_FakeStreamingLlm(["仍可完成回答"]),
            ):
                events = [
                    event async for event in chat_service.stream_chat_message(
                        session,
                        self.conversation.id,
                        1,
                        "读取超时后继续",
                    )
                ]

            self.assertEqual(
                [event["event"] for event in events],
                ["meta", "tool", "delta", "citations", "done"],
            )
            self.assertEqual(events[1]["data"]["error_code"], "TOOL_TIMEOUT")
            statement = (
                select(ChatMessage)
                .where(ChatMessage.role == "assistant")
                .order_by(desc(ChatMessage.id))
                .limit(1)
            )
            message = (await session.execute(statement)).scalar_one()
            self.assertEqual(message.status, "completed")
            self.assertEqual(message.content, "仍可完成回答")
