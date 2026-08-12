"""Deterministic evaluation for Artifact Microcompact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.services.artifact_microcompact import (
    ArtifactInput,
    MicrocompactPolicy,
    microcompact_artifacts,
)


DEFAULT_CASES_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "artifact_microcompact_cases.json"
)


def load_cases(path: Path | str = DEFAULT_CASES_PATH) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported artifact evaluation schema_version")
    policy = payload.get("policy")
    cases = payload.get("cases")
    if not isinstance(policy, dict) or not isinstance(cases, list) or not cases:
        raise ValueError("artifact evaluation fixture is incomplete")
    return policy, cases


def run_evaluation(path: Path | str = DEFAULT_CASES_PATH) -> dict[str, Any]:
    policy_data, cases = load_cases(path)
    policy = MicrocompactPolicy(**policy_data)
    results = []
    total_original = 0
    total_included = 0
    passed = 0

    for index, case in enumerate(cases):
        content = str(case.get("repeat_text", "")) * int(case.get("repeat", 1))
        content += str(case.get("critical_tail", ""))
        batch = microcompact_artifacts(
            [
                ArtifactInput(
                    original_index=index,
                    kind=str(case["kind"]),
                    title=str(case["title"]),
                    content=content,
                    reference_id=str(case["reference_id"]),
                )
            ],
            budget_tokens=int(case["budget_tokens"]),
            policy=policy,
        )
        artifact = batch.artifacts[0]
        preserved = all(
            marker in artifact.rendered_text
            for marker in case.get("must_preserve", [])
        )
        case_passed = artifact.mode == case["expected_mode"] and preserved
        passed += case_passed
        total_original += artifact.original_tokens
        total_included += artifact.included_tokens
        results.append(
            {
                "id": case["id"],
                "mode": artifact.mode,
                "expected_mode": case["expected_mode"],
                "critical_markers_preserved": preserved,
                "original_tokens": artifact.original_tokens,
                "included_tokens": artifact.included_tokens,
                "saved_tokens": artifact.original_tokens - artifact.included_tokens,
                "passed": case_passed,
            }
        )

    total = len(results)
    saved = max(0, total_original - total_included)
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total * 100, 1),
        "original_tokens": total_original,
        "included_tokens": total_included,
        "saved_tokens": saved,
        "token_reduction_rate": round(saved / total_original * 100, 1)
        if total_original
        else 0.0,
        "results": results,
        "note": "Deterministic fixture metric; not a production traffic claim.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Artifact Microcompact.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    args = parser.parse_args()
    print(json.dumps(run_evaluation(args.cases), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
