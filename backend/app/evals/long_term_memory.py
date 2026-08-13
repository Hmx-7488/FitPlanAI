"""Deterministic M4 lifecycle and relevance evaluation for long-term memory."""

from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.memory.retriever import MemoryRetriever
from app.memory.types import MemoryVectorMatch
from app.models.user import UserMemory
from app.services.user_memory_service import _relevance_score

FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "long_term_memory_cases.json"
)


def load_cases(path: Path = FIXTURE_PATH) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("long-term memory fixture must be a list")
    return value


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class _EvaluationVectorBackend:
    """Deterministic candidate source; MemoryRetriever still owns hybrid logic."""

    def __init__(self) -> None:
        self.memories_by_user: dict[int, list[UserMemory]] = {}
        self.explicit_vector_ids_by_user: dict[int, list[int]] = {}

    async def search(self, query: str, *, user_id: int, limit: int):
        explicit_ids = self.explicit_vector_ids_by_user.get(user_id, [])
        by_id = {memory.id: memory for memory in self.memories_by_user.get(user_id, [])}
        explicit = [by_id[memory_id] for memory_id in explicit_ids if memory_id in by_id]
        ranked = sorted(
            (
                (_relevance_score(memory, query)[0], memory)
                for memory in self.memories_by_user.get(user_id, [])
                if memory.id not in explicit_ids
            ),
            key=lambda item: (item[0], item[1].id),
            reverse=True,
        )
        semantic_matches = [
            MemoryVectorMatch(
                memory_id=memory.id,
                score=1.0,
                content_fingerprint=memory.content_fingerprint,
                index_revision=int(memory.index_revision or 0),
            )
            for memory in explicit
        ]
        return semantic_matches + [
            MemoryVectorMatch(
                memory_id=memory.id,
                score=min(1.0, score / 12),
                content_fingerprint=memory.content_fingerprint,
                index_revision=int(memory.index_revision or 0),
            )
            for score, memory in ranked[:limit]
            if score > 0
        ]

    async def upsert(self, memory):
        return None

    async def delete(self, memory_id: int):
        return None

    async def list_memory_ids(self):
        return set()

    async def collection_exists(self):
        return True

    async def close(self):
        return None

    async def cleanup_obsolete_collections(self):
        return 0


async def evaluate_cases(cases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    active_cases = cases or load_cases()
    case_results = []
    true_positive = 0
    returned_total = 0
    expected_total = 0
    degraded_cases = 0
    vector_hit_cases = 0

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "memory-eval.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        for case_index, case in enumerate(active_cases, start=1):
            async with session_factory() as session:
                case_memories: list[UserMemory] = []
                for item in case["memories"]:
                    memory = UserMemory(
                            id=item["id"],
                            user_id=case_index,
                            memory_type=item["memory_type"],
                            memory_key=item["memory_key"],
                            content_json=json.dumps(
                                {"fact": item["content_text"]},
                                ensure_ascii=False,
                            ),
                            content_text=item["content_text"],
                            content_fingerprint=f"{case_index:02d}{item['id']:062d}"[-64:],
                            confirmation_status=item["confirmation_status"],
                            sensitivity=item["sensitivity"],
                            confidence=1,
                            valid_until=_parse_datetime(item.get("valid_until")),
                            deleted_at=_parse_datetime(item.get("deleted_at")),
                            created_by="fixture",
                        )
                    session.add(memory)
                    case_memories.append(memory)
                await session.commit()
                backend = _EvaluationVectorBackend()
                backend.memories_by_user[case_index] = case_memories
                backend.explicit_vector_ids_by_user[case_index] = list(
                    case.get("simulated_vector_ids", [])
                )
                recall_result = await MemoryRetriever(
                    vector_backend=backend
                ).retrieve(
                    session,
                    case_index,
                    case["query"],
                    mode="hybrid",
                    limit=case["limit"],
                )

            returned_ids = [hit.memory.id for hit in recall_result.hits]
            degraded_cases += int(recall_result.degraded)
            vector_hit_cases += int(
                any("vector" in hit.channels for hit in recall_result.hits)
            )
            expected_ids = list(case["expected_ids"])
            returned_set = set(returned_ids)
            expected_set = set(expected_ids)
            matched = len(returned_set & expected_set)
            true_positive += matched
            returned_total += len(returned_ids)
            expected_total += len(expected_ids)
            case_results.append(
                {
                    "id": case["id"],
                    "passed": returned_ids == expected_ids,
                    "expected_ids": expected_ids,
                    "returned_ids": returned_ids,
                    "requested_mode": recall_result.requested_mode,
                    "effective_mode": recall_result.effective_mode,
                    "degraded": recall_result.degraded,
                    "degradation_reason": recall_result.degradation_reason,
                    "channels": {
                        str(hit.memory.id): list(hit.channels)
                        for hit in recall_result.hits
                    },
                    "simulated_vector_ids": list(
                        case.get("simulated_vector_ids", [])
                    ),
                }
            )

        await engine.dispose()

    precision = true_positive / returned_total if returned_total else 1.0
    recall = true_positive / expected_total if expected_total else 1.0
    passed = sum(1 for case in case_results if case["passed"])
    return {
        "total": len(case_results),
        "passed": passed,
        "failed": len(case_results) - passed,
        "pass_rate": passed / len(case_results) if case_results else 1.0,
        "precision": precision,
        "recall": recall,
        "requested_mode": "hybrid",
        "degraded_cases": degraded_cases,
        "vector_hit_cases": vector_hit_cases,
        "cases": case_results,
        "scope_note": (
            "deterministic fixture metric through MemoryRetriever hybrid/RRF; "
            "the vector candidate source is simulated (including explicitly "
            "labeled semantic-only fixtures) and is not a real embedding, "
            "production hybrid-retrieval quality, or traffic claim"
        ),
    }


def main() -> None:
    print(json.dumps(asyncio.run(evaluate_cases()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
