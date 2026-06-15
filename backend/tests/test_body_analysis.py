import unittest

from app.services.body_analysis_service import (
    assess_photo_quality,
    fuse_body_fat_estimate,
    navy_body_fat,
    select_comparable_views,
    validate_measurements,
)


class MeasurementValidationTests(unittest.TestCase):
    def test_accepts_optional_measurements_and_normalizes_numbers(self):
        result = validate_measurements({
            "waist_cm": "82.24",
            "hip_cm": None,
            "body_fat_scale_pct": 21.46,
        })

        self.assertEqual(result, {"waist_cm": 82.2, "body_fat_scale_pct": 21.5})

    def test_rejects_out_of_range_measurements(self):
        with self.assertRaisesRegex(ValueError, "waist_cm"):
            validate_measurements({"waist_cm": 20})


class CircumferenceEstimateTests(unittest.TestCase):
    def test_returns_reasonable_male_estimate(self):
        result = navy_body_fat("male", 175, 86, None, 38)

        self.assertIsNotNone(result)
        self.assertGreater(result, 8)
        self.assertLess(result, 35)

    def test_requires_hip_for_female_estimate(self):
        self.assertIsNone(navy_body_fat("female", 165, 72, None, 32))
        self.assertIsNotNone(navy_body_fat("female", 165, 72, 94, 32))


class PhotoQualityTests(unittest.TestCase):
    def test_rejects_when_all_views_are_unusable(self):
        quality = assess_photo_quality(
            {
                "is_usable": False,
                "view_quality": {
                    "front": {
                        "usable": False,
                        "correct_view": True,
                        "torso_visible": False,
                        "lighting": "dark",
                        "occlusion": "heavy",
                    }
                },
            },
            ["front"],
            0.3,
        )

        self.assertFalse(quality["is_usable"])
        self.assertTrue(quality["rejection_reasons"])
        self.assertTrue(quality["retake_guidance"])

    def test_accepts_one_clear_view_but_preserves_view_level_quality(self):
        quality = assess_photo_quality(
            {
                "is_usable": True,
                "view_quality": {
                    "side": {
                        "usable": True,
                        "correct_view": True,
                        "torso_visible": True,
                        "lighting": "good",
                        "occlusion": "none",
                    }
                },
            },
            ["side"],
            0.62,
        )

        self.assertTrue(quality["is_usable"])
        self.assertEqual(quality["usable_views"], ["side"])
        self.assertTrue(quality["views"]["side"]["usable"])

    def test_missing_view_quality_and_string_false_are_rejected(self):
        missing = assess_photo_quality({"is_usable": True}, ["front"], 0.7)
        string_false = assess_photo_quality(
            {
                "is_usable": "false",
                "view_quality": {
                    "front": {
                        "usable": "false",
                        "correct_view": "true",
                        "torso_visible": "true",
                        "lighting": "good",
                        "occlusion": "none",
                    }
                },
            },
            ["front"],
            0.7,
        )

        self.assertFalse(missing["is_usable"])
        self.assertFalse(string_false["is_usable"])


class EstimateFusionTests(unittest.TestCase):
    def test_measurements_increase_evidence_without_false_precision(self):
        vision_only = fuse_body_fat_estimate(
            gender="male",
            height_cm=175,
            vision_low=18,
            vision_high=24,
            vision_confidence=0.65,
            measurements={},
            usable_view_count=1,
        )
        fused = fuse_body_fat_estimate(
            gender="male",
            height_cm=175,
            vision_low=18,
            vision_high=24,
            vision_confidence=0.65,
            measurements={
                "waist_cm": 86,
                "neck_cm": 38,
                "body_fat_scale_pct": 20.5,
            },
            usable_view_count=3,
        )

        self.assertEqual(len(vision_only["estimate_sources"]), 1)
        self.assertEqual(len(fused["estimate_sources"]), 3)
        self.assertGreater(fused["confidence"], vision_only["confidence"])
        self.assertGreaterEqual(fused["body_fat_high"] - fused["body_fat_low"], 3)


class HistoricalComparisonTests(unittest.TestCase):
    def test_only_selects_matching_usable_views_with_similar_aspect_ratio(self):
        current_metadata = {
            "front": {"aspect_ratio": 0.75},
            "side": {"aspect_ratio": 0.6},
        }
        previous_metadata = {
            "front": {"aspect_ratio": 0.78},
            "side": {"aspect_ratio": 0.9},
        }
        current_quality = {
            "views": {
                "front": {"usable": True, "correct_view": True},
                "side": {"usable": True, "correct_view": True},
            }
        }
        previous_quality = {
            "views": {
                "front": {"usable": True, "correct_view": True},
                "side": {"usable": True, "correct_view": True},
            }
        }

        result = select_comparable_views(
            current_metadata,
            previous_metadata,
            current_quality,
            previous_quality,
        )

        self.assertEqual(result, ["front"])


if __name__ == "__main__":
    unittest.main()
