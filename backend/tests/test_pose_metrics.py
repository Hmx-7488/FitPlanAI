import math
import unittest

from app.services.pose_metrics_service import compute_pose_metrics


def make_frame(index: int, visible: bool = True) -> dict:
    visibility = 0.95 if visible else 0.1
    landmarks = [
        {"x": 0.5, "y": 0.5, "z": 0.0, "visibility": visibility}
        for _ in range(33)
    ]
    phase = math.sin(index / 11 * math.pi)
    hip_y = 0.48 + phase * 0.12
    knee_offset = 0.12 - phase * 0.055

    points = {
        11: (0.43, 0.25), 12: (0.57, 0.25),
        13: (0.40, 0.38), 14: (0.60, 0.38),
        15: (0.38, 0.50), 16: (0.62, 0.50),
        23: (0.45, hip_y), 24: (0.55, hip_y),
        25: (0.45 - knee_offset, 0.68), 26: (0.55 + knee_offset, 0.68),
        27: (0.42, 0.88), 28: (0.58, 0.88),
        29: (0.40, 0.91), 30: (0.60, 0.91),
        31: (0.38, 0.92), 32: (0.62, 0.92),
    }
    for landmark_index, (x, y) in points.items():
        landmarks[landmark_index] = {
            "x": x,
            "y": y,
            "z": 0,
            "visibility": visibility,
        }
    return {"timestamp_ms": index * 100, "landmarks": landmarks}


class PoseMetricsTests(unittest.TestCase):
    def test_computes_joint_ranges_symmetry_and_trajectory(self):
        result = compute_pose_metrics(
            {
                "model": "mediapipe_pose_landmarker_lite",
                "duration_ms": 1100,
                "frames": [make_frame(index) for index in range(12)],
            },
            "squat",
        )

        self.assertTrue(result["available"])
        self.assertTrue(result["quality"]["is_usable"])
        self.assertEqual(result["sampled_frames"], 12)
        self.assertIn("left_knee", result["joint_angles"])
        self.assertGreater(result["joint_angles"]["left_knee"]["range"], 0)
        self.assertIsNotNone(result["symmetry_difference_deg"])
        self.assertEqual(len(result["metrics"]), 4)

    def test_rejects_heavily_occluded_landmarks(self):
        result = compute_pose_metrics(
            {"frames": [make_frame(index, visible=False) for index in range(12)]},
            "squat",
        )

        self.assertFalse(result["quality"]["is_usable"])
        self.assertFalse(result["available"])
        self.assertIn("关键关节存在较多遮挡或未入镜", result["quality"]["issues"])


if __name__ == "__main__":
    unittest.main()
