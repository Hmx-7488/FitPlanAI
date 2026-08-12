import tempfile
import unittest
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.memory.types import MemoryVectorMatch
from app.models.user import UserMemory, UserMemoryIndexOutbox
from app.services.memory_index_service import (
    process_memory_index_outbox,
    rebuild_memory_index,
    run_memory_index_maintenance,
)
from app.services.user_memory_service import delete_user_memory, update_user_memory


class FakeVectorBackend:
    def __init__(self, *, fail_upserts=0, initialized=False):
        self.documents = {}
        self.fail_upserts = fail_upserts
        self.upsert_calls = 0
        self.initialized = initialized

    async def search(self, query, *, user_id, limit):
        return []

    async def upsert(self, memory):
        self.upsert_calls += 1
        if self.upsert_calls <= self.fail_upserts:
            raise TimeoutError("fake")
        self.initialized = True
        self.documents[memory.id] = (
            memory.user_id,
            memory.index_revision,
            memory.content_fingerprint,
        )

    async def delete(self, memory_id):
        self.documents.pop(memory_id, None)

    async def list_memory_ids(self):
        return set(self.documents)

    async def collection_exists(self):
        return self.initialized


class BlockingFirstUpsertBackend(FakeVectorBackend):
    def __init__(self):
        super().__init__()
        self.first_started = asyncio.Event()
        self.release_first = asyncio.Event()

    async def upsert(self, memory):
        self.upsert_calls += 1
        if self.upsert_calls == 1:
            self.first_started.set()
            await self.release_first.wait()
        self.documents[memory.id] = (
            memory.user_id,
            memory.index_revision,
            memory.content_fingerprint,
        )


class BlockingListBackend(FakeVectorBackend):
    def __init__(self):
        super().__init__()
        self.list_started = asyncio.Event()
        self.release_list = asyncio.Event()
        self.upsert_started = asyncio.Event()

    async def upsert(self, memory):
        self.upsert_started.set()
        await super().upsert(memory)

    async def list_memory_ids(self):
        self.list_started.set()
        await self.release_list.wait()
        return set(self.documents)


def _memory(user_id=1, *, text="dislikes cilantro", revision=1):
    return UserMemory(
        user_id=user_id,
        memory_type="preference",
        memory_key="diet.disliked_food.cilantro",
        content_json='{"value":"cilantro"}',
        content_text=text,
        content_fingerprint=f"fingerprint-{user_id}-{revision}",
        index_revision=revision,
        confirmation_status="confirmed",
        sensitivity="normal",
        confidence=1,
        active_slot="active",
        created_by="user",
    )


class MemoryIndexOutboxTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        path = Path(self.temp_dir.name) / "memory-index.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.settings = SimpleNamespace(
            MEMORY_VECTOR_ENABLED=True,
            MEMORY_INDEX_MAX_ATTEMPTS=3,
            MEMORY_INDEX_RETRY_BASE_SECONDS=1,
            MEMORY_INDEX_BATCH_SIZE=20,
        )

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def _insert_job(self, memory, operation="upsert"):
        async with self.sessions() as db:
            db.add(memory)
            await db.flush()
            db.add(
                UserMemoryIndexOutbox(
                    memory_id=memory.id,
                    user_id=memory.user_id,
                    operation=operation,
                    index_revision=memory.index_revision,
                )
            )
            await db.commit()
            return memory.id

    async def test_retry_keeps_sql_and_event_then_idempotently_upserts(self):
        memory_id = await self._insert_job(_memory())
        backend = FakeVectorBackend(fail_upserts=1)
        with patch(
            "app.services.memory_index_service.get_settings",
            return_value=self.settings,
        ):
            first = await process_memory_index_outbox(
                vector_backend=backend,
                session_factory=self.sessions,
            )
            async with self.sessions() as db:
                job = (await db.execute(select(UserMemoryIndexOutbox))).scalar_one()
                job.available_at = datetime.utcnow() - timedelta(seconds=1)
                await db.commit()
            second = await process_memory_index_outbox(
                vector_backend=backend,
                session_factory=self.sessions,
            )

        self.assertEqual(first["failed"], 1)
        self.assertEqual(second["completed"], 1)
        self.assertIn(memory_id, backend.documents)
        async with self.sessions() as db:
            self.assertIsNotNone(await db.get(UserMemory, memory_id))
            job = (await db.execute(select(UserMemoryIndexOutbox))).scalar_one()
            self.assertEqual(job.status, "completed")
            self.assertIsNone(job.last_error_code)

    async def test_startup_maintenance_backfills_legacy_memory_without_outbox_once(self):
        async with self.sessions() as db:
            legacy = _memory(revision=0)
            db.add(legacy)
            await db.commit()
            memory_id = legacy.id

        backend = FakeVectorBackend()
        with patch(
            "app.services.memory_index_service.get_settings",
            return_value=self.settings,
        ):
            first = await run_memory_index_maintenance(
                self.sessions,
                vector_backend=backend,
            )
            second = await run_memory_index_maintenance(
                self.sessions,
                vector_backend=backend,
            )

        self.assertEqual(first["completed"], 1)
        self.assertEqual(second["processed"], 0)
        self.assertIn(memory_id, backend.documents)
        async with self.sessions() as db:
            jobs = list((await db.execute(select(UserMemoryIndexOutbox))).scalars())
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].index_revision, 0)

    async def test_new_collection_replays_completed_current_revision_once(self):
        memory_id = await self._insert_job(_memory())
        async with self.sessions() as db:
            job = (await db.execute(select(UserMemoryIndexOutbox))).scalar_one()
            job.status = "completed"
            job.processed_at = datetime.utcnow()
            await db.commit()

        backend = FakeVectorBackend(initialized=False)
        with patch(
            "app.services.memory_index_service.get_settings",
            return_value=self.settings,
        ):
            first = await run_memory_index_maintenance(
                self.sessions,
                vector_backend=backend,
            )
            second = await run_memory_index_maintenance(
                self.sessions,
                vector_backend=backend,
            )

        self.assertEqual(first["completed"], 1)
        self.assertEqual(second["processed"], 0)
        self.assertEqual(backend.upsert_calls, 1)
        self.assertIn(memory_id, backend.documents)

    async def test_edit_invalidates_old_revision_and_keyword_truth_is_immediate(self):
        memory_id = await self._insert_job(_memory())
        async with self.sessions() as db:
            edited = await update_user_memory(
                db,
                memory_id,
                1,
                content={"value": "celery"},
                content_text="dislikes celery",
            )
            jobs = list(
                (await db.execute(select(UserMemoryIndexOutbox).order_by(UserMemoryIndexOutbox.id))).scalars()
            )

        self.assertEqual(edited.content_text, "dislikes celery")
        self.assertEqual(edited.index_revision, 2)
        self.assertEqual([job.index_revision for job in jobs], [1, 2])

        backend = FakeVectorBackend()
        with patch(
            "app.services.memory_index_service.get_settings",
            return_value=self.settings,
        ):
            stats = await process_memory_index_outbox(
                vector_backend=backend,
                session_factory=self.sessions,
            )
        self.assertEqual(stats["obsolete"], 1)
        self.assertEqual(backend.documents[memory_id][1], 2)

    async def test_delete_is_sql_immediate_and_vector_event_is_durable(self):
        memory_id = await self._insert_job(_memory())
        async with self.sessions() as db:
            deleted = await delete_user_memory(db, memory_id, 1)
            memory = await db.get(UserMemory, memory_id)
            jobs = list((await db.execute(select(UserMemoryIndexOutbox))).scalars())

        self.assertTrue(deleted)
        self.assertIsNotNone(memory.deleted_at)
        self.assertEqual(memory.index_revision, 2)
        self.assertEqual([(job.operation, job.index_revision) for job in jobs], [("upsert", 1), ("delete", 2)])

    async def test_scoped_rebuild_does_not_delete_other_users(self):
        backend = FakeVectorBackend()
        backend.documents[999] = (2, 1, "other-user")
        async with self.sessions() as db:
            memory = _memory(user_id=1)
            db.add(memory)
            await db.commit()
            result = await rebuild_memory_index(
                db,
                vector_backend=backend,
                user_id=1,
            )

        self.assertEqual(result, {"indexed": 1, "orphans_deleted": 0})
        self.assertIn(999, backend.documents)
        self.assertIn(memory.id, backend.documents)

    async def test_rebuild_serializes_writes_and_rechecks_orphans_against_sql(self):
        backend = BlockingListBackend()
        concurrent_memory = _memory(user_id=2)
        concurrent_memory.id = 200
        backend.documents[200] = (2, 1, concurrent_memory.content_fingerprint)

        async with self.sessions() as rebuild_db:
            rebuild_task = asyncio.create_task(
                rebuild_memory_index(rebuild_db, vector_backend=backend)
            )
            await backend.list_started.wait()

            async with self.sessions() as write_db:
                write_db.add(concurrent_memory)
                await write_db.commit()
                write_db.add(
                    UserMemoryIndexOutbox(
                        memory_id=concurrent_memory.id,
                        user_id=concurrent_memory.user_id,
                        operation="upsert",
                        index_revision=concurrent_memory.index_revision,
                    )
                )
                await write_db.commit()

            with patch(
                "app.services.memory_index_service.get_settings",
                return_value=self.settings,
            ):
                worker_task = asyncio.create_task(
                    process_memory_index_outbox(
                        vector_backend=backend,
                        session_factory=self.sessions,
                        batch_size=1,
                    )
                )
                for _ in range(20):
                    async with self.sessions() as status_db:
                        status = (
                            await status_db.execute(
                                select(UserMemoryIndexOutbox.status)
                            )
                        ).scalar_one()
                    if status == "processing":
                        break
                    await asyncio.sleep(0)

                self.assertEqual(status, "processing")
                self.assertFalse(backend.upsert_started.is_set())
                backend.release_list.set()
                rebuild_result, _ = await asyncio.gather(
                    rebuild_task,
                    worker_task,
                )

        self.assertEqual(rebuild_result["orphans_deleted"], 0)
        self.assertIn(concurrent_memory.id, backend.documents)

    async def test_concurrent_workers_cannot_leave_an_old_revision_last(self):
        memory_id = await self._insert_job(_memory())
        backend = BlockingFirstUpsertBackend()
        with patch(
            "app.services.memory_index_service.get_settings",
            return_value=self.settings,
        ):
            old_worker = asyncio.create_task(
                process_memory_index_outbox(
                    vector_backend=backend,
                    session_factory=self.sessions,
                    batch_size=2,
                )
            )
            await backend.first_started.wait()
            async with self.sessions() as db:
                edited = await update_user_memory(
                    db,
                    memory_id,
                    1,
                    content={"value": "celery"},
                    content_text="dislikes celery",
                )
            new_worker = asyncio.create_task(
                process_memory_index_outbox(
                    vector_backend=backend,
                    session_factory=self.sessions,
                    batch_size=1,
                )
            )
            await asyncio.sleep(0)
            backend.release_first.set()
            await asyncio.gather(old_worker, new_worker)

        self.assertEqual(backend.documents[memory_id][1], edited.index_revision)
        self.assertEqual(backend.documents[memory_id][2], edited.content_fingerprint)


if __name__ == "__main__":
    unittest.main()
