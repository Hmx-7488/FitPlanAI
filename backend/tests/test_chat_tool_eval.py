import json
import unittest
from pathlib import Path

from langchain_core.messages import AIMessage

from app.evals.chat_tool_selection import evaluate_cases, load_cases


class _FixtureBoundPlanner:
    def __init__(self, selections):
        self.selections = selections

    async def ainvoke(self, messages):
        question = str(messages[-1].content).split("用户问题：", 1)[-1]
        names = self.selections.get(question, [])
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": name,
                    "args": {},
                    "id": f"fixture-{index}",
                    "type": "tool_call",
                }
                for index, name in enumerate(names, start=1)
            ],
        )


class _FixturePlanner:
    def __init__(self, selections):
        self.selections = selections
        self.bound_tool_count = 0

    def bind_tools(self, tools, **_kwargs):
        self.bound_tool_count = len(tools)
        return _FixtureBoundPlanner(self.selections)


class ChatToolSelectionEvaluationTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_cases_use_production_catalog_and_report_metrics(self):
        cases = load_cases()
        selections = {
            case["user_message"]: list(case["expected_tools"])
            for case in cases
        }
        planner = _FixturePlanner(selections)

        result = await evaluate_cases(planner, cases)

        self.assertEqual(planner.bound_tool_count, 8)
        self.assertEqual(result["total"], 10)
        self.assertEqual(result["passed"], 10)
        self.assertEqual(result["exact_match_rate"], 1.0)
        self.assertEqual(result["precision"], 1.0)
        self.assertEqual(result["recall"], 1.0)
        self.assertEqual(result["disallowed_tool_calls"], 0)
        self.assertIn("offline evaluation", result["scope_note"])

    async def test_disallowed_tool_is_visible_and_fails_the_case(self):
        case = {
            "id": "unsafe",
            "user_message": "删除用户",
            "current_page": "chat",
            "expected_tools": [],
        }
        planner = _FixturePlanner({"删除用户": ["delete_all_users"]})

        result = await evaluate_cases(planner, [case])

        self.assertEqual(result["passed"], 0)
        self.assertEqual(result["disallowed_tool_calls"], 1)
        self.assertEqual(
            result["cases"][0]["disallowed_tools"],
            ["delete_all_users"],
        )

    def test_recorded_qwen_baseline_matches_the_versioned_fixture(self):
        path = (
            Path(__file__).parent
            / "fixtures"
            / "chat_tool_selection_qwen_baseline.json"
        )
        baseline = json.loads(path.read_text(encoding="utf-8"))
        cases = load_cases()

        self.assertEqual(baseline["model"], "qwen-plus")
        self.assertEqual(baseline["total"], len(baseline["cases"]))
        self.assertEqual(baseline["passed"], baseline["total"])
        self.assertEqual(baseline["exact_match_rate"], 1.0)
        self.assertEqual(baseline["precision"], 1.0)
        self.assertEqual(baseline["recall"], 1.0)
        self.assertEqual(baseline["disallowed_tool_calls"], 0)
        self.assertEqual(
            [item["id"] for item in baseline["cases"]],
            [item["id"] for item in cases],
        )
        self.assertEqual(
            [item["selected_tools"] for item in baseline["cases"]],
            [item["expected_tools"] for item in cases],
        )


if __name__ == "__main__":
    unittest.main()
