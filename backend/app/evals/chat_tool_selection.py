"""Fixed-case evaluation for the M6 chat tool router.

The evaluator calls the same bounded selection function and tool schemas used
by production. Tests may inject a deterministic planner; running the module
directly uses the configured chat planner and therefore requires model access.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast

from app.agent.chat_tool_agent import select_chat_tool_calls
from app.agent.read_tools import ChatReadToolContext, build_chat_read_tools


FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "chat_tool_selection_cases.json"
)


def load_cases(path: Path = FIXTURE_PATH) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("chat tool selection fixture must be a list")
    return value


async def evaluate_cases(
    planner: Any,
    cases: list[dict[str, Any]] | None = None,
    *,
    call_budget: int = 4,
) -> dict[str, Any]:
    active_cases = cases or load_cases()
    # Selection only binds schemas; no tool is executed and this sentinel DB is
    # never accessed. This keeps evaluation read-only and independent of user data.
    context = ChatReadToolContext(
        db=cast(Any, None),
        user_id=1,
        conversation_id=1,
        source_message_id=1,
    )
    tools = build_chat_read_tools(context)
    allowed_tools = set(tools)
    results: list[dict[str, Any]] = []
    true_positive = 0
    expected_total = 0
    selected_total = 0
    disallowed_total = 0

    for case in active_cases:
        calls = await select_chat_tool_calls(
            planner=planner,
            tools=list(tools.values()),
            user_message=str(case["user_message"]),
            current_page=str(case.get("current_page") or "chat"),
            call_budget=call_budget,
        )
        selected = [str(call["name"]) for call in calls]
        expected = [str(name) for name in case.get("expected_tools", [])]
        selected_set = set(selected)
        expected_set = set(expected)
        disallowed = sorted(selected_set - allowed_tools)
        matched = len(selected_set & expected_set)
        true_positive += matched
        expected_total += len(expected_set)
        selected_total += len(selected_set)
        disallowed_total += len(disallowed)
        exact_match = selected_set == expected_set and not disallowed
        results.append({
            "id": case["id"],
            "passed": exact_match,
            "expected_tools": expected,
            "selected_tools": selected,
            "missing_tools": sorted(expected_set - selected_set),
            "unexpected_tools": sorted((selected_set - expected_set) & allowed_tools),
            "disallowed_tools": disallowed,
        })

    passed = sum(1 for result in results if result["passed"])
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "exact_match_rate": passed / len(results) if results else 1.0,
        "precision": true_positive / selected_total if selected_total else 1.0,
        "recall": true_positive / expected_total if expected_total else 1.0,
        "disallowed_tool_calls": disallowed_total,
        "call_budget": max(1, min(call_budget, 8)),
        "cases": results,
        "scope_note": (
            "fixed routing cases through the production tool schemas and bounded "
            "selector; this is an offline evaluation, not a production traffic claim"
        ),
    }


def main() -> None:
    from app.services.chat_service import _chat_planner_llm

    result = asyncio.run(evaluate_cases(_chat_planner_llm()))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
