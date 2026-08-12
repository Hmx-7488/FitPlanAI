"""Application boundary for memory retrieval and content-free usage telemetry."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.memory.retriever import MemoryRetriever
from app.memory.types import MemoryRecallResult, MemoryRetrievalMode
from app.models.user import UserMemoryRetrievalHit, UserMemoryRetrievalRun

logger = logging.getLogger(__name__)
_MEMORY_RETRIEVER = MemoryRetriever()


def _telemetry_session_factory(db: AsyncSession):
    """Keep telemetry failure and rollback isolated from the business session."""
    return async_sessionmaker(db.bind, expire_on_commit=False)


async def retrieve_user_memory_result(
    db: AsyncSession,
    user_id: int,
    query: str,
    *,
    consumer: str,
    conversation_id: int | None = None,
    source_message_id: int | None = None,
    plan_id: int | None = None,
    mode: MemoryRetrievalMode | None = None,
    limit: int | None = None,
    retriever: MemoryRetriever | None = None,
) -> tuple[MemoryRecallResult, str | None]:
    requested_mode = mode or get_settings().MEMORY_RETRIEVAL_MODE
    result = await (retriever or _MEMORY_RETRIEVER).retrieve(
        db,
        user_id,
        query,
        mode=requested_mode,
        limit=limit,
    )
    run_id = str(uuid.uuid4())
    try:
        async with _telemetry_session_factory(db)() as telemetry_db:
            telemetry_db.add(
                UserMemoryRetrievalRun(
                    id=run_id,
                    user_id=user_id,
                    consumer=consumer,
                    conversation_id=conversation_id,
                    source_message_id=source_message_id,
                    plan_id=plan_id,
                    query_hash=hashlib.sha256(query.encode("utf-8")).hexdigest(),
                    requested_mode=result.requested_mode,
                    effective_mode=result.effective_mode,
                    degraded_reason=result.degradation_reason,
                    keyword_candidate_count=result.keyword_candidate_count,
                    vector_candidate_count=result.vector_candidate_count,
                    stale_filtered_count=result.stale_vector_candidate_count,
                    embedding_model=(
                        get_settings().MEMORY_EMBEDDING_MODEL
                        if "vector"
                        in {result.requested_mode, result.effective_mode}
                        else None
                    ),
                )
            )
            for hit in result.hits:
                telemetry_db.add(
                    UserMemoryRetrievalHit(
                        run_id=run_id,
                        memory_id=hit.memory.id,
                        channels_json=json.dumps(hit.channels),
                        keyword_rank=hit.keyword_rank,
                        vector_rank=hit.vector_rank,
                        fused_rank=hit.final_rank,
                        rrf_score=hit.fusion_score,
                        final_rank=hit.final_rank,
                        included_in_context=False,
                    )
                )
            await telemetry_db.commit()
    except Exception as exc:
        logger.warning(
            "Memory retrieval telemetry write failed",
            extra={"user_id": user_id, "error_type": type(exc).__name__},
        )
        run_id = None
    return result, run_id


async def mark_memory_hits_included(
    db: AsyncSession,
    run_id: str | None,
    memory_ids: list[int],
) -> None:
    """Mark exactly the facts serialized into the model request as used."""
    if not run_id or not memory_ids:
        return
    try:
        async with _telemetry_session_factory(db)() as telemetry_db:
            await telemetry_db.execute(
                update(UserMemoryRetrievalHit)
                .where(
                    UserMemoryRetrievalHit.run_id == run_id,
                    UserMemoryRetrievalHit.memory_id.in_(memory_ids),
                )
                .values(included_in_context=True, included_at=datetime.utcnow())
            )
            await telemetry_db.commit()
    except Exception as exc:
        logger.warning(
            "Memory usage telemetry write failed",
            extra={"run_id": run_id, "error_type": type(exc).__name__},
        )


async def get_memory_retrieval_diagnostics(
    db: AsyncSession,
    run_id: str,
    user_id: int,
) -> tuple[UserMemoryRetrievalRun | None, list[UserMemoryRetrievalHit]]:
    run = (
        await db.execute(
            select(UserMemoryRetrievalRun).where(
                UserMemoryRetrievalRun.id == run_id,
                UserMemoryRetrievalRun.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        return None, []
    hits = list(
        (
            await db.execute(
                select(UserMemoryRetrievalHit)
                .where(UserMemoryRetrievalHit.run_id == run_id)
                .order_by(UserMemoryRetrievalHit.final_rank)
            )
        ).scalars()
    )
    return run, hits
