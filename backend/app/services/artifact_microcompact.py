"""Deterministic microcompaction for RAG and tool-result context artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Sequence

from app.services.token_estimator import estimate_tokens


ArtifactMode = Literal["full", "microcompact", "dropped"]
_IMPORTANT_PATTERN = re.compile(
    r"(?:\d|不应|不得|禁止|避免|风险|危险|过敏|伤病|疼痛|剂量|每天|每周|"
    r"蛋白质|热量|千卡|kcal|kg|公斤|克|毫克|分钟|次数|组数)",
    re.IGNORECASE,
)
_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?；;])|\n+")


@dataclass(frozen=True)
class MicrocompactPolicy:
    full_content_tokens: int = 800
    compact_content_tokens: int = 240

    def __post_init__(self) -> None:
        if self.full_content_tokens <= 0:
            raise ValueError("full_content_tokens must be positive")
        if self.compact_content_tokens <= 0:
            raise ValueError("compact_content_tokens must be positive")
        if self.compact_content_tokens >= self.full_content_tokens:
            raise ValueError(
                "compact_content_tokens must be smaller than full_content_tokens"
            )


@dataclass(frozen=True)
class ArtifactInput:
    original_index: int
    kind: str
    title: str
    content: str
    reference_id: str
    score: float = 0.0

    def __post_init__(self) -> None:
        if self.original_index < 0:
            raise ValueError("original_index cannot be negative")
        if not self.kind.strip():
            raise ValueError("artifact kind is required")
        if not self.reference_id.strip():
            raise ValueError("artifact reference_id is required for traceability")


@dataclass(frozen=True)
class CompactedArtifact:
    original_index: int
    kind: str
    title: str
    reference_id: str
    score: float
    mode: ArtifactMode
    rendered_text: str
    original_tokens: int
    included_tokens: int


@dataclass(frozen=True)
class MicrocompactBatch:
    artifacts: list[CompactedArtifact]

    @property
    def original_tokens(self) -> int:
        return sum(artifact.original_tokens for artifact in self.artifacts)

    @property
    def included_tokens(self) -> int:
        return sum(artifact.included_tokens for artifact in self.artifacts)

    @property
    def saved_tokens(self) -> int:
        return max(0, self.original_tokens - self.included_tokens)

    @property
    def full_count(self) -> int:
        return sum(artifact.mode == "full" for artifact in self.artifacts)

    @property
    def compacted_count(self) -> int:
        return sum(artifact.mode == "microcompact" for artifact in self.artifacts)

    @property
    def dropped_count(self) -> int:
        return sum(artifact.mode == "dropped" for artifact in self.artifacts)


def _message_tokens(text: str) -> int:
    return estimate_tokens(text) + 4


def _truncate_to_tokens(text: str, token_limit: int) -> str:
    if token_limit <= 0:
        return ""
    if estimate_tokens(text) <= token_limit:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if estimate_tokens(text[:middle]) <= token_limit:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip()


def _compact_content(content: str, token_limit: int) -> str:
    normalized = " ".join(content.split())
    if estimate_tokens(normalized) <= token_limit:
        return normalized
    sentences = [
        sentence.strip()
        for sentence in _SENTENCE_BOUNDARY.split(normalized)
        if sentence.strip()
    ]
    if not sentences:
        return _truncate_to_tokens(normalized, token_limit)
    important = [sentence for sentence in sentences if _IMPORTANT_PATTERN.search(sentence)]
    ordered: list[str] = []
    seen: set[str] = set()
    for sentence in [*important, *sentences]:
        if sentence not in seen:
            seen.add(sentence)
            ordered.append(sentence)

    selected: list[str] = []
    for sentence in ordered:
        candidate = " ".join([*selected, sentence])
        if estimate_tokens(candidate) <= token_limit:
            selected.append(sentence)
            continue
        if not selected:
            shortened = _truncate_to_tokens(sentence, token_limit)
            if shortened:
                selected.append(shortened)
        break
    return " ".join(selected) or _truncate_to_tokens(normalized, token_limit)


def _render(artifact: ArtifactInput, content: str, *, compacted: bool) -> str:
    label = "（微压缩摘录，完整内容可由引用追溯）" if compacted else ""
    reference = artifact.reference_id or "未提供引用 ID"
    return (
        f"上下文资料 [{artifact.original_index + 1}] {artifact.title}{label}\n"
        f"类型：{artifact.kind}；引用：{reference}\n{content}"
    )


def microcompact_artifacts(
    artifacts: Sequence[ArtifactInput],
    *,
    budget_tokens: int,
    policy: MicrocompactPolicy | None = None,
) -> MicrocompactBatch:
    """Fit ranked artifacts into a budget, compacting before dropping.

    Input order is treated as relevance order. Every output retains its source
    metadata even when dropped so diagnostics can explain the decision.
    """
    active_policy = policy or MicrocompactPolicy()
    remaining = max(0, budget_tokens)
    outputs: list[CompactedArtifact] = []

    for artifact in artifacts:
        full_text = _render(artifact, artifact.content, compacted=False)
        original_tokens = _message_tokens(full_text)
        content_tokens = estimate_tokens(artifact.content)
        compacted = content_tokens > active_policy.full_content_tokens
        if compacted:
            compact_content = _compact_content(
                artifact.content,
                active_policy.compact_content_tokens,
            )
            candidate = _render(artifact, compact_content, compacted=True)
            mode: ArtifactMode = "microcompact"
        else:
            candidate = full_text
            mode = "full"
        candidate_tokens = _message_tokens(candidate)

        if candidate_tokens > remaining and mode == "full":
            compact_content = _compact_content(
                artifact.content,
                active_policy.compact_content_tokens,
            )
            compact_candidate = _render(artifact, compact_content, compacted=True)
            compact_tokens = _message_tokens(compact_candidate)
            if compact_tokens < candidate_tokens:
                candidate = compact_candidate
                candidate_tokens = compact_tokens
                mode = "microcompact"

        if candidate_tokens > remaining:
            outputs.append(
                CompactedArtifact(
                    original_index=artifact.original_index,
                    kind=artifact.kind,
                    title=artifact.title,
                    reference_id=artifact.reference_id,
                    score=artifact.score,
                    mode="dropped",
                    rendered_text="",
                    original_tokens=original_tokens,
                    included_tokens=0,
                )
            )
            continue

        remaining -= candidate_tokens
        outputs.append(
            CompactedArtifact(
                original_index=artifact.original_index,
                kind=artifact.kind,
                title=artifact.title,
                reference_id=artifact.reference_id,
                score=artifact.score,
                mode=mode,
                rendered_text=candidate,
                original_tokens=original_tokens,
                included_tokens=candidate_tokens,
            )
        )

    return MicrocompactBatch(artifacts=outputs)
