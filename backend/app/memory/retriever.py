"""Governed keyword/vector/RRF retrieval over long-term user memories."""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from datetime import datetime
from typing import cast

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.memory.types import (
    MemoryRecallHit,
    MemoryRecallResult,
    MemoryRetrievalChannel,
    MemoryRetrievalMode,
    MemoryVectorMatch,
)
from app.memory.vectorstore import (
    ChromaMemoryVectorStore,
    MemoryVectorBackend,
    MemoryVectorUnavailable,
)
from app.models.user import UserMemory
from app.services.user_memory_service import _relevance_score, active_memory_filters

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)


def _tokens(text: str) -> list[str]:
    result: list[str] = []
    for token in _TOKEN_RE.findall(text.lower()):
        if "\u4e00" <= token[0] <= "\u9fff" and len(token) > 1:
            result.extend(token[index:index + 2] for index in range(len(token) - 1))
        result.append(token)
    return result


def _keyword_ranks(
    memories: list[UserMemory], query: str, *, limit: int
) -> list[tuple[UserMemory, float]]:
    query_tokens = _tokens(query)
    if not memories or not query_tokens or limit <= 0:
        return []
    frequencies: list[Counter[str]] = []
    document_frequency: Counter[str] = Counter()
    total_length = 0
    for memory in memories:
        terms = _tokens(
            f"{memory.memory_type} {memory.memory_key} {memory.content_text}"
        )
        frequency = Counter(terms)
        frequencies.append(frequency)
        total_length += len(terms)
        document_frequency.update(frequency.keys())
    average_length = max(total_length / len(memories), 1.0)
    scores: list[tuple[UserMemory, float]] = []
    for memory, frequency in zip(memories, frequencies, strict=True):
        document_length = max(sum(frequency.values()), 1)
        score = 0.0
        for token in query_tokens:
            term_frequency = frequency.get(token, 0)
            if not term_frequency:
                continue
            inverse_frequency = math.log(
                (len(memories) - document_frequency[token] + 0.5)
                / (document_frequency[token] + 0.5)
                + 1
            )
            score += inverse_frequency * (
                term_frequency * 2.5
                / (
                    term_frequency
                    + 1.5 * (0.25 + 0.75 * document_length / average_length)
                )
            )
        # Preserve the established business cues (memory type and key domain)
        # as a bounded rerank signal alongside BM25 lexical relevance.
        business_score = float(_relevance_score(memory, query)[0])
        if memory.sensitivity == "health_sensitive":
            # Safety priority is applied separately with health_limit; do not
            # let the legacy +8 health bonus bypass that explicit cap.
            business_score = max(0.0, business_score - 8.0)
        combined_score = score + min(business_score, 12.0) / 10.0
        if combined_score > 0:
            scores.append((memory, combined_score))
    scores.sort(
        key=lambda item: (
            item[1],
            item[0].updated_at or item[0].created_at,
            item[0].id,
        ),
        reverse=True,
    )
    return scores[:limit]


class MemoryRetriever:
    """Hybrid retriever with SQL lifecycle validation as the final authority."""

    def __init__(
        self,
        vector_backend: MemoryVectorBackend | None = None,
        *,
        rrf_k: int | None = None,
        candidate_limit: int | None = None,
        health_limit: int | None = None,
    ) -> None:
        settings = get_settings()
        self.vector_backend = vector_backend or ChromaMemoryVectorStore()
        self.rrf_k = rrf_k or settings.MEMORY_RRF_K
        self.keyword_candidate_limit = (
            candidate_limit or settings.MEMORY_KEYWORD_CANDIDATE_LIMIT
        )
        self.vector_candidate_limit = settings.MEMORY_VECTOR_CANDIDATE_LIMIT
        self.vector_enabled = settings.MEMORY_VECTOR_ENABLED
        self.health_limit = health_limit or settings.MEMORY_HEALTH_RECALL_LIMIT
        if self.rrf_k <= 0:
            raise ValueError("rrf_k must be positive")
        if (
            self.keyword_candidate_limit <= 0
            or self.vector_candidate_limit <= 0
            or self.health_limit <= 0
        ):
            raise ValueError("candidate and health limits must be positive")

    @staticmethod
    def _eligible_filters(user_id: int, now: datetime):
        return active_memory_filters(user_id, now)

    async def _eligible_candidates(
        self,
        db: AsyncSession,
        user_id: int,
        now: datetime,
        query: str,
    ) -> list[UserMemory]:
        base_filters = self._eligible_filters(user_id, now)
        # A recency-only LIMIT made an old but exact preference invisible before
        # BM25 ever got a chance to rank it. Fetch a bounded lexical/domain pool
        # first, then add recent rows as a fallback for cue-based ranking.
        search_tokens = list(dict.fromkeys(_tokens(query)))[:16]
        lexical_predicates = [
            predicate
            for token in search_tokens
            for predicate in (
                UserMemory.memory_key.contains(token),
                UserMemory.content_text.contains(token),
            )
        ]
        query_lower = query.lower()
        domain_prefixes: list[str] = []
        if any(cue in query_lower for cue in ("吃", "饮食", "餐", "食物", "营养")):
            domain_prefixes.append("diet.")
        if any(cue in query_lower for cue in ("训练", "运动", "健身", "力量", "有氧")):
            domain_prefixes.append("training.")
        if any(cue in query_lower for cue in ("目标", "计划", "减脂", "增肌", "体重")):
            domain_prefixes.append("goal.")
        lexical_predicates.extend(
            UserMemory.memory_key.startswith(prefix) for prefix in domain_prefixes
        )

        candidates: dict[int, UserMemory] = {}
        if lexical_predicates:
            lexical_statement = (
                select(UserMemory)
                .where(*base_filters, or_(*lexical_predicates))
                .order_by(desc(UserMemory.updated_at), desc(UserMemory.id))
                .limit(self.keyword_candidate_limit)
            )
            for memory in (await db.execute(lexical_statement)).scalars().all():
                candidates[memory.id] = memory

        recent_statement = (
            select(UserMemory)
            .where(*base_filters)
            .order_by(desc(UserMemory.updated_at), desc(UserMemory.id))
            .limit(self.keyword_candidate_limit)
        )
        for memory in (await db.execute(recent_statement)).scalars().all():
            candidates.setdefault(memory.id, memory)
        return list(candidates.values())

    async def _eligible_health(
        self, db: AsyncSession, user_id: int, now: datetime
    ) -> list[UserMemory]:
        statement = (
            select(UserMemory)
            .where(
                *self._eligible_filters(user_id, now),
                UserMemory.sensitivity == "health_sensitive",
            )
            .order_by(desc(UserMemory.updated_at), desc(UserMemory.id))
            .limit(self.health_limit)
        )
        return list((await db.execute(statement)).scalars().all())

    async def _validate_vector_matches(
        self,
        db: AsyncSession,
        user_id: int,
        matches: list[MemoryVectorMatch],
        now: datetime,
    ) -> tuple[list[tuple[UserMemory, MemoryVectorMatch]], int]:
        ids = list(dict.fromkeys(match.memory_id for match in matches))
        if not ids:
            return [], 0
        statement = select(UserMemory).where(
            UserMemory.id.in_(ids),
            *self._eligible_filters(user_id, now),
        )
        memories = {
            memory.id: memory
            for memory in (await db.execute(statement)).scalars().all()
        }
        valid: list[tuple[UserMemory, MemoryVectorMatch]] = []
        stale = 0
        for match in matches:
            memory = memories.get(match.memory_id)
            current_revision = int(getattr(memory, "index_revision", 0) or 0) if memory else -1
            if (
                memory is None
                or match.content_fingerprint != memory.content_fingerprint
                or match.index_revision != current_revision
            ):
                stale += 1
                continue
            valid.append((memory, match))
        return valid, stale

    async def retrieve(
        self,
        db: AsyncSession,
        user_id: int,
        query: str,
        *,
        mode: MemoryRetrievalMode | None = None,
        limit: int | None = None,
    ) -> MemoryRecallResult:
        mode = mode or cast(
            MemoryRetrievalMode, get_settings().MEMORY_RETRIEVAL_MODE
        )
        if mode not in ("keyword", "vector", "hybrid"):
            raise ValueError(f"unsupported memory retrieval mode: {mode}")
        recall_limit = limit or get_settings().CHAT_MEMORY_RECALL_LIMIT
        if recall_limit <= 0:
            raise ValueError("limit must be positive")

        now = datetime.utcnow()
        eligible = await self._eligible_candidates(db, user_id, now, query)
        by_id = {memory.id: memory for memory in eligible}
        keyword = (
            _keyword_ranks(eligible, query, limit=self.keyword_candidate_limit)
            if mode in ("keyword", "hybrid")
            else []
        )

        degraded = False
        degradation_reason: str | None = None
        effective_mode = mode
        raw_vectors: list[MemoryVectorMatch] = []
        vectors: list[tuple[UserMemory, MemoryVectorMatch]] = []
        stale_count = 0
        if mode in ("vector", "hybrid") and not self.vector_enabled:
            degraded = True
            degradation_reason = "vector_disabled"
            effective_mode = "keyword"
            keyword = _keyword_ranks(
                eligible, query, limit=self.keyword_candidate_limit
            )
        elif mode in ("vector", "hybrid"):
            try:
                raw_vectors = await self.vector_backend.search(
                    query, user_id=user_id, limit=self.vector_candidate_limit
                )
                vectors, stale_count = await self._validate_vector_matches(
                    db, user_id, raw_vectors, now
                )
            except Exception as exc:
                logger.warning(
                    "Memory vector retrieval failed; degrading to keyword",
                    extra={"user_id": user_id, "error_type": type(exc).__name__},
                )
                degraded = True
                degradation_reason = (
                    "vector_index_unavailable"
                    if isinstance(exc, MemoryVectorUnavailable)
                    else "vector_backend_unavailable"
                )
                effective_mode = "keyword"
                keyword = _keyword_ranks(
                    eligible, query, limit=self.keyword_candidate_limit
                )

        keyword_rank = {memory.id: rank for rank, (memory, _) in enumerate(keyword, 1)}
        vector_rank: dict[int, int] = {}
        for rank, (memory, _) in enumerate(vectors, 1):
            vector_rank.setdefault(memory.id, rank)
        candidate_ids = set(keyword_rank) | set(vector_rank)

        # Health-sensitive constraints are safety-injected in a bounded way,
        # independently of lexical/semantic recall quality.
        health = await self._eligible_health(db, user_id, now)
        by_id.update((memory.id, memory) for memory in health)
        safety_ids = {memory.id for memory in health}
        candidate_ids |= safety_ids

        scored: list[tuple[UserMemory, tuple[MemoryRetrievalChannel, ...], float, float]] = []
        for memory_id in candidate_ids:
            memory = by_id.get(memory_id)
            if memory is None:
                # A vector candidate may be outside the keyword candidate window,
                # but validated vector rows are still SQL-authoritative.
                memory = next(
                    (item for item, _ in vectors if item.id == memory_id), None
                )
            if memory is None:
                continue
            channels: list[MemoryRetrievalChannel] = []
            fusion_score = 0.0
            if memory_id in keyword_rank:
                channels.append("keyword")
                fusion_score += 1 / (self.rrf_k + keyword_rank[memory_id])
            if memory_id in vector_rank:
                channels.append("vector")
                fusion_score += 1 / (self.rrf_k + vector_rank[memory_id])
            safety_bonus = 0.0
            if memory_id in safety_ids:
                channels.append("safety")
                safety_bonus = 1.0
            scored.append(
                (memory, tuple(channels), fusion_score, fusion_score + safety_bonus)
            )

        scored.sort(
            key=lambda item: (
                item[3],
                item[0].updated_at or item[0].created_at,
                item[0].id,
            ),
            reverse=True,
        )
        hits = tuple(
            MemoryRecallHit(
                memory=memory,
                channels=channels,
                keyword_rank=keyword_rank.get(memory.id),
                vector_rank=vector_rank.get(memory.id),
                fusion_score=fusion_score,
                final_score=final_score,
                final_rank=rank,
            )
            for rank, (memory, channels, fusion_score, final_score) in enumerate(
                scored[:recall_limit], 1
            )
        )
        return MemoryRecallResult(
            hits=hits,
            requested_mode=mode,
            effective_mode=effective_mode,
            degraded=degraded,
            degradation_reason=degradation_reason,
            keyword_candidate_count=len(keyword),
            vector_candidate_count=len(vector_rank),
            stale_vector_candidate_count=stale_count,
        )
