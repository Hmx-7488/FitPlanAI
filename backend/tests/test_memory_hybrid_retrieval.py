import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.memory.retriever import MemoryRetriever
from app.memory.types import MemoryVectorMatch
from app.memory.vectorstore import (
    ChromaMemoryVectorStore,
    MemoryVectorUnavailable,
    memory_collection_name,
)
from app.models.user import UserMemory


class FakeVectorBackend:
    def __init__(self, matches=None, error: Exception | None = None):
        self.matches = list(matches or [])
        self.error = error
        self.searches: list[tuple[str, int, int]] = []

    async def search(self, query: str, *, user_id: int, limit: int):
        self.searches.append((query, user_id, limit))
        if self.error:
            raise self.error
        return self.matches

    async def upsert(self, memory):
        return None

    async def delete(self, memory_id: int):
        return None

    async def list_memory_ids(self):
        return set()

    async def collection_exists(self):
        return True


class CountingEmbeddings:
    def __init__(self):
        self.query_calls = 0

    def embed_query(self, _text):
        self.query_calls += 1
        raise AssertionError("embedding must not run without an index")


def _memory(
    memory_id: int,
    *,
    text: str,
    key: str | None = None,
    status: str = "confirmed",
    active_slot: str | None = "active",
    sensitivity: str = "normal",
    deleted_at: datetime | None = None,
    valid_until: datetime | None = None,
    user_id: int = 1,
) -> UserMemory:
    return UserMemory(
        id=memory_id,
        user_id=user_id,
        memory_type="constraint" if sensitivity == "health_sensitive" else "preference",
        memory_key=key or f"memory.key.{memory_id}",
        content_json="{}",
        content_text=text,
        content_fingerprint=f"fingerprint-{memory_id}",
        confirmation_status=status,
        sensitivity=sensitivity,
        confidence=1,
        active_slot=active_slot,
        valid_from=datetime.utcnow() - timedelta(days=1),
        valid_until=valid_until,
        deleted_at=deleted_at,
        created_by="user",
    )


def _match(memory: UserMemory, score: float = 0.8, *, revision: int = 0):
    return MemoryVectorMatch(
        memory_id=memory.id,
        score=score,
        content_fingerprint=memory.content_fingerprint,
        index_revision=revision,
    )


class MemoryHybridRetrievalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "memory-retrieval.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        self.session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False
        )
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def _insert(self, *memories: UserMemory):
        async with self.session_factory() as session:
            session.add_all(memories)
            await session.commit()

    async def test_keyword_mode_never_returns_inactive_lifecycle_rows(self):
        active = _memory(1, text="用户喜欢在晚上进行力量训练")
        candidate = _memory(2, text="晚上训练", status="candidate", active_slot="candidate:x")
        rejected = _memory(3, text="晚上训练", status="rejected", active_slot=None)
        deleted = _memory(4, text="晚上训练", deleted_at=datetime.utcnow())
        expired = _memory(
            5, text="晚上训练", active_slot=None,
            valid_until=datetime.utcnow() - timedelta(minutes=1),
        )
        superseded = _memory(
            6,
            text="晚上训练",
            active_slot=None,
            valid_until=datetime.utcnow() - timedelta(minutes=1),
        )
        await self._insert(active, candidate, rejected, deleted, expired, superseded)

        async with self.session_factory() as session:
            result = await MemoryRetriever(FakeVectorBackend()).retrieve(
                session, 1, "晚上力量训练", mode="keyword"
            )

        self.assertEqual([hit.memory.id for hit in result.hits], [1])
        self.assertEqual(result.hits[0].channels, ("keyword",))
        self.assertFalse(result.degraded)

    async def test_confirmed_legacy_row_without_active_slot_remains_retrievable(self):
        legacy = _memory(
            7,
            text="用户早餐喜欢全麦面包",
            active_slot=None,
        )
        await self._insert(legacy)

        async with self.session_factory() as session:
            result = await MemoryRetriever(FakeVectorBackend()).retrieve(
                session, 1, "早餐全麦面包", mode="keyword"
            )

        self.assertEqual([hit.memory.id for hit in result.hits], [legacy.id])

    async def test_vector_matches_require_current_sql_fingerprint_and_revision(self):
        current = _memory(10, text="用户不吃花生")
        stale = _memory(11, text="用户偏好游泳")
        await self._insert(current, stale)
        backend = FakeVectorBackend(
            [
                _match(current),
                MemoryVectorMatch(
                    memory_id=stale.id,
                    score=0.99,
                    content_fingerprint="old-fingerprint",
                    index_revision=0,
                ),
                MemoryVectorMatch(
                    memory_id=999,
                    score=1,
                    content_fingerprint="missing",
                    index_revision=0,
                ),
            ]
        )

        async with self.session_factory() as session:
            result = await MemoryRetriever(backend).retrieve(
                session, 1, "饮食限制", mode="vector"
            )

        self.assertEqual([hit.memory.id for hit in result.hits], [current.id])
        self.assertEqual(result.hits[0].channels, ("vector",))
        self.assertEqual(result.stale_vector_candidate_count, 2)

    async def test_vector_results_are_deduplicated_and_cross_user_ids_rejected(self):
        own = _memory(12, text="用户偏好普拉提")
        other = _memory(13, text="其他用户偏好跑步", user_id=2)
        await self._insert(own, other)
        backend = FakeVectorBackend([_match(own), _match(own), _match(other)])

        async with self.session_factory() as session:
            result = await MemoryRetriever(backend).retrieve(
                session, 1, "运动偏好", mode="vector"
            )

        self.assertEqual([hit.memory.id for hit in result.hits], [own.id])
        self.assertEqual(result.hits[0].vector_rank, 1)
        self.assertEqual(result.stale_vector_candidate_count, 1)

    async def test_hybrid_mode_uses_rrf_and_exposes_both_channel_ranks(self):
        both = _memory(20, text="用户周末喜欢游泳", key="training.swimming.weekend")
        vector_only = _memory(21, text="用户偏好椭圆机", key="training.cardio.elliptical")
        await self._insert(both, vector_only)
        backend = FakeVectorBackend([_match(vector_only), _match(both)])

        async with self.session_factory() as session:
            result = await MemoryRetriever(backend, rrf_k=60).retrieve(
                session, 1, "周末游泳", mode="hybrid"
            )

        by_id = {hit.memory.id: hit for hit in result.hits}
        self.assertEqual(by_id[both.id].keyword_rank, 1)
        self.assertEqual(by_id[both.id].vector_rank, 2)
        self.assertEqual(by_id[both.id].channels, ("keyword", "vector"))
        self.assertAlmostEqual(
            by_id[both.id].fusion_score, 1 / 61 + 1 / 62
        )
        self.assertEqual(result.effective_mode, "hybrid")

    async def test_plan_domain_query_retrieves_diet_preference(self):
        diet = _memory(
            25,
            text="用户不喜欢香菜",
            key="diet.disliked_food.cilantro",
        )
        await self._insert(diet)

        async with self.session_factory() as session:
            result = await MemoryRetriever(FakeVectorBackend()).retrieve(
                session,
                1,
                "生成饮食和训练计划，结合长期目标、偏好、习惯和已确认限制",
                mode="keyword",
            )

        self.assertEqual([hit.memory.id for hit in result.hits], [diet.id])

    async def test_hybrid_vector_failure_degrades_to_keyword_with_diagnostics(self):
        memory = _memory(30, text="用户早餐喜欢燕麦")
        await self._insert(memory)

        async with self.session_factory() as session:
            result = await MemoryRetriever(
                FakeVectorBackend(error=RuntimeError("offline"))
            ).retrieve(session, 1, "早餐燕麦", mode="hybrid")

        self.assertTrue(result.degraded)
        self.assertEqual(result.requested_mode, "hybrid")
        self.assertEqual(result.effective_mode, "keyword")
        self.assertEqual(result.degradation_reason, "vector_backend_unavailable")
        self.assertEqual([hit.memory.id for hit in result.hits], [memory.id])

    async def test_vector_only_failure_also_degrades_safely_to_keyword(self):
        memory = _memory(40, text="用户喜欢晨跑")
        await self._insert(memory)

        async with self.session_factory() as session:
            result = await MemoryRetriever(
                FakeVectorBackend(error=ConnectionError("unavailable"))
            ).retrieve(session, 1, "晨跑", mode="vector")

        self.assertTrue(result.degraded)
        self.assertEqual(result.requested_mode, "vector")
        self.assertEqual(result.effective_mode, "keyword")
        self.assertEqual([hit.memory.id for hit in result.hits], [memory.id])

    async def test_missing_index_has_specific_degradation_reason(self):
        memory = _memory(41, text="用户喜欢晨跑")
        await self._insert(memory)

        async with self.session_factory() as session:
            result = await MemoryRetriever(
                FakeVectorBackend(error=MemoryVectorUnavailable("missing"))
            ).retrieve(session, 1, "晨跑", mode="hybrid")

        self.assertTrue(result.degraded)
        self.assertEqual(result.effective_mode, "keyword")
        self.assertEqual(result.degradation_reason, "vector_index_unavailable")

    async def test_health_sensitive_safety_injection_is_bounded(self):
        health = [
            _memory(
                50 + index,
                text=f"用户存在健康限制 {index}",
                sensitivity="health_sensitive",
            )
            for index in range(4)
        ]
        await self._insert(*health)

        async with self.session_factory() as session:
            result = await MemoryRetriever(
                FakeVectorBackend(), health_limit=2
            ).retrieve(session, 1, "完全无关的查询", mode="keyword", limit=10)

        self.assertEqual(len(result.hits), 2)
        self.assertTrue(all("safety" in hit.channels for hit in result.hits))
        self.assertTrue(all(hit.final_score >= 1 for hit in result.hits))

    def test_collection_name_isolated_by_model_and_index_version(self):
        first = memory_collection_name("text-embedding-v3", "v1")
        second = memory_collection_name("text-embedding-v4", "v1")
        third = memory_collection_name("text-embedding-v3", "v2")
        self.assertNotEqual(first, second)
        self.assertNotEqual(first, third)
        self.assertNotEqual(
            memory_collection_name("vendor/model", "v1"),
            memory_collection_name("vendor:model", "v1"),
        )
        self.assertTrue(first.startswith("slim_agent_user_memories_"))

    def test_default_store_collection_includes_sanitized_model_and_version(self):
        settings = SimpleNamespace(
            MEMORY_EMBEDDING_MODEL="vendor/text embedding:v4",
            MEMORY_VECTOR_COLLECTION="memory index/v2",
        )
        with patch(
            "app.memory.vectorstore.get_settings",
            return_value=settings,
        ):
            store = ChromaMemoryVectorStore()

        self.assertEqual(
            store.collection_name,
            memory_collection_name(
                settings.MEMORY_EMBEDDING_MODEL,
                settings.MEMORY_VECTOR_COLLECTION,
            ),
        )
        self.assertNotIn("/", store.collection_name)
        self.assertNotIn(":", store.collection_name)

    async def test_missing_vector_index_does_not_create_files_or_embed_query(self):
        index_path = Path(self.temp_dir.name) / "missing-memory-index"
        embeddings = CountingEmbeddings()
        store = ChromaMemoryVectorStore(
            persist_directory=index_path,
            embedding_function=embeddings,
        )

        with self.assertRaises(MemoryVectorUnavailable):
            await store.search("早餐偏好", user_id=1, limit=5)

        self.assertEqual(embeddings.query_calls, 0)
        self.assertFalse(index_path.exists())

        await store.delete(999)
        self.assertEqual(await store.list_memory_ids(), set())
        self.assertFalse(index_path.exists())

    async def test_other_collection_does_not_make_current_collection_queryable(self):
        index_path = Path(self.temp_dir.name) / "shared-memory-index"
        index_path.mkdir()
        (index_path / "chroma.sqlite3").touch()
        client = SimpleNamespace(
            list_collections=lambda: [SimpleNamespace(name="another_model_collection")]
        )
        embeddings = CountingEmbeddings()
        store = ChromaMemoryVectorStore(
            persist_directory=index_path,
            embedding_model="current-model",
            index_version="current-version",
            embedding_function=embeddings,
        )

        with patch(
            "app.memory.vectorstore.chromadb.PersistentClient",
            return_value=client,
        ):
            with self.assertRaises(MemoryVectorUnavailable):
                await store.search("早餐偏好", user_id=1, limit=5)

        self.assertEqual(embeddings.query_calls, 0)


if __name__ == "__main__":
    unittest.main()
