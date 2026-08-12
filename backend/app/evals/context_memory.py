"""Deterministic context/memory baseline evaluation.

This module measures whether a fact is available to the model under the current
chat context-loading policy. It deliberately does not call an LLM: if a fact is
absent from the assembled context, generation quality cannot recover it
reliably. The result is therefore a context-availability upper bound, not an
answer-quality score.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.services.token_estimator import estimate_tokens


CURRENT_HISTORY_QUERY_LIMIT = 10
DEFAULT_CASES_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "context_memory_cases.json"
)


def load_cases(path: Path | str = DEFAULT_CASES_PATH) -> list[dict[str, Any]]:
    """Load and minimally validate the versioned evaluation fixture."""
    fixture_path = Path(path)
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported context evaluation schema_version")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("context evaluation fixture must contain cases")
    return cases


def _filler_messages(
    conversation_id: str,
    turns: int,
    label: str,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for index in range(1, turns + 1):
        messages.extend(
            [
                {
                    "conversation_id": conversation_id,
                    "role": "user",
                    "content": f"{label}用户消息{index}：记录普通执行情况。",
                },
                {
                    "conversation_id": conversation_id,
                    "role": "assistant",
                    "content": f"{label}助手回复{index}：已记录普通执行情况。",
                },
            ]
        )
    return messages


def expand_history(case: dict[str, Any]) -> list[dict[str, str]]:
    """Expand compact fixture fields into an ordered multi-conversation history."""
    active_id = str(case["active_conversation_id"])
    history = _filler_messages(
        active_id,
        int(case.get("filler_turns_before", 0)),
        "前置",
    )
    for message in case.get("fact_messages", []):
        history.append(
            {
                "conversation_id": str(message["conversation_id"]),
                "role": str(message["role"]),
                "content": str(message["content"]),
            }
        )
    history.extend(
        _filler_messages(
            active_id,
            int(case.get("filler_turns_after", 0)),
            "后置",
        )
    )
    return history


def build_current_baseline_context(case: dict[str, Any]) -> dict[str, Any]:
    """Mirror the current chat service's dynamic context behavior.

    The current user message is committed before the database query with
    ``LIMIT 10``. It therefore occupies one of those ten rows and is skipped
    when history messages are appended, leaving at most nine prior messages.
    The current user message is then appended explicitly.
    """
    active_id = str(case["active_conversation_id"])
    history = [
        message
        for message in expand_history(case)
        if message["conversation_id"] == active_id
    ]
    prior_slots = max(CURRENT_HISTORY_QUERY_LIMIT - 1, 0)
    visible_history = history[-prior_slots:] if prior_slots else []
    profile = case.get("profile_context") or {}
    latest_plan = case.get("latest_plan_context") or None
    page_context = case.get("page_context") or {}
    probe = str(case["probe"])
    searchable_text = "\n".join(
        [
            json.dumps(profile, ensure_ascii=False, sort_keys=True),
            json.dumps(latest_plan, ensure_ascii=False, sort_keys=True),
            json.dumps(page_context, ensure_ascii=False, sort_keys=True),
            *(message["content"] for message in visible_history),
            probe,
        ]
    )
    return {
        "visible_history": visible_history,
        "profile_context": profile,
        "latest_plan_context": latest_plan,
        "page_context": page_context,
        "probe": probe,
        "searchable_text": searchable_text,
    }


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    context = build_current_baseline_context(case)
    must_include = [str(value) for value in case.get("must_include", [])]
    missing = [
        value for value in must_include if value not in context["searchable_text"]
    ]
    visible = not missing
    expected = bool(case["expected_current_visibility"])
    active_history_count = sum(
        message["conversation_id"] == str(case["active_conversation_id"])
        for message in expand_history(case)
    )
    return {
        "id": case["id"],
        "category": case["category"],
        "description": case["description"],
        "criticality": case.get("criticality", "normal"),
        "fact_visible": visible,
        "expected_current_visibility": expected,
        "fixture_expectation_matched": visible == expected,
        "missing_facts": missing,
        "active_history_messages": active_history_count,
        "visible_prior_messages": len(context["visible_history"]),
        "estimated_dynamic_context_tokens": estimate_tokens(
            context["searchable_text"]
        ),
    }


def run_baseline(
    path: Path | str = DEFAULT_CASES_PATH,
) -> dict[str, Any]:
    cases = load_cases(path)
    results = [evaluate_case(case) for case in cases]
    visible_count = sum(result["fact_visible"] for result in results)
    critical_results = [
        result for result in results if result["criticality"] == "safety"
    ]
    critical_visible = sum(result["fact_visible"] for result in critical_results)
    expectation_matches = sum(
        result["fixture_expectation_matched"] for result in results
    )
    total = len(results)
    return {
        "policy": {
            "history_query_limit": CURRENT_HISTORY_QUERY_LIMIT,
            "max_prior_messages_sent": CURRENT_HISTORY_QUERY_LIMIT - 1,
            "cross_conversation_recall": False,
            "conversation_summary": False,
            "long_term_memory": False,
        },
        "metrics": {
            "total_cases": total,
            "facts_visible": visible_count,
            "context_availability_rate": round(visible_count / total * 100, 1),
            "safety_cases": len(critical_results),
            "safety_facts_visible": critical_visible,
            "safety_context_availability_rate": round(
                critical_visible / len(critical_results) * 100, 1
            )
            if critical_results
            else 100.0,
            "fixture_expectations_matched": expectation_matches,
        },
        "results": results,
        "notes": [
            "This measures fact availability, not LLM answer quality.",
            "Token counts are a model-independent estimate for comparison only.",
            "Provider-reported token usage will be the production source of truth.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the deterministic SlimAgent context baseline."
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES_PATH,
        help="Path to a schema_version=1 JSON fixture.",
    )
    args = parser.parse_args()
    print(json.dumps(run_baseline(args.cases), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
