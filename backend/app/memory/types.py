"""Typed contracts for governed long-term-memory retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.models.user import UserMemory

MemoryRetrievalMode = Literal["keyword", "vector", "hybrid"]
MemoryRetrievalChannel = Literal["keyword", "vector", "safety"]


@dataclass(frozen=True, slots=True)
class MemoryVectorMatch:
    """A vector candidate carrying only identity and revision metadata."""

    memory_id: int
    score: float
    content_fingerprint: str
    index_revision: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MemoryRecallHit:
    """One SQL-validated memory plus retrieval diagnostics."""

    memory: UserMemory
    channels: tuple[MemoryRetrievalChannel, ...]
    keyword_rank: int | None = None
    vector_rank: int | None = None
    fusion_score: float = 0.0
    final_score: float = 0.0
    final_rank: int = 0


@dataclass(frozen=True, slots=True)
class MemoryRecallResult:
    """Recall output with explicit mode and degradation information."""

    hits: tuple[MemoryRecallHit, ...]
    requested_mode: MemoryRetrievalMode
    effective_mode: MemoryRetrievalMode
    degraded: bool = False
    degradation_reason: str | None = None
    keyword_candidate_count: int = 0
    vector_candidate_count: int = 0
    stale_vector_candidate_count: int = 0

    @property
    def memories(self) -> list[UserMemory]:
        return [hit.memory for hit in self.hits]
