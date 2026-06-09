import asyncio
import unittest
from unittest.mock import patch

from app.api.body import _coerce_body_fat_range
from app.api.meal import _extract_json_array
from app.api.pose import _normalize_pose_result
from app.schemas.vision import IngredientItem
from app.services.image_utils import (
    detect_image_mime,
    image_extension,
    read_image_dimensions,
    validate_image,
)
from app.services.vision_service import _build_recipe, _encode_image, _parse_recipes


def png_header(width: int, height: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + (b"\x00" * 8) + width.to_bytes(4, "big") + height.to_bytes(4, "big")


class ImageValidationTests(unittest.TestCase):
    def test_detects_content_instead_of_filename(self):
        image = png_header(32, 24)
        mime_type, width, height = validate_image(image)

        self.assertEqual(mime_type, "image/png")
        self.assertEqual((width, height), (32, 24))
        self.assertEqual(image_extension(mime_type, "wrong.jpg"), ".png")
        self.assertTrue(_encode_image(image, mime_type).startswith("data:image/png;base64,"))

    def test_rejects_spoofed_or_too_small_images(self):
        self.assertEqual(detect_image_mime(b"not an image"), "application/octet-stream")
        with self.assertRaisesRegex(ValueError, "invalid image"):
            validate_image(b"not an image")
        with self.assertRaisesRegex(ValueError, "10x10"):
            validate_image(png_header(9, 20))

    def test_reads_lossy_webp_dimensions(self):
        image = bytearray(30)
        image[0:4] = b"RIFF"
        image[8:12] = b"WEBP"
        image[12:16] = b"VP8 "
        image[23:26] = b"\x9d\x01\x2a"
        image[26:28] = (640).to_bytes(2, "little")
        image[28:30] = (480).to_bytes(2, "little")

        self.assertEqual(read_image_dimensions(bytes(image), "image/webp"), (640, 480))


class ResponseNormalizationTests(unittest.TestCase):
    def test_extracts_json_array_from_markdown(self):
        parsed = _extract_json_array('result:\n```json\n[{"name":"egg"}]\n```')
        self.assertEqual(parsed, [{"name": "egg"}])

    def test_normalizes_pose_result(self):
        result = _normalize_pose_result(
            {
                "score": 140,
                "issues": [{"severity": "unknown", "description": "x", "suggestion": "y"}],
                "coach_cues": "bad format",
                "phases": [{"phase": "下降", "observation": "膝盖内扣"}],
                "rep_count_estimate": 3,
            },
            "深蹲",
            True,
        )

        self.assertEqual(result["score"], 100)
        self.assertEqual(result["issues"][0]["severity"], "low")
        self.assertEqual(result["coach_cues"], ["核心收紧", "动作匀速"])
        self.assertEqual(result["rep_count_estimate"], 3)

    def test_body_fat_range_is_ordered_and_bounded(self):
        user = type("User", (), {"gender": "female"})()
        low, high = _coerce_body_fat_range(40, 20, user)

        self.assertLess(low, high)
        self.assertLessEqual(high - low, 12)
        self.assertGreaterEqual(low, 12)


class RecipeTests(unittest.TestCase):
    def test_recipe_contains_substitutes_and_shopping_list(self):
        recipe = _build_recipe(
            "鸡胸肉糙米碗",
            [
                "食材：鸡胸肉、西兰花、糙米",
                "热量：约 420 kcal | 蛋白质：35g | 碳水：48g | 脂肪：9g",
                "做法：煎鸡胸肉，焯西兰花，搭配糙米。",
            ],
            [IngredientItem(
                name="chicken_breast",
                display_name="鸡胸肉",
                estimated_weight_g=150,
                confidence=0.9,
            )],
        )

        self.assertIn("西兰花", recipe.shopping_list)
        self.assertIn("糙米", recipe.shopping_list)
        self.assertEqual(recipe.substitute_ingredients[0].missing, "西兰花")

    def test_historical_markdown_uses_dish_headings_not_field_labels(self):
        recipes = _parse_recipes(
            """### **1. 鸡胸肉蔬菜碗**
**食材**：
- 鸡胸肉 150g
- 西兰花 100g

**热量**：约 420 kcal | **蛋白质**：35g | **碳水**：40g | **脂肪**：10g

**做法**：
1. 煎熟鸡胸肉。
2. 焯熟西兰花。

### **2. 酸奶燕麦杯**
**食材**：
- 酸奶 150g
- 燕麦 30g

**热量**：约 280 kcal | **蛋白质**：15g
**做法**：混合即可。
""",
            [],
        )

        self.assertEqual([recipe.name for recipe in recipes], ["鸡胸肉蔬菜碗", "酸奶燕麦杯"])
        self.assertEqual(recipes[0].calories_est, 420)
        self.assertEqual(recipes[0].protein_est, 35)
        self.assertIn("煎熟鸡胸肉", recipes[0].steps)

    def test_structured_json_recipe_is_parsed(self):
        recipes = _parse_recipes(
            """```json
[{
  "name": "鸡胸肉沙拉",
  "ingredients": ["鸡胸肉 150g", "生菜 100g"],
  "calories_est": 360,
  "protein_est": 40,
  "carbs_est": 18,
  "fat_est": 12,
  "steps": ["煎熟鸡胸肉", "混合蔬菜"],
  "substitute_ingredients": [{"missing": "鸡胸肉", "alternatives": ["去皮鸡腿肉 170g"]}],
  "shopping_list": ["生菜 100g"]
}]
```""",
            [],
        )

        self.assertEqual(recipes[0].name, "鸡胸肉沙拉")
        self.assertEqual(recipes[0].steps, "1. 煎熟鸡胸肉\n2. 混合蔬菜")
        self.assertEqual(recipes[0].shopping_list, ["生菜 100g"])

    def test_image_generation_jobs_can_run_concurrently(self):
        active = 0
        peak = 0

        def fake_generate(index: int):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            import time
            time.sleep(0.03)
            active -= 1
            return index

        async def run():
            return await asyncio.gather(*[
                asyncio.to_thread(fake_generate, index)
                for index in range(3)
            ])

        with patch("app.services.vision_service.generate_recipe_image"):
            self.assertEqual(asyncio.run(run()), [0, 1, 2])
        self.assertGreaterEqual(peak, 2)


if __name__ == "__main__":
    unittest.main()
