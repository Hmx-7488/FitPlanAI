import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.memory.types import MemoryRecallHit, MemoryRecallResult
from app.models.user import (
    UserMemory,
    UserMemoryRetrievalHit,
    UserMemoryRetrievalRun,
)
from app.services.memory_retrieval_service import (
    mark_memory_hits_included,
    retrieve_user_memory_result,
)


class FakeRetriever:
    def __init__(self, result):
        self.result = result

    async def retrieve(self, db, user_id, query, *, mode, limit):
        return self.result


def _memory(memory_id: int) -> UserMemory:
    return UserMemory(
        id=memory_id,
        user_id=1,
        memory_type="preference",
        memory_key=f"diet.preference.{memory_id}",
        content_json="{}",
        content_text=f"preference {memory_id}",
        content_fingerprint=f"fingerprint-{memory_id}",
        confirmation_status="confirmed",
        sensitivity="normal",
        confidence=1,
        active_slot="active",
        created_by="user",
    )


class MemoryRetrievalUsageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        path = Path(self.temp_dir.name) / "usage.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_persists_content_free_ranks_and_marks_only_actual_usage(self):
        first = _memory(1)
        second = _memory(2)
        result = MemoryRecallResult(
            hits=(
                MemoryRecallHit(
                    memory=first,
                    channels=("keyword", "vector"),
                    keyword_rank=1,
                    vector_rank=2,
                    fusion_score=0.03,
                    final_score=0.03,
                    final_rank=1,
                ),
                MemoryRecallHit(
                    memory=second,
                    channels=("vector",),
                    vector_rank=1,
                    fusion_score=0.016,
                    final_score=0.016,
                    final_rank=2,
                ),
            ),
            requested_mode="hybrid",
            effective_mode="hybrid",
            keyword_candidate_count=1,
            vector_candidate_count=2,
        )
        query = "please remember my breakfast preference"
        async with self.sessions() as db:
            recall, run_id = await retrieve_user_memory_result(
                db,
                1,
                query,
                consumer="chat",
                conversation_id=5,
                source_message_id=9,
                retriever=FakeRetriever(result),
            )
            await mark_memory_hits_included(db, run_id, [2])

        async with self.sessions() as db:
            run = await db.get(UserMemoryRetrievalRun, run_id)
            hits = list(
                (
                    await db.execute(
                        select(UserMemoryRetrievalHit).order_by(
                            UserMemoryRetrievalHit.final_rank
                        )
                    )
                ).scalars()
            )

        self.assertEqual(recall.memories, [first, second])
        self.assertEqual(run.query_hash, hashlib.sha256(query.encode()).hexdigest())
        self.assertNotIn(query, json.dumps(run.__dict__, default=str))
        self.assertEqual(json.loads(hits[0].channels_json), ["keyword", "vector"])
        self.assertEqual(hits[0].keyword_rank, 1)
        self.assertAlmostEqual(hits[0].rrf_score, 0.03)
        self.assertFalse(hits[0].included_in_context)
        self.assertTrue(hits[1].included_in_context)

    async def test_degradation_diagnostics_are_persisted(self):
        result = MemoryRecallResult(
            hits=(),
            requested_mode="hybrid",
            effective_mode="keyword",
            degraded=True,
            degradation_reason="vector_index_unavailable",
            stale_vector_candidate_count=3,
        )
        async with self.sessions() as db:
            _, run_id = await retrieve_user_memory_result(
                db,
                1,
                "query",
                consumer="plan",
                retriever=FakeRetriever(result),
            )
        async with self.sessions() as db:
            run = await db.get(UserMemoryRetrievalRun, run_id)

        self.assertEqual(run.requested_mode, "hybrid")
        self.assertEqual(run.effective_mode, "keyword")
        self.assertEqual(run.degraded_reason, "vector_index_unavailable")
        self.assertEqual(run.stale_filtered_count, 3)


if __name__ == "__main__":
    unittest.main()
