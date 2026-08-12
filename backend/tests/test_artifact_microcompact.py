import unittest

from app.services.artifact_microcompact import (
    ArtifactInput,
    MicrocompactPolicy,
    microcompact_artifacts,
)
from app.evals.artifact_microcompact import run_evaluation


class ArtifactMicrocompactTests(unittest.TestCase):
    def setUp(self):
        self.policy = MicrocompactPolicy(
            full_content_tokens=80,
            compact_content_tokens=35,
        )

    def test_artifact_requires_traceable_reference(self):
        with self.assertRaisesRegex(ValueError, "reference_id"):
            ArtifactInput(
                original_index=0,
                kind="tool",
                title="无引用结果",
                content="内容",
                reference_id="",
            )

    def test_short_artifact_is_kept_full_with_reference(self):
        batch = microcompact_artifacts(
            [
                ArtifactInput(
                    original_index=0,
                    kind="rag",
                    title="蛋白质指南",
                    content="减脂期应根据体重安排蛋白质。",
                    reference_id="chunk-protein",
                )
            ],
            budget_tokens=200,
            policy=self.policy,
        )
        artifact = batch.artifacts[0]
        self.assertEqual(artifact.mode, "full")
        self.assertIn("chunk-protein", artifact.rendered_text)
        self.assertIn("根据体重安排蛋白质", artifact.rendered_text)
        self.assertEqual(batch.full_count, 1)

    def test_long_artifact_is_compacted_and_preserves_safety_numbers(self):
        content = (
            "这是很长的背景介绍。" * 30
            + "肾功能异常者不应自行补充，每天剂量必须经过专业确认。"
            + "这是结尾说明。" * 20
        )
        batch = microcompact_artifacts(
            [
                ArtifactInput(
                    original_index=0,
                    kind="tool",
                    title="补剂检查结果",
                    content=content,
                    reference_id="tool-call-42",
                )
            ],
            budget_tokens=120,
            policy=self.policy,
        )
        artifact = batch.artifacts[0]
        self.assertEqual(artifact.mode, "microcompact")
        self.assertIn("微压缩", artifact.rendered_text)
        self.assertIn("肾功能异常", artifact.rendered_text)
        self.assertIn("每天剂量", artifact.rendered_text)
        self.assertLess(artifact.included_tokens, artifact.original_tokens)
        self.assertGreater(batch.saved_tokens, 0)

    def test_low_rank_artifact_is_dropped_when_batch_budget_is_exhausted(self):
        artifacts = [
            ArtifactInput(
                original_index=0,
                kind="rag",
                title="第一条",
                content="第一条短资料。",
                reference_id="chunk-1",
            ),
            ArtifactInput(
                original_index=1,
                kind="rag",
                title="第二条",
                content="第二条短资料。",
                reference_id="chunk-2",
            ),
        ]
        first_only = microcompact_artifacts(
            artifacts[:1],
            budget_tokens=200,
            policy=self.policy,
        )
        batch = microcompact_artifacts(
            artifacts,
            budget_tokens=first_only.included_tokens,
            policy=self.policy,
        )
        self.assertEqual(batch.artifacts[0].mode, "full")
        self.assertEqual(batch.artifacts[1].mode, "dropped")
        self.assertEqual(batch.dropped_count, 1)

    def test_empty_budget_drops_without_losing_trace_metadata(self):
        batch = microcompact_artifacts(
            [
                ArtifactInput(
                    original_index=7,
                    kind="tool",
                    title="动作搜索",
                    content="返回了二十个候选动作。",
                    reference_id="tool-call-7",
                )
            ],
            budget_tokens=0,
            policy=self.policy,
        )
        artifact = batch.artifacts[0]
        self.assertEqual(artifact.mode, "dropped")
        self.assertEqual(artifact.reference_id, "tool-call-7")
        self.assertEqual(artifact.original_index, 7)

    def test_deterministic_evaluation_fixture_passes(self):
        report = run_evaluation()
        self.assertEqual(report["total"], 4)
        self.assertEqual(report["passed"], 4)
        self.assertEqual(report["failed"], 0)
        self.assertGreater(report["token_reduction_rate"], 50)
