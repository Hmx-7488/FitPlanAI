import tempfile
import unittest
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import anyio
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


class _PartialThenFailingLlm:
    def __init__(self, error: BaseException):
        self.error = error

    async def astream(self, _messages):
        yield SimpleNamespace(content="已生成部分")
        raise self.error


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

    async def _assert_setup_cancellation_is_paired(self, patches):
        async with self.session_factory() as session:
            with patches:
                with self.assertRaises(asyncio.CancelledError):
                    async for _event in chat_service.stream_chat_message(
                        session, self.conversation.id, 1, "在准备上下文时停止"
                    ):
                        pass

            rows = list(
                (
                    await session.execute(
                        select(ChatMessage)
                        .where(ChatMessage.conversation_id == self.conversation.id)
                        .order_by(ChatMessage.id)
                    )
                ).scalars()
            )
            self.assertEqual([row.role for row in rows], ["user", "assistant"])
            self.assertEqual(rows[0].status, "completed")
            self.assertEqual(rows[1].status, "stopped")
            self.assertEqual(rows[1].content, "已停止生成。")

    async def test_cancelled_history_loading_persists_paired_stopped_message(self):
        async def cancelled(*_args, **_kwargs):
            raise asyncio.CancelledError()

        await self._assert_setup_cancellation_is_paired(
            patch.object(chat_service, "_load_chat_history", new=cancelled)
        )

    async def test_cancelled_legacy_profile_loading_persists_stopped_message(self):
        async def cancelled(*_args, **_kwargs):
            raise asyncio.CancelledError()

        with patch.object(
            chat_service,
            "run_chat_tool_agent",
            new=AsyncMock(return_value=ToolAgentReport(
                degraded=True,
                degradation_reason="PLANNER_ERROR",
            )),
        ):
            await self._assert_setup_cancellation_is_paired(
                patch.object(
                    chat_service,
                    "_load_legacy_profile_plan",
                    new=cancelled,
                )
            )

    async def test_cancel_after_initial_commit_repairs_pending_assistant(self):
        async with self.session_factory() as session:
            real_commit = session.commit
            commit_calls = 0

            async def commit_then_cancel_once():
                nonlocal commit_calls
                commit_calls += 1
                await real_commit()
                if commit_calls == 1:
                    raise asyncio.CancelledError()

            with patch.object(session, "commit", new=commit_then_cancel_once):
                with self.assertRaises(asyncio.CancelledError):
                    async for _event in chat_service.stream_chat_message(
                        session, self.conversation.id, 1, "提交后立即停止"
                    ):
                        pass

            rows = list(
                (
                    await session.execute(
                        select(ChatMessage)
                        .where(ChatMessage.conversation_id == self.conversation.id)
                        .order_by(ChatMessage.id)
                    )
                ).scalars()
            )
            self.assertEqual([row.role for row in rows], ["user", "assistant"])
            self.assertEqual(rows[1].status, "stopped")
            self.assertEqual(rows[1].content, "已停止生成。")

    async def test_real_cancel_scope_persists_stopped_assistant(self):
        entered = anyio.Event()

        async def block_history(*_args, **_kwargs):
            entered.set()
            await anyio.sleep_forever()

        async with self.session_factory() as session:
            async def consume():
                async for _event in chat_service.stream_chat_message(
                    session,
                    self.conversation.id,
                    1,
                    "真实断连取消",
                ):
                    pass

            with patch.object(
                chat_service,
                "_load_chat_history",
                new=block_history,
            ):
                async with anyio.create_task_group() as task_group:
                    task_group.start_soon(consume)
                    await entered.wait()
                    task_group.cancel_scope.cancel()

        async with self.session_factory() as verify_session:
            rows = list(
                (
                    await verify_session.execute(
                        select(ChatMessage)
                        .where(
                            ChatMessage.conversation_id == self.conversation.id
                        )
                        .order_by(ChatMessage.id)
                    )
                ).scalars()
            )

        self.assertEqual([row.role for row in rows], ["user", "assistant"])
        self.assertEqual(rows[0].status, "completed")
        self.assertEqual(rows[1].status, "stopped")
        self.assertEqual(rows[1].content, "已停止生成。")

    async def test_real_cancel_scope_after_initial_commit_repairs_assistant(self):
        entered = anyio.Event()

        async with self.session_factory() as session:
            real_commit = session.commit
            commit_calls = 0

            async def commit_then_block_once():
                nonlocal commit_calls
                commit_calls += 1
                await real_commit()
                if commit_calls == 1:
                    entered.set()
                    await anyio.sleep_forever()

            async def consume():
                async for _event in chat_service.stream_chat_message(
                    session,
                    self.conversation.id,
                    1,
                    "提交落库后真实断连",
                ):
                    pass

            with patch.object(session, "commit", new=commit_then_block_once):
                async with anyio.create_task_group() as task_group:
                    task_group.start_soon(consume)
                    await entered.wait()
                    task_group.cancel_scope.cancel()

        async with self.session_factory() as verify_session:
            rows = list(
                (
                    await verify_session.execute(
                        select(ChatMessage)
                        .where(
                            ChatMessage.conversation_id == self.conversation.id
                        )
                        .order_by(ChatMessage.id)
                    )
                ).scalars()
            )

        self.assertEqual([row.role for row in rows], ["user", "assistant"])
        self.assertEqual(rows[1].status, "stopped")
        self.assertEqual(rows[1].content, "已停止生成。")

    async def test_cancel_repair_uses_fresh_session_if_original_rollback_fails(self):
        async with self.session_factory() as session:
            pending = ChatMessage(
                conversation_id=self.conversation.id,
                role="assistant",
                content="",
                status="pending",
            )
            session.add(pending)
            await session.commit()

            with patch.object(
                session,
                "rollback",
                new=AsyncMock(side_effect=RuntimeError("broken request session")),
            ):
                await chat_service._persist_cancelled_assistant(
                    session,
                    pending.id,
                    content="已停止生成。",
                )

        async with self.session_factory() as verify_session:
            repaired = await verify_session.get(ChatMessage, pending.id)
        self.assertIsNotNone(repaired)
        self.assertEqual(repaired.status, "stopped")

    async def test_cancelled_memory_recall_persists_paired_stopped_message(self):
        async def cancelled(*_args, **_kwargs):
            raise asyncio.CancelledError()

        with patch.object(
            chat_service,
            "run_chat_tool_agent",
            new=AsyncMock(return_value=ToolAgentReport(
                degraded=True,
                degradation_reason="PLANNER_ERROR",
            )),
        ), patch.object(
            chat_service,
            "_load_legacy_profile_plan",
            new=AsyncMock(return_value=({}, None)),
        ):
            await self._assert_setup_cancellation_is_paired(
                patch.object(
                    chat_service,
                    "retrieve_user_memory_result",
                    new=cancelled,
                )
            )

    async def test_cancelled_summary_loading_persists_paired_stopped_message(self):
        async def cancelled(*_args, **_kwargs):
            raise asyncio.CancelledError()

        with patch.object(
            chat_service,
            "_load_chat_history",
            new=AsyncMock(return_value=[]),
        ):
            await self._assert_setup_cancellation_is_paired(
                patch.object(
                chat_service,
                "get_latest_completed_summary",
                    new=cancelled,
                )
            )

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

    async def test_successful_tool_routing_does_not_eagerly_load_legacy_context(self):
        fake_llm = _FakeStreamingLlm(["你好，有什么可以帮你？"])
        legacy_loader = AsyncMock(side_effect=AssertionError("legacy context loaded"))
        automatic_memory = AsyncMock(side_effect=AssertionError("automatic memory loaded"))

        async with self.session_factory() as session:
            with patch.object(
                chat_service,
                "run_chat_tool_agent",
                new=AsyncMock(return_value=ToolAgentReport()),
            ), patch.object(
                chat_service,
                "_load_legacy_profile_plan",
                new=legacy_loader,
            ), patch.object(
                chat_service,
                "retrieve_user_memory_result",
                new=automatic_memory,
            ), patch.object(
                chat_service,
                "_chat_llm",
                return_value=fake_llm,
            ):
                events = [
                    event async for event in chat_service.stream_chat_message(
                        session, self.conversation.id, 1, "你好"
                    )
                ]

        legacy_loader.assert_not_awaited()
        automatic_memory.assert_not_awaited()
        self.assertEqual(events[-1]["event"], "done")

    async def test_memory_tool_reports_its_effective_retrieval_mode(self):
        report = ToolAgentReport(
            selected_count=1,
            traces=[ToolTrace(
                call_id="call-memory",
                tool_name="search_memories",
                label="长期记忆",
                status="completed",
                summary="命中 1 条记忆",
            )],
            artifacts=[{
                "kind": "tool",
                "title": "长期记忆检索",
                "content": '{"items":[{"memory_id":9}]}',
                "reference_id": "tool:call-memory",
                "score": 1.0,
            }],
            memory_usages=[{
                "tool_reference_id": "tool:call-memory",
                "run_id": "memory-run-1",
                "memory_ids": [9],
                "effective_mode": "keyword",
                "degraded": True,
            }],
        )
        async with self.session_factory() as session:
            with patch.object(
                chat_service,
                "run_chat_tool_agent",
                new=AsyncMock(return_value=report),
            ), patch.object(
                chat_service,
                "_chat_llm",
                return_value=_FakeStreamingLlm(["我记得你的偏好。"]),
            ):
                events = [
                    event async for event in chat_service.stream_chat_message(
                        session, self.conversation.id, 1, "我以前说过什么偏好？"
                    )
                ]

        meta = events[0]["data"]
        self.assertEqual(meta["memory_retrieval_mode"], "keyword")
        self.assertTrue(meta["memory_retrieval_degraded"])
        self.assertEqual(meta["memory_ids"], [9])

    async def test_multiple_memory_tools_report_each_included_retrieval_run(self):
        report = ToolAgentReport(
            selected_count=2,
            traces=[
                ToolTrace(
                    call_id="m1",
                    tool_name="search_memories",
                    label="长期记忆",
                    status="completed",
                    summary="第一组",
                ),
                ToolTrace(
                    call_id="m2",
                    tool_name="search_memories",
                    label="长期记忆",
                    status="completed",
                    summary="第二组",
                ),
            ],
            artifacts=[
                {
                    "kind": "tool",
                    "title": "m1",
                    "content": '{"items":[{"memory_id":1}]}',
                    "reference_id": "tool:m1",
                    "score": 1.0,
                },
                {
                    "kind": "tool",
                    "title": "m2",
                    "content": '{"items":[{"memory_id":2}]}',
                    "reference_id": "tool:m2",
                    "score": 1.0,
                },
            ],
            memory_usages=[
                {
                    "tool_reference_id": "tool:m1",
                    "run_id": "run-vector",
                    "memory_ids": [1],
                    "effective_mode": "vector",
                    "degraded": False,
                },
                {
                    "tool_reference_id": "tool:m2",
                    "run_id": "run-keyword",
                    "memory_ids": [2],
                    "effective_mode": "keyword",
                    "degraded": True,
                },
            ],
        )
        async with self.session_factory() as session:
            with patch.object(
                chat_service,
                "run_chat_tool_agent",
                new=AsyncMock(return_value=report),
            ), patch.object(
                chat_service,
                "_chat_llm",
                return_value=_FakeStreamingLlm(["完成"]),
            ):
                events = [
                    event async for event in chat_service.stream_chat_message(
                        session, self.conversation.id, 1, "两组记忆"
                    )
                ]

        meta = events[0]["data"]
        self.assertEqual(meta["memory_ids"], [1, 2])
        self.assertIsNone(meta["memory_retrieval_run_id"])
        self.assertIsNone(meta["memory_retrieval_mode"])
        self.assertEqual(
            meta["memory_retrieval_runs"],
            [
                {
                    "run_id": "run-vector",
                    "memory_ids": [1],
                    "effective_mode": "vector",
                    "degraded": False,
                },
                {
                    "run_id": "run-keyword",
                    "memory_ids": [2],
                    "effective_mode": "keyword",
                    "degraded": True,
                },
            ],
        )

    async def test_knowledge_tool_reports_actual_included_knowledge_count(self):
        report = ToolAgentReport(
            selected_count=1,
            traces=[ToolTrace(
                call_id="call-knowledge",
                tool_name="search_knowledge",
                label="专业知识",
                status="completed",
                summary="命中 1 条资料",
                source_count=1,
            )],
            artifacts=[{
                "kind": "tool",
                "title": "专业知识检索",
                "content": '{"documents":[{"chunk_id":"doc-1"}]}',
                "reference_id": "tool:call-knowledge",
                "score": 1.0,
            }],
            citations=[{
                "chunk_id": "doc-1",
                "title": "训练资料",
                "category": "training",
                "source_name": "测试来源",
                "source_url": "https://example.com/doc-1",
                "evidence_level": "secondary",
                "score": 0.8,
                "tool_reference_id": "tool:call-knowledge",
            }],
        )
        async with self.session_factory() as session:
            with patch.object(
                chat_service,
                "run_chat_tool_agent",
                new=AsyncMock(return_value=report),
            ), patch.object(
                chat_service,
                "_chat_llm",
                return_value=_FakeStreamingLlm(["请参考这条训练资料。"]),
            ):
                events = [
                    event async for event in chat_service.stream_chat_message(
                        session, self.conversation.id, 1, "训练时应该注意什么？"
                    )
                ]

        meta = events[0]["data"]
        self.assertEqual(meta["knowledge_count"], 1)
        self.assertEqual(events[-2]["event"], "citations")
        self.assertEqual(len(events[-2]["data"]), 1)

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

    async def test_empty_model_response_is_not_marked_completed(self):
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
                return_value=_FakeStreamingLlm([]),
            ):
                events = [
                    event async for event in chat_service.stream_chat_message(
                        session, self.conversation.id, 1, "测试空响应"
                    )
                ]

            message = (
                await session.execute(
                    select(ChatMessage)
                    .where(ChatMessage.role == "assistant")
                    .order_by(desc(ChatMessage.id))
                    .limit(1)
                )
            ).scalar_one()
            self.assertEqual([event["event"] for event in events][-1], "error")
            self.assertEqual(message.status, "failed")
            self.assertEqual(message.content, "生成失败，请稍后重试。")

    async def test_model_failure_after_partial_output_preserves_partial_answer(self):
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
                return_value=_PartialThenFailingLlm(RuntimeError("provider failed")),
            ):
                events = [
                    event async for event in chat_service.stream_chat_message(
                        session, self.conversation.id, 1, "测试部分失败"
                    )
                ]

            message = (
                await session.execute(
                    select(ChatMessage)
                    .where(ChatMessage.role == "assistant")
                    .order_by(desc(ChatMessage.id))
                    .limit(1)
                )
            ).scalar_one()
            self.assertEqual(
                "".join(
                    event["data"]["content"]
                    for event in events
                    if event["event"] == "delta"
                ),
                "已生成部分",
            )
            self.assertEqual(events[-1]["event"], "error")
            self.assertEqual(message.status, "failed")
            self.assertEqual(message.content, "已生成部分")

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

    async def test_cancelled_stream_preserves_partial_answer(self):
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
                return_value=_PartialThenFailingLlm(asyncio.CancelledError()),
            ):
                observed = []
                with self.assertRaises(asyncio.CancelledError):
                    async for event in chat_service.stream_chat_message(
                        session, self.conversation.id, 1, "停止部分回答"
                    ):
                        observed.append(event)

            message = (
                await session.execute(
                    select(ChatMessage)
                    .where(ChatMessage.role == "assistant")
                    .order_by(desc(ChatMessage.id))
                    .limit(1)
                )
            ).scalar_one()
            self.assertEqual(message.status, "stopped")
            self.assertEqual(message.content, "已生成部分")
            self.assertIn("context_budget", json.loads(message.context_json))

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

        fake_llm = _FakeStreamingLlm(["仍可完成回答"])
        legacy_result = {
            **self._graph_result(),
            "profile": {"height": 175, "weight": 75},
        }
        legacy_graph = AsyncMock(return_value=legacy_result)
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
                return_value=fake_llm,
            ), patch.object(
                chat_service._CHAT_GRAPH,
                "ainvoke",
                new=legacy_graph,
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
            legacy_graph.assert_awaited_once()
            rendered_context = "\n".join(str(item.content) for item in fake_llm.messages)
            self.assertIn('"height": 175', rendered_context)
            statement = (
                select(ChatMessage)
                .where(ChatMessage.role == "assistant")
                .order_by(desc(ChatMessage.id))
                .limit(1)
            )
            message = (await session.execute(statement)).scalar_one()
            self.assertEqual(message.status, "completed")
            self.assertEqual(message.content, "仍可完成回答")

    async def test_partial_tool_failure_falls_back_and_keeps_successful_tool(self):
        report = ToolAgentReport(
            selected_count=2,
            degraded=True,
            degradation_reason="TOOL_EXECUTION_FAILED",
            traces=[
                ToolTrace(
                    call_id="call-plan",
                    tool_name="get_latest_plan",
                    label="当前计划",
                    status="completed",
                    summary="已读取计划",
                ),
                ToolTrace(
                    call_id="call-checkin",
                    tool_name="get_recent_checkins",
                    label="近期打卡",
                    status="failed",
                    summary="查询超时，已跳过",
                    error_code="TOOL_TIMEOUT",
                ),
            ],
            artifacts=[{
                "kind": "tool",
                "title": "当前计划",
                "content": '{"daily_calorie_target":1900}',
                "reference_id": "tool:call-plan",
                "score": 1.0,
            }],
        )
        fake_llm = _FakeStreamingLlm(["仍基于计划回答"])
        legacy_graph = AsyncMock(return_value=self._graph_result())

        async with self.session_factory() as session:
            with patch.object(
                chat_service,
                "run_chat_tool_agent",
                new=AsyncMock(return_value=report),
            ), patch.object(
                chat_service._CHAT_GRAPH,
                "ainvoke",
                new=legacy_graph,
            ), patch.object(
                chat_service,
                "_chat_llm",
                return_value=fake_llm,
            ):
                events = [
                    event async for event in chat_service.stream_chat_message(
                        session, self.conversation.id, 1, "结合计划和打卡分析"
                    )
                ]

        legacy_graph.assert_awaited_once()
        rendered_context = "\n".join(str(item.content) for item in fake_llm.messages)
        self.assertIn('"daily_calorie_target":1900', rendered_context)
        self.assertIn("按体重安排蛋白质", rendered_context)
        self.assertEqual(
            [event["data"]["status"] for event in events if event["event"] == "tool"],
            ["completed", "failed"],
        )
