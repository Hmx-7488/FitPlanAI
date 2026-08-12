import unittest

from app.evals.long_term_memory import evaluate_cases, load_cases


class LongTermMemoryEvaluationTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_cases_pass_with_perfect_precision_and_recall(self):
        result = await evaluate_cases(load_cases())
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["precision"], 1.0)
        self.assertEqual(result["recall"], 1.0)


if __name__ == "__main__":
    unittest.main()
