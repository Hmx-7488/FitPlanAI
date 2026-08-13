import asyncio
import json
import shutil
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.graph.chat_workflow import assess_risk
from app.memory.retriever import MemoryRetriever
from app.memory.vectorstore import ChromaMemoryVectorStore
from app.models.user import ChatConversation, ChatMessage, UserMemory, UserMemoryIndexOutbox
from app.rag.models import KnowledgeChunk
from app.rag.retriever import HybridRetriever
from app.rag.vectorstore import VectorStoreManager
from app.services.memory_index_service import (
    memory_index_maintenance_worker,
    process_memory_index_outbox,
    run_memory_index_maintenance,
)
from app.services.conversation_summary_service import compact_conversation_if_needed
from app.services.user_memory_service import (
    ExtractedMemoryCandidate,
    extract_and_persist_user_memory,
    replay_pending_memory_extractions,
    update_user_memory,
)


class FakeVectorBackend:
    def __init__(self, *, initialized=True, fail_upserts=0):
        self.initialized = initialized
        self.fail_upserts = fail_upserts
        self.upsert_calls = 0
        self.closed = False
        self.cleanup_calls = 0
        self.documents: dict[int, tuple[int, int, str]] = {}

    async def search(self, query, *, user_id, limit):
        return []

    async def upsert(self, memory):
        self.upsert_calls += 1
        if self.upsert_calls <= self.fail_upserts:
            raise TimeoutError("temporary vector failure")
        self.initialized = True
        self.documents[memory.id] = (
            memory.user_id,
            int(memory.index_revision or 0),
            memory.content_fingerprint,
        )

    async def delete(self, memory_id):
        self.documents.pop(memory_id, None)

    async def list_memory_ids(self):
        return set(self.documents)

    async def list_memory_revisions(self):
        return {
            memory_id: (document[1], document[2])
            for memory_id, document in self.documents.items()
        }

    async def collection_exists(self):
        return self.initialized

    async def cleanup_obsolete_collections(self):
        self.cleanup_calls += 1
        return 0

    async def close(self):
        self.closed = True


class DeterministicEmbeddings:
    def embed_documents(self, texts):
        return [[float(len(text) % 7), 1.0, 0.5] for text in texts]

    def embed_query(self, text):
        return [float(len(text) % 7), 1.0, 0.5]


class NoopAsyncLock:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class LateOldWriteBackend(FakeVectorBackend):
    def __init__(self):
        super().__init__(initialized=True)
        self.first_started = asyncio.Event()
        self.release_first = asyncio.Event()

    async def upsert(self, memory):
        self.upsert_calls += 1
        revision = int(memory.index_revision or 0)
        fingerprint = memory.content_fingerprint
        if self.upsert_calls == 1:
            self.first_started.set()
            await self.release_first.wait()
        self.documents[memory.id] = (memory.user_id, revision, fingerprint)


def _memory(memory_id: int | None = None, *, text="用户早餐喜欢燕麦") -> UserMemory:
    return UserMemory(
        id=memory_id,
        user_id=1,
        memory_type="preference",
        memory_key="diet.breakfast.oatmeal",
        content_json="{}",
        content_text=text,
        content_fingerprint=f"fingerprint-{memory_id or 0}",
        index_revision=1,
        confirmation_status="confirmed",
        sensitivity="normal",
        confidence=1,
        active_slot="active",
        valid_from=datetime.utcnow() - timedelta(days=1),
        created_by="user",
    )


class RagMemoryReliabilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        path = Path(self.temp_dir.name) / "reliability.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.settings = SimpleNamespace(
            MEMORY_VECTOR_ENABLED=True,
            MEMORY_INDEX_MAX_ATTEMPTS=3,
            MEMORY_INDEX_RETRY_BASE_SECONDS=1,
            MEMORY_INDEX_BATCH_SIZE=20,
            MEMORY_CLEANUP_OBSOLETE_COLLECTIONS=True,
            MEMORY_KEYWORD_CANDIDATE_LIMIT=100,
            MEMORY_VECTOR_CANDIDATE_LIMIT=40,
            MEMORY_HEALTH_RECALL_LIMIT=4,
            MEMORY_RRF_K=60,
            CHAT_MEMORY_RECALL_LIMIT=12,
            MEMORY_RETRIEVAL_MODE="keyword",
            CHAT_MEMORY_EXTRACTION_ENABLED=True,
            CHAT_MEMORY_EXTRACTION_RETRY_BASE_SECONDS=1,
            CHAT_MEMORY_EXTRACTION_MAX_ATTEMPTS=5,
            CHAT_MEMORY_AUTO_CONFIRM_MIN_CONFIDENCE=0.8,
        )

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_existing_collection_backfills_a_missing_completed_document(self):
        async with self.sessions() as db:
            memory = _memory()
            db.add(memory)
            await db.flush()
            db.add(UserMemoryIndexOutbox(
                memory_id=memory.id,
                user_id=memory.user_id,
                operation="upsert",
                index_revision=memory.index_revision,
                status="completed",
                processed_at=datetime.utcnow(),
            ))
            await db.commit()
            memory_id = memory.id

        backend = FakeVectorBackend(initialized=True)
        with patch("app.services.memory_index_service.get_settings", return_value=self.settings):
            stats = await run_memory_index_maintenance(
                self.sessions, vector_backend=backend
            )

        self.assertEqual(stats["completed"], 1)
        self.assertIn(memory_id, backend.documents)

    async def test_existing_collection_repairs_stale_same_id_metadata(self):
        async with self.sessions() as db:
            memory = _memory()
            db.add(memory)
            await db.flush()
            db.add(UserMemoryIndexOutbox(
                memory_id=memory.id,
                user_id=memory.user_id,
                operation="upsert",
                index_revision=memory.index_revision,
                status="completed",
                processed_at=datetime.utcnow(),
            ))
            await db.commit()
            memory_id = memory.id

        backend = FakeVectorBackend(initialized=True)
        backend.documents[memory_id] = (1, 0, "stale-fingerprint")
        with patch("app.services.memory_index_service.get_settings", return_value=self.settings):
            stats = await run_memory_index_maintenance(
                self.sessions, vector_backend=backend
            )

        self.assertEqual(stats["completed"], 1)
        self.assertEqual(
            backend.documents[memory_id],
            (1, memory.index_revision, memory.content_fingerprint),
        )

    async def test_expired_legacy_null_slot_is_removed_from_vector_index(self):
        async with self.sessions() as db:
            memory = _memory()
            memory.active_slot = None
            memory.valid_until = datetime.utcnow() - timedelta(minutes=1)
            db.add(memory)
            await db.flush()
            db.add(UserMemoryIndexOutbox(
                memory_id=memory.id,
                user_id=memory.user_id,
                operation="upsert",
                index_revision=memory.index_revision,
                status="completed",
            ))
            await db.commit()
            memory_id = memory.id

        backend = FakeVectorBackend(initialized=True)
        backend.documents[memory_id] = (1, 1, memory.content_fingerprint)
        with patch("app.services.memory_index_service.get_settings", return_value=self.settings):
            await run_memory_index_maintenance(self.sessions, vector_backend=backend)

        self.assertNotIn(memory_id, backend.documents)

    async def test_keyword_recall_can_find_relevant_memory_older_than_recent_window(self):
        old = _memory(1, text="用户对山竹严重不耐受")
        old.memory_key = "diet.intolerance.mangosteen"
        old.updated_at = datetime.utcnow() - timedelta(days=365)
        memories = [old]
        for memory_id in range(2, 103):
            item = _memory(memory_id, text=f"用户记录了普通偏好 {memory_id}")
            item.memory_key = f"preference.generic.{memory_id}"
            memories.append(item)
        async with self.sessions() as db:
            db.add_all(memories)
            await db.commit()

        with patch("app.memory.retriever.get_settings", return_value=self.settings):
            async with self.sessions() as db:
                result = await MemoryRetriever(FakeVectorBackend()).retrieve(
                    db, 1, "山竹不耐受", mode="keyword", limit=5
                )

        self.assertIn(old.id, [hit.memory.id for hit in result.hits])

    async def test_failed_memory_extraction_records_retryable_state(self):
        async with self.sessions() as db:
            conversation = ChatConversation(user_id=1)
            db.add(conversation)
            await db.flush()
            message = ChatMessage(
                conversation_id=conversation.id,
                role="user",
                content="我不吃花生",
                status="completed",
            )
            db.add(message)
            await db.commit()
            conversation_id, message_id = conversation.id, message.id

        with (
            patch("app.services.user_memory_service.get_settings", return_value=self.settings),
            patch("app.services.user_memory_service.async_session", self.sessions),
            patch(
                "app.services.user_memory_service.extract_memory_candidates",
                new=AsyncMock(side_effect=TimeoutError("provider unavailable")),
            ),
        ):
            created = await extract_and_persist_user_memory(conversation_id, message_id)

        self.assertEqual(created, 0)
        async with self.sessions() as db:
            stored = await db.get(ChatMessage, message_id)
            context = json.loads(stored.context_json)
        self.assertEqual(context["memory_extraction_status"], "failed")
        self.assertEqual(context["memory_extraction_error_type"], "TimeoutError")
        self.assertGreaterEqual(context["memory_extraction_attempts"], 1)
        self.assertIn("memory_extraction_available_at", context)

    async def test_stale_slow_extractor_cannot_persist_after_lease_takeover(self):
        async with self.sessions() as db:
            conversation = ChatConversation(user_id=1)
            db.add(conversation)
            await db.flush()
            message = ChatMessage(
                conversation_id=conversation.id,
                role="user",
                content="我的早餐偏好改变了",
                status="completed",
            )
            db.add(message)
            await db.commit()
            conversation_id, message_id = conversation.id, message.id

        first_started = asyncio.Event()
        release_first = asyncio.Event()
        call_count = 0

        async def extract(_content):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                first_started.set()
                await release_first.wait()
                text = "用户早餐喜欢燕麦"
            else:
                text = "用户早餐喜欢鸡蛋"
            return [ExtractedMemoryCandidate(
                memory_type="preference",
                memory_key="diet.breakfast.preference",
                content={"value": text},
                content_text=text,
                sensitivity="normal",
                confidence=1,
            )]

        with (
            patch("app.services.user_memory_service.get_settings", return_value=self.settings),
            patch(
                "app.services.user_memory_service.extract_memory_candidates",
                side_effect=extract,
            ),
        ):
            stale = asyncio.create_task(extract_and_persist_user_memory(
                conversation_id,
                message_id,
                session_factory=self.sessions,
                lease_owner="worker-a",
            ))
            await first_started.wait()
            async with self.sessions() as db:
                message = await db.get(ChatMessage, message_id)
                context = json.loads(message.context_json)
                context["memory_extraction_lease_expires_at"] = (
                    datetime.utcnow() - timedelta(seconds=1)
                ).isoformat()
                message.context_json = json.dumps(context, ensure_ascii=False)
                await db.commit()

            winner = await extract_and_persist_user_memory(
                conversation_id,
                message_id,
                session_factory=self.sessions,
                lease_owner="worker-b",
            )
            release_first.set()
            stale_result = await stale

        self.assertEqual(winner, 1)
        self.assertEqual(stale_result, 0)
        async with self.sessions() as db:
            memories = list((await db.execute(select(UserMemory))).scalars())
        self.assertEqual([memory.content_text for memory in memories], ["用户早餐喜欢鸡蛋"])

    async def test_continuous_worker_drains_more_than_one_batch_and_closes(self):
        self.settings.MEMORY_INDEX_BATCH_SIZE = 2
        async with self.sessions() as db:
            for index in range(5):
                memory = _memory(text=f"偏好 {index}")
                memory.memory_key = f"diet.preference.{index}"
                memory.content_fingerprint = f"fingerprint-{index}"
                db.add(memory)
                await db.flush()
                db.add(UserMemoryIndexOutbox(
                    memory_id=memory.id,
                    user_id=1,
                    operation="upsert",
                    index_revision=1,
                ))
            await db.commit()

        backend = FakeVectorBackend(initialized=True)
        stop = asyncio.Event()
        with patch("app.services.memory_index_service.get_settings", return_value=self.settings):
            task = asyncio.create_task(memory_index_maintenance_worker(
                stop_event=stop,
                vector_backend=backend,
                session_factory=self.sessions,
                interval_seconds=0.01,
            ))
            for _ in range(200):
                if len(backend.documents) == 5:
                    break
                await asyncio.sleep(0.01)
            stop.set()
            await asyncio.wait_for(task, timeout=2)

        self.assertEqual(len(backend.documents), 5)
        self.assertTrue(backend.closed)

    async def test_expired_lease_late_old_write_is_reconciled_to_latest_revision(self):
        async with self.sessions() as db:
            memory = _memory()
            db.add(memory)
            await db.flush()
            db.add(UserMemoryIndexOutbox(
                memory_id=memory.id,
                user_id=memory.user_id,
                operation="upsert",
                index_revision=memory.index_revision,
            ))
            await db.commit()
            memory_id = memory.id

        backend = LateOldWriteBackend()
        with (
            patch("app.services.memory_index_service.get_settings", return_value=self.settings),
            patch(
                "app.services.memory_index_service._VECTOR_WRITE_LOCK",
                NoopAsyncLock(),
            ),
        ):
            old_worker = asyncio.create_task(process_memory_index_outbox(
                vector_backend=backend,
                session_factory=self.sessions,
                batch_size=1,
            ))
            await backend.first_started.wait()
            async with self.sessions() as db:
                updated = await update_user_memory(
                    db,
                    memory_id,
                    1,
                    content={"value": "new"},
                    content_text="用户早餐改为喜欢鸡蛋",
                )
                old_job = (
                    await db.execute(
                        select(UserMemoryIndexOutbox)
                        .where(UserMemoryIndexOutbox.index_revision == 1)
                    )
                ).scalar_one()
                old_job.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
                await db.commit()

            await process_memory_index_outbox(
                vector_backend=backend,
                session_factory=self.sessions,
                batch_size=2,
            )
            backend.release_first.set()
            await old_worker

        self.assertEqual(
            backend.documents[memory_id],
            (1, updated.index_revision, updated.content_fingerprint),
        )

    async def test_retry_scanner_replays_due_failed_memory_extraction(self):
        async with self.sessions() as db:
            conversation = ChatConversation(user_id=1)
            db.add(conversation)
            await db.flush()
            message = ChatMessage(
                conversation_id=conversation.id,
                role="user",
                content="我不吃花生",
                status="completed",
                context_json=json.dumps({
                    "memory_extraction_status": "failed",
                    "memory_extraction_attempts": 1,
                    "memory_extraction_available_at": (
                        datetime.utcnow() - timedelta(seconds=1)
                    ).isoformat(),
                }),
            )
            db.add(message)
            await db.commit()
            message_id = message.id

        with (
            patch("app.services.user_memory_service.get_settings", return_value=self.settings),
            patch(
                "app.services.user_memory_service.extract_memory_candidates",
                new=AsyncMock(return_value=[]),
            ),
        ):
            stats = await replay_pending_memory_extractions(
                session_factory=self.sessions,
                limit=10,
            )

        self.assertEqual(stats["attempted"], 1)
        async with self.sessions() as db:
            stored = await db.get(ChatMessage, message_id)
            context = json.loads(stored.context_json)
        self.assertEqual(context["memory_extraction_status"], "skipped")

    async def test_summary_claim_allows_only_one_concurrent_llm_call(self):
        async with self.sessions() as db:
            conversation = ChatConversation(user_id=1)
            db.add(conversation)
            await db.flush()
            db.add_all([
                ChatMessage(
                    conversation_id=conversation.id,
                    role="user" if index % 2 == 0 else "assistant",
                    content=f"消息 {index}",
                    status="completed",
                )
                for index in range(6)
            ])
            await db.commit()
            conversation_id = conversation.id

        summary_settings = SimpleNamespace(
            CHAT_CONTEXT_MAX_HISTORY_MESSAGES=500,
            CHAT_SUMMARY_TRIGGER_TOKENS=1,
            CHAT_SUMMARY_TRIGGER_MESSAGES=2,
            CHAT_SUMMARY_KEEP_RECENT_TOKENS=1,
            CHAT_SUMMARY_PENDING_LEASE_SECONDS=300,
            CHAT_SUMMARY_MAX_OUTPUT_TOKENS=200,
            LLM_MODEL="fake",
            LLM_API_KEY="",
            LLM_BASE_URL="http://invalid",
        )
        release = asyncio.Event()
        calls = 0

        async def invoke(_messages):
            nonlocal calls
            calls += 1
            await release.wait()
            return SimpleNamespace(content=json.dumps({
                "current_goal": "",
                "confirmed_facts": [],
                "constraints": [],
                "decisions": [],
                "open_questions": [],
                "pending_actions": [],
                "corrections": [],
            }))

        llm = SimpleNamespace(ainvoke=invoke)
        with (
            patch(
                "app.services.conversation_summary_service.get_settings",
                return_value=summary_settings,
            ),
            patch(
                "app.services.conversation_summary_service._summary_llm",
                return_value=llm,
            ),
        ):
            first = asyncio.create_task(compact_conversation_if_needed(
                conversation_id, session_factory=self.sessions
            ))
            for _ in range(100):
                if calls:
                    break
                await asyncio.sleep(0.01)
            second = asyncio.create_task(compact_conversation_if_needed(
                conversation_id, session_factory=self.sessions
            ))
            await asyncio.sleep(0.05)
            release.set()
            results = await asyncio.gather(first, second)

        self.assertEqual(calls, 1)
        self.assertEqual(sorted(results), [False, True])


class KnowledgeReliabilityTests(unittest.TestCase):
    @staticmethod
    def _chunk(chunk_id: str) -> KnowledgeChunk:
        return KnowledgeChunk(
            chunk_id=chunk_id,
            document_id=f"doc-{chunk_id}",
            title=chunk_id,
            content=f"content {chunk_id}",
        )

    def test_hybrid_merge_uses_rank_fusion_not_incomparable_raw_max(self):
        retriever = HybridRetriever()
        both = self._chunk("both")
        vector_only = self._chunk("vector")
        keyword_only = self._chunk("keyword")

        merged = retriever._merge(
            [(vector_only, 0.99), (both, 0.20)],
            [(keyword_only, 9.5), (both, 1.0)],
        )

        self.assertEqual(merged["both"][2], "hybrid")
        self.assertGreater(merged["both"][1], merged["vector"][1])
        self.assertGreater(merged["both"][1], merged["keyword"][1])
        self.assertLessEqual(max(value[1] for value in merged.values()), 1.0)

    def test_rrf_ignores_extreme_raw_score_scales(self):
        retriever = HybridRetriever()
        first = self._chunk("first")
        second = self._chunk("second")

        normal = retriever._merge(
            [(first, 0.9), (second, 0.8)],
            [(second, 9.0), (first, 1.0)],
        )
        extreme = retriever._merge(
            [(first, -999999.0), (second, 999999.0)],
            [(second, 1e100), (first, -1e100)],
        )

        self.assertEqual(normal["first"][1], extreme["first"][1])
        self.assertEqual(normal["second"][1], extreme["second"][1])

    def test_pre_swap_rebuild_failure_preserves_current_index(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            current = base / "vectorstore"
            current.mkdir()
            marker = current / "old-index.marker"
            marker.write_text("keep", encoding="utf-8")
            manager = VectorStoreManager()
            manager._store = SimpleNamespace(
                _client=SimpleNamespace(close=lambda: None)
            )
            chunk = self._chunk("new")

            with (
                patch("app.rag.vectorstore._BASE_DIR", base),
                patch("app.rag.vectorstore._VECTORSTORE_DIR", current),
                patch.object(manager, "_get_embeddings", return_value=object()),
                patch(
                    "app.rag.vectorstore.Chroma.from_documents",
                    side_effect=RuntimeError("embedding failed"),
                ),
            ):
                with self.assertRaises(RuntimeError):
                    manager.index_chunks([chunk])

            self.assertTrue(marker.exists())

    def test_two_managers_publish_concurrently_without_shared_temp_collisions(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            current = base / "vectorstore"
            current.mkdir()
            (current / "old.marker").write_text("old", encoding="utf-8")
            managers = [VectorStoreManager(), VectorStoreManager()]

            def fake_store():
                return SimpleNamespace(
                    _collection=SimpleNamespace(count=lambda: 1),
                    _client=SimpleNamespace(close=lambda: None),
                )

            with (
                patch("app.rag.vectorstore._BASE_DIR", base),
                patch("app.rag.vectorstore._VECTORSTORE_DIR", current),
                patch.object(
                    VectorStoreManager,
                    "_get_embeddings",
                    return_value=object(),
                ),
                patch(
                    "app.rag.vectorstore.Chroma.from_documents",
                    side_effect=lambda **_kwargs: fake_store(),
                ),
                patch(
                    "app.rag.vectorstore.Chroma",
                    side_effect=lambda **_kwargs: fake_store(),
                ) as chroma_cls,
            ):
                # Keep from_documents available after patching the class mock.
                chroma_cls.from_documents.side_effect = lambda **_kwargs: fake_store()
                with ThreadPoolExecutor(max_workers=2) as executor:
                    results = list(executor.map(
                        lambda manager: manager.index_chunks([self._chunk("new")]),
                        managers,
                    ))

            self.assertEqual([result.total_chunks for result in results], [1, 1])
            self.assertTrue(current.exists())
            self.assertEqual(list(base.glob("vectorstore_tmp_*")), [])
            self.assertEqual(list(base.glob("vectorstore_backup_*")), [])

    def test_risk_normalization_covers_reported_high_risk_phrases(self):
        for message in (
            "我每天只吃 500 大卡，而且最近头晕",
            "我想自行停用降压药",
            "训练后胸口很痛，喘不上气",
        ):
            with self.subTest(message=message):
                result = assess_risk({"user_message": message})
                self.assertEqual(result["risk_level"], "high")


class MemoryVectorStoreLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_close_releases_real_chroma_files_for_windows_cleanup(self):
        directory = Path(tempfile.mkdtemp())
        try:
            store = ChromaMemoryVectorStore(
                persist_directory=directory,
                embedding_function=DeterministicEmbeddings(),
            )
            await store.upsert(_memory(1))
            await store.close()
            shutil.rmtree(directory)
            self.assertFalse(directory.exists())
        finally:
            if directory.exists():
                shutil.rmtree(directory, ignore_errors=True)

    async def test_cleanup_removes_only_obsolete_memory_collections(self):
        current = SimpleNamespace(name="current")
        old = SimpleNamespace(name="slim_agent_user_memories_old")
        unrelated = SimpleNamespace(name="another_feature")
        deleted: list[str] = []
        client = SimpleNamespace(
            list_collections=lambda: [current, old, unrelated],
            delete_collection=lambda *, name: deleted.append(name),
            close=lambda: None,
        )
        store = object.__new__(ChromaMemoryVectorStore)
        store.collection_name = "current"
        store.persist_directory = Path("unused")
        store._store = None

        with (
            patch.object(store, "collection_exists", new=AsyncMock(return_value=True)),
            patch("app.memory.vectorstore.chromadb.PersistentClient", return_value=client),
        ):
            count = await store.cleanup_obsolete_collections()

        self.assertEqual(count, 1)
        self.assertEqual(deleted, ["slim_agent_user_memories_old"])


if __name__ == "__main__":
    unittest.main()
