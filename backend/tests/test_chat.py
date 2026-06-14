import tempfile
import unittest
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.graph.chat_workflow import assess_risk
from app.main import app
from app.models.user import ChatMessage, User
from app.services import chat_service


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


class _FakeStreamingLlm:
    def __init__(self, chunks=None, error: Exception | None = None):
        self.chunks = chunks or []
        self.error = error

    async def astream(self, _messages):
        if self.error:
            raise self.error
        for chunk in self.chunks:
            yield SimpleNamespace(content=chunk)


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

    async def test_model_failure_persists_failed_status(self):
        async with self.session_factory() as session:
            with patch.object(
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
