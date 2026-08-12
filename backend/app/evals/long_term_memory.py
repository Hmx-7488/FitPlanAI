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
from app.models.user import UserMemory
from app.services.user_memory_service import recall_user_memories

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


async def evaluate_cases(cases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    active_cases = cases or load_cases()
    case_results = []
    true_positive = 0
    returned_total = 0
    expected_total = 0

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "memory-eval.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        for case_index, case in enumerate(active_cases, start=1):
            async with session_factory() as session:
                for item in case["memories"]:
                    session.add(
                        UserMemory(
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
                    )
                await session.commit()
                recalled = await recall_user_memories(
                    session,
                    case_index,
                    case["query"],
                    limit=case["limit"],
                )

            returned_ids = [memory.id for memory in recalled]
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
        "cases": case_results,
        "scope_note": "deterministic fixture metric; not a production traffic claim",
    }


def main() -> None:
    print(json.dumps(asyncio.run(evaluate_cases()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
