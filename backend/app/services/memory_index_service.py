"""Durable synchronization between governed SQLite memories and Chroma."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import exists, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import get_settings
from app.core.database import async_session
from app.memory.vectorstore import ChromaMemoryVectorStore, MemoryVectorBackend
from app.models.user import UserMemory, UserMemoryIndexOutbox
from app.services.user_memory_service import _queue_index_event, active_memory_filters

logger = logging.getLogger(__name__)
_VECTOR_WRITE_LOCK = asyncio.Lock()


def memory_is_indexable(memory: UserMemory | None, now: datetime | None = None) -> bool:
    effective_now = now or datetime.utcnow()
    return bool(
        memory is not None
        and memory.confirmation_status == "confirmed"
        and memory.deleted_at is None
        and memory.valid_from <= effective_now
        and (memory.valid_until is None or memory.valid_until > effective_now)
    )


async def enqueue_expired_memory_deletes(db: AsyncSession) -> int:
    """Turn natural time expiry into durable delete work; SQL remains protective meanwhile."""
    now = datetime.utcnow()
    existing_delete = aliased(UserMemoryIndexOutbox)
    expired = list(
        (
            await db.execute(
                select(UserMemory).where(
                    UserMemory.confirmation_status == "confirmed",
                    UserMemory.deleted_at.is_(None),
                    UserMemory.valid_until.is_not(None),
                    UserMemory.valid_until <= now,
                    ~exists(
                        select(existing_delete.id).where(
                            existing_delete.memory_id == UserMemory.id,
                            existing_delete.index_revision
                            == UserMemory.index_revision,
                            existing_delete.operation == "delete",
                        )
                    ),
                )
            )
        ).scalars()
    )
    for memory in expired:
        memory.active_slot = None
        memory.updated_at = now
        _queue_index_event(db, memory, "delete")
    if expired:
        await db.commit()
    return len(expired)


async def enqueue_missing_memory_upserts(
    db: AsyncSession,
    *,
    indexed_memory_ids: set[int] | None = None,
    indexed_memory_revisions: dict[int, tuple[int, str]] | None = None,
) -> int:
    """Backfill active SQL memories missing either outbox work or vector documents."""
    now = datetime.utcnow()
    existing_job = aliased(UserMemoryIndexOutbox)
    filters: list[Any] = [
        UserMemory.confirmation_status == "confirmed",
        UserMemory.deleted_at.is_(None),
        UserMemory.valid_from <= now,
        or_(
            UserMemory.valid_until.is_(None),
            UserMemory.valid_until > now,
        ),
    ]
    if indexed_memory_ids is None:
        filters.append(
            ~exists(
                select(existing_job.id).where(
                    existing_job.memory_id == UserMemory.id,
                    existing_job.index_revision == UserMemory.index_revision,
                )
            )
        )
    elif indexed_memory_revisions is None and indexed_memory_ids:
        filters.append(UserMemory.id.not_in(indexed_memory_ids))

    missing = list(
        (
            await db.execute(
                select(
                    UserMemory.id,
                    UserMemory.user_id,
                    UserMemory.index_revision,
                    UserMemory.content_fingerprint,
                )
                .where(*filters)
            )
        ).all()
    )
    enqueued = 0
    for memory_id, user_id, index_revision, content_fingerprint in missing:
        revision = int(index_revision or 0)
        if indexed_memory_revisions is not None:
            indexed_revision = indexed_memory_revisions.get(memory_id)
            if indexed_revision == (revision, str(content_fingerprint)):
                continue
        if indexed_memory_ids is not None:
            # A completed event is not proof that the collection still contains
            # its document (manual deletion/corruption/model migration). Replay
            # exactly that revision without creating a duplicate outbox row.
            replay = await db.execute(
                update(UserMemoryIndexOutbox)
                .where(
                    UserMemoryIndexOutbox.memory_id == memory_id,
                    UserMemoryIndexOutbox.index_revision == revision,
                    UserMemoryIndexOutbox.status == "completed",
                )
                .values(
                    operation="upsert",
                    status="pending",
                    attempts=0,
                    available_at=now,
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error_code=None,
                    processed_at=None,
                )
            )
            if replay.rowcount:
                enqueued += int(replay.rowcount)
                continue
        result = await db.execute(
            sqlite_insert(UserMemoryIndexOutbox)
            .values(
                memory_id=memory_id,
                user_id=user_id,
                operation="upsert",
                index_revision=revision,
                status="pending",
                attempts=0,
                available_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=["memory_id", "index_revision"]
            )
        )
        enqueued += max(0, int(result.rowcount or 0))
    if enqueued:
        await db.commit()
    return enqueued


async def replay_active_memory_upserts(db: AsyncSession) -> int:
    """Requeue active revisions when the configured collection is new/missing."""
    now = datetime.utcnow()
    active_rows = list(
        (
            await db.execute(
                select(UserMemory.id, UserMemory.index_revision).where(
                    UserMemory.confirmation_status == "confirmed",
                    UserMemory.deleted_at.is_(None),
                    UserMemory.valid_from <= now,
                    or_(
                        UserMemory.valid_until.is_(None),
                        UserMemory.valid_until > now,
                    ),
                )
            )
        ).all()
    )
    replayed = 0
    for memory_id, index_revision in active_rows:
        result = await db.execute(
            update(UserMemoryIndexOutbox)
            .where(
                UserMemoryIndexOutbox.memory_id == memory_id,
                UserMemoryIndexOutbox.index_revision == int(index_revision or 0),
                UserMemoryIndexOutbox.status.in_(("completed", "failed")),
            )
            .values(
                operation="upsert",
                status="pending",
                attempts=0,
                available_at=now,
                lease_owner=None,
                lease_expires_at=None,
                last_error_code=None,
                processed_at=None,
            )
        )
        replayed += max(0, int(result.rowcount or 0))
    if replayed:
        await db.commit()
    return replayed


async def _claim_one(db: AsyncSession, worker_id: str) -> int | None:
    settings = get_settings()
    now = datetime.utcnow()
    active_job = aliased(UserMemoryIndexOutbox)
    same_memory_is_processing = exists(
        select(active_job.id).where(
            active_job.memory_id == UserMemoryIndexOutbox.memory_id,
            active_job.id != UserMemoryIndexOutbox.id,
            active_job.status == "processing",
            active_job.lease_expires_at >= now,
        )
    )
    candidate_id = (
        await db.execute(
            select(UserMemoryIndexOutbox.id)
            .where(
                UserMemoryIndexOutbox.attempts < settings.MEMORY_INDEX_MAX_ATTEMPTS,
                UserMemoryIndexOutbox.available_at <= now,
                or_(
                    UserMemoryIndexOutbox.status == "pending",
                    (
                        (UserMemoryIndexOutbox.status == "processing")
                        & (UserMemoryIndexOutbox.lease_expires_at < now)
                    ),
                ),
                ~same_memory_is_processing,
            )
            .order_by(UserMemoryIndexOutbox.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if candidate_id is None:
        return None
    result = await db.execute(
        update(UserMemoryIndexOutbox)
        .where(
            UserMemoryIndexOutbox.id == candidate_id,
            or_(
                UserMemoryIndexOutbox.status == "pending",
                (
                    (UserMemoryIndexOutbox.status == "processing")
                    & (UserMemoryIndexOutbox.lease_expires_at < now)
                ),
            ),
        )
        .values(
            status="processing",
            lease_owner=worker_id,
            lease_expires_at=now + timedelta(minutes=2),
        )
    )
    await db.commit()
    return candidate_id if result.rowcount == 1 else None


async def process_memory_index_outbox(
    *,
    vector_backend: MemoryVectorBackend | None = None,
    session_factory: Any = async_session,
    batch_size: int | None = None,
) -> dict[str, int]:
    """Process a bounded batch. Failures stay content-free and retryable."""
    settings = get_settings()
    owns_backend = vector_backend is None
    backend = vector_backend or ChromaMemoryVectorStore()
    worker_id = str(uuid.uuid4())
    stats = {"processed": 0, "completed": 0, "failed": 0, "obsolete": 0}
    try:
        for _ in range(batch_size or settings.MEMORY_INDEX_BATCH_SIZE):
            async with session_factory() as claim_db:
                job_id = await _claim_one(claim_db, worker_id)
            if job_id is None:
                break
            stats["processed"] += 1
            async with session_factory() as db:
                job = await db.get(UserMemoryIndexOutbox, job_id)
                if job is None or job.lease_owner != worker_id:
                    continue
                try:
                    async with _VECTOR_WRITE_LOCK:
                        # Another worker may have embedded a newer revision while
                        # this job waited. Re-read inside the write critical section
                        # so an old completion can never overwrite a newer vector.
                        memory = await db.get(UserMemory, job.memory_id)
                        if memory is not None:
                            await db.refresh(memory)
                        if (
                            memory is not None
                            and int(memory.index_revision or 0) > job.index_revision
                        ):
                            job.status = "completed"
                            job.processed_at = datetime.utcnow()
                            job.last_error_code = "obsolete_revision"
                            stats["obsolete"] += 1
                        else:
                            should_upsert = (
                                job.operation == "upsert"
                                and memory_is_indexable(memory)
                                and int(memory.index_revision or 0)
                                == job.index_revision
                            )
                            if should_upsert:
                                await backend.upsert(memory)
                            else:
                                await backend.delete(job.memory_id)

                            # A vector call can outlive its DB lease. If another
                            # process advances the memory while this worker is in
                            # external I/O, reconcile to the newest SQL authority so
                            # a late stale write can never be the final document.
                            current = await db.get(UserMemory, job.memory_id)
                            if current is not None:
                                await db.refresh(current)
                            if (
                                current is not None
                                and int(current.index_revision or 0)
                                > job.index_revision
                            ):
                                if memory_is_indexable(current):
                                    await backend.upsert(current)
                                else:
                                    await backend.delete(job.memory_id)
                                job.last_error_code = "obsolete_after_write"
                                stats["obsolete"] += 1
                            else:
                                job.last_error_code = None
                                stats["completed"] += 1
                            job.status = "completed"
                            job.processed_at = datetime.utcnow()
                    job.lease_owner = None
                    job.lease_expires_at = None
                    await db.commit()
                except Exception as exc:
                    job.attempts += 1
                    job.lease_owner = None
                    job.lease_expires_at = None
                    job.last_error_code = type(exc).__name__[:80]
                    if job.attempts >= settings.MEMORY_INDEX_MAX_ATTEMPTS:
                        job.status = "failed"
                    else:
                        job.status = "pending"
                        delay = settings.MEMORY_INDEX_RETRY_BASE_SECONDS * (
                            2 ** (job.attempts - 1)
                        )
                        job.available_at = datetime.utcnow() + timedelta(seconds=delay)
                    await db.commit()
                    stats["failed"] += 1
                    logger.warning(
                        "Memory index job failed",
                        extra={"job_id": job.id, "error_type": type(exc).__name__},
                    )
        return stats
    finally:
        close = getattr(backend, "close", None)
        if owns_backend and callable(close):
            await close()


async def rebuild_memory_index(
    db: AsyncSession,
    *,
    vector_backend: MemoryVectorBackend,
    user_id: int | None = None,
) -> dict[str, int]:
    """Idempotently upsert all SQL-active memories then remove orphan IDs."""
    async with _VECTOR_WRITE_LOCK:
        now = datetime.utcnow()
        stmt = select(UserMemory).where(
            UserMemory.confirmation_status == "confirmed",
            UserMemory.deleted_at.is_(None),
            UserMemory.valid_from <= now,
            or_(UserMemory.valid_until.is_(None), UserMemory.valid_until > now),
        )
        if user_id is not None:
            stmt = stmt.where(UserMemory.user_id == user_id)
        active = list((await db.execute(stmt)).scalars())
        for memory in active:
            await vector_backend.upsert(memory)
        active_ids = {memory.id for memory in active}
        # A global ID listing cannot safely identify another user's records as
        # orphans during a scoped rebuild. Cleanup therefore runs only globally.
        orphan_ids = (
            await vector_backend.list_memory_ids() - active_ids
            if user_id is None
            else set()
        )
        orphans_deleted = 0
        for memory_id in sorted(orphan_ids):
            # SQL can change while the rebuild awaits vector I/O. Re-read the
            # source of truth immediately before deletion so a newly confirmed
            # memory is retained and brought to the current revision instead.
            memory = await db.get(UserMemory, memory_id)
            if memory is not None:
                await db.refresh(memory)
            if memory_is_indexable(memory):
                await vector_backend.upsert(memory)
                continue
            await vector_backend.delete(memory_id)
            orphans_deleted += 1
        return {"indexed": len(active), "orphans_deleted": orphans_deleted}


async def run_memory_index_maintenance(
    session_factory: Any = async_session,
    *,
    vector_backend: MemoryVectorBackend | None = None,
) -> dict[str, int]:
    """Best-effort entry point for startup and response background tasks."""
    settings = get_settings()
    if not settings.MEMORY_VECTOR_ENABLED:
        return {
            "processed": 0,
            "completed": 0,
            "failed": 0,
            "obsolete": 0,
            "collections_deleted": 0,
        }
    owns_backend = vector_backend is None
    backend = vector_backend or ChromaMemoryVectorStore()
    collection_exists = await backend.collection_exists()
    revision_lister = getattr(backend, "list_memory_revisions", None)
    indexed_memory_revisions = (
        await revision_lister()
        if collection_exists and callable(revision_lister)
        else None
    )
    indexed_memory_ids = (
        set(indexed_memory_revisions)
        if indexed_memory_revisions is not None
        else await backend.list_memory_ids() if collection_exists else None
    )
    async with session_factory() as db:
        await enqueue_expired_memory_deletes(db)
        await enqueue_missing_memory_upserts(
            db,
            indexed_memory_ids=indexed_memory_ids,
            indexed_memory_revisions=indexed_memory_revisions,
        )
        if not collection_exists:
            await replay_active_memory_upserts(db)
    stats = await process_memory_index_outbox(
        vector_backend=backend,
        session_factory=session_factory,
    )
    stats["collections_deleted"] = 0

    cleanup = getattr(backend, "cleanup_obsolete_collections", None)
    if (
        getattr(settings, "MEMORY_CLEANUP_OBSOLETE_COLLECTIONS", False)
        and callable(cleanup)
        and await backend.collection_exists()
    ):
        current_ids = await backend.list_memory_ids()
        async with session_factory() as db:
            now = datetime.utcnow()
            active_ids = set(
                (
                    await db.execute(
                        select(UserMemory.id).where(
                            UserMemory.confirmation_status == "confirmed",
                            UserMemory.deleted_at.is_(None),
                            UserMemory.valid_from <= now,
                            or_(
                                UserMemory.valid_until.is_(None),
                                UserMemory.valid_until > now,
                            ),
                        )
                    )
                ).scalars()
            )
        # Old collections are removed only after the current collection fully
        # covers SQL authority; partial migrations keep the previous fallback.
        if active_ids.issubset(current_ids):
            stats["collections_deleted"] = int(await cleanup())
    close = getattr(backend, "close", None)
    if owns_backend and callable(close):
        await close()
    return stats


async def memory_index_maintenance_worker(
    *,
    stop_event: asyncio.Event | None = None,
    vector_backend: MemoryVectorBackend | None = None,
    session_factory: Any = async_session,
    interval_seconds: float | None = None,
    close_backend: bool = True,
) -> None:
    """Continuously drain durable index work and wake for due retries.

    Outbox claims use SQLite atomic updates plus leases, so multiple processes can
    run this worker without treating the in-process vector lock as correctness.
    """
    settings = get_settings()
    backend = vector_backend or ChromaMemoryVectorStore()
    interval = interval_seconds or getattr(
        settings, "MEMORY_INDEX_MAINTENANCE_INTERVAL_SECONDS", 5.0
    )
    if interval <= 0:
        raise ValueError("interval_seconds must be positive")
    try:
        while stop_event is None or not stop_event.is_set():
            try:
                stats = await run_memory_index_maintenance(
                    session_factory,
                    vector_backend=backend,
                )
                # A full batch may mean more immediately claimable work exists;
                # drain it before entering the periodic wait.
                if stats["processed"] >= settings.MEMORY_INDEX_BATCH_SIZE:
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Memory index maintenance cycle failed",
                    extra={"error_type": type(exc).__name__},
                )
            if stop_event is None:
                await asyncio.sleep(interval)
                continue
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
    finally:
        close = getattr(backend, "close", None)
        if close_backend and callable(close):
            await close()
