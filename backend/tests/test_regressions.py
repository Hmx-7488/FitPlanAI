import asyncio
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

from app.api.body import _coerce_body_fat_range
from app.services.vision_service import _extract_json_array
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
                "issues": [{"severity": "unknown", "title": "问题", "description": "x", "impact": "y", "correction": "z"}],
                "coach_cues": "bad format",
                "phases": [{"phase": "下降", "observation": "膝盖内扣"}],
                "rep_count_estimate": 3,
                "risk_level": "invalid",
                "metrics": [{"name": "稳定", "score": 200, "description": "test"}],
            },
            "深蹲",
            True,
        )

        self.assertEqual(result["overall_score"], 100)
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["risk_level"], "low")
        self.assertEqual(result["issues"][0]["severity"], "low")
        self.assertEqual(result["issues"][0]["title"], "问题")
        self.assertEqual(result["coach_cues"], ["核心收紧", "动作匀速"])
        self.assertEqual(result["rep_count_estimate"], 3)
        self.assertEqual(result["metrics"][0]["score"], 100)

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

    def test_image_generation_jobs_run_concurrently(self):
        from types import SimpleNamespace
        from app.services.recipe_image_service import process_recipe_image_jobs

        jobs = [
            SimpleNamespace(id=11, status="queued"),
            SimpleNamespace(id=12, status="ready"),
            SimpleNamespace(id=13, status="queued"),
        ]
        processed = []
        active = 0
        max_active = 0

        async def fake_process(job_id):
            nonlocal active, max_active
            processed.append(job_id)
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            active -= 1

        session = AsyncMock()
        session.__aenter__.return_value = session
        session.__aexit__.return_value = None

        with (
            patch(
                "app.services.recipe_image_service.async_session",
                return_value=session,
            ),
            patch(
                "app.services.recipe_image_service.get_recipe_image_jobs",
                new=AsyncMock(return_value=jobs),
            ),
            patch(
                "app.services.recipe_image_service.process_recipe_image_job",
                side_effect=fake_process,
            ),
        ):
            asyncio.run(process_recipe_image_jobs(7))

        self.assertEqual(set(processed), {11, 13})
        self.assertEqual(max_active, 2)


# ═══════════════════════════════════════════════════════════════
# RAG 回归测试
# ═══════════════════════════════════════════════════════════════


class AdminAuthTests(unittest.TestCase):
    """Issue 1: 管理接口鉴权逻辑。"""

    def _make_settings(self, env="development", key=""):
        """创建 mock Settings 对象。"""
        s = MagicMock()
        s.APP_ENV = env
        s.KNOWLEDGE_ADMIN_KEY = key
        return s

    def test_dev_no_key_allows(self):
        """development + 未配置密钥 → 放行"""
        from app.api.knowledge import require_admin_key
        with patch("app.api.knowledge.get_settings", return_value=self._make_settings("development", "")):
            # 不应抛出异常
            require_admin_key(x_admin_key="")

    def test_configured_key_no_header_rejects(self):
        """已配置密钥 + 无请求头 → 403"""
        from app.api.knowledge import require_admin_key
        from fastapi import HTTPException
        with patch("app.api.knowledge.get_settings", return_value=self._make_settings("development", "secret123")):
            with self.assertRaises(HTTPException) as ctx:
                require_admin_key(x_admin_key="")
            self.assertEqual(ctx.exception.status_code, 403)

    def test_wrong_key_rejects(self):
        """已配置密钥 + 错误密钥 → 403"""
        from app.api.knowledge import require_admin_key
        from fastapi import HTTPException
        with patch("app.api.knowledge.get_settings", return_value=self._make_settings("development", "secret123")):
            with self.assertRaises(HTTPException) as ctx:
                require_admin_key(x_admin_key="wrong_key")
            self.assertEqual(ctx.exception.status_code, 403)

    def test_correct_key_passes(self):
        """已配置密钥 + 正确密钥 → 放行"""
        from app.api.knowledge import require_admin_key
        with patch("app.api.knowledge.get_settings", return_value=self._make_settings("development", "secret123")):
            require_admin_key(x_admin_key="secret123")

    def test_prod_no_key_rejects(self):
        """production + 未配置密钥 → 拒绝"""
        from app.api.knowledge import require_admin_key
        from fastapi import HTTPException
        with patch("app.api.knowledge.get_settings", return_value=self._make_settings("production", "")):
            with self.assertRaises(HTTPException) as ctx:
                require_admin_key(x_admin_key="")
            self.assertEqual(ctx.exception.status_code, 403)
            # 错误信息不应泄露密钥
            self.assertNotIn("secret", ctx.exception.detail.lower())

    def test_no_key_leak_in_error(self):
        """错误信息中不应包含密钥值"""
        from app.api.knowledge import require_admin_key
        from fastapi import HTTPException
        with patch("app.api.knowledge.get_settings", return_value=self._make_settings("production", "my_secret_key_here")):
            with self.assertRaises(HTTPException) as ctx:
                require_admin_key(x_admin_key="")
            self.assertNotIn("my_secret_key_here", ctx.exception.detail)


class EvidenceAssessmentTests(unittest.TestCase):
    """Issue 2: 证据不足判定。"""

    def test_unrelated_query_insufficient(self):
        """与健身无关的查询应返回证据不足"""
        from app.rag.models import SearchQuery
        from app.rag.retriever import get_retriever
        r = get_retriever()
        for query in ["量子力学对减脂的影响", "今天天气适合穿什么", "Python如何读取文件"]:
            result = r.search(SearchQuery(query=query, top_k=5))
            self.assertTrue(
                result.insufficient_evidence,
                f"Expected insufficient_evidence for '{query}', got {len(result.documents)} docs",
            )
            self.assertEqual(len(result.documents), 0, f"Expected empty documents for '{query}'")

    def test_related_query_sufficient(self):
        """与健身相关的查询应返回有效结果"""
        from app.rag.models import SearchQuery
        from app.rag.retriever import get_retriever
        r = get_retriever()
        result = r.search(SearchQuery(query="减脂期每天应该摄入多少热量", top_k=5))
        self.assertFalse(result.insufficient_evidence)
        self.assertGreater(len(result.documents), 0)

    def test_score_floor_threshold(self):
        """原始合并分数低于 _SCORE_FLOOR 应判为证据不足"""
        from app.rag.retriever import _SCORE_FLOOR
        from app.rag.models import RetrievedChunk
        from app.rag.retriever import HybridRetriever
        docs = [RetrievedChunk(
            chunk_id="c1", document_id="d1", title="T", content="C",
            score=_SCORE_FLOOR - 0.01, retrieval_method="vector",
        )]
        self.assertTrue(HybridRetriever._assess_evidence("test", docs, raw_top_score=_SCORE_FLOOR - 0.01))

    def test_score_ceiling_threshold(self):
        """原始合并分数高于 _SCORE_CEILING 应判为证据充分"""
        from app.rag.retriever import _SCORE_CEILING
        from app.rag.models import RetrievedChunk
        from app.rag.retriever import HybridRetriever
        docs = [RetrievedChunk(
            chunk_id="c1", document_id="d1", title="T", content="C",
            score=0.9, retrieval_method="vector",
        )]
        self.assertFalse(HybridRetriever._assess_evidence("test", docs, raw_top_score=_SCORE_CEILING + 0.01))


class GoalTypeFilteringTests(unittest.TestCase):
    """目标类型过滤：构造 chunk 直接测试 _filter_and_rerank。"""

    def _build_retriever(self):
        from app.rag.retriever import get_retriever
        r = get_retriever()
        r.initialize()
        return r

    def _make_mg(self, chunks, score=0.8):
        """构造合并字典。"""
        return {ch.chunk_id: (ch, score, 'vector') for ch in chunks}

    def test_muscle_gain_excludes_fat_loss(self):
        """goal_type=muscle_gain 保留 muscle_gain + general，排除 fat_loss"""
        from app.rag.models import GoalType, KnowledgeChunk, KnowledgeCategory, SearchQuery
        r = self._build_retriever()
        chunks = [
            KnowledgeChunk(document_id='d1', title='增肌', content='c',
                           category=KnowledgeCategory.muscle_gain_standards,
                           goal_types=[GoalType.muscle_gain], chunk_id='c_mg'),
            KnowledgeChunk(document_id='d2', title='减脂', content='c',
                           category=KnowledgeCategory.fat_loss_standards,
                           goal_types=[GoalType.fat_loss], chunk_id='c_fl'),
            KnowledgeChunk(document_id='d3', title='通用', content='c',
                           category=KnowledgeCategory.nutrition_planning,
                           goal_types=[GoalType.general], chunk_id='c_gen'),
        ]
        mg = self._make_mg(chunks)
        q = SearchQuery(query='test', goal_type=GoalType.muscle_gain, top_k=10)
        rr = r._filter_and_rerank(mg, q)
        kept = {ch.chunk_id for ch, _, _ in rr}
        self.assertIn('c_mg', kept)
        self.assertIn('c_gen', kept)
        self.assertNotIn('c_fl', kept)

    def test_fat_loss_excludes_muscle_gain(self):
        """goal_type=fat_loss 保留 fat_loss + general，排除 muscle_gain"""
        from app.rag.models import GoalType, KnowledgeChunk, KnowledgeCategory, SearchQuery
        r = self._build_retriever()
        chunks = [
            KnowledgeChunk(document_id='d1', title='增肌', content='c',
                           category=KnowledgeCategory.muscle_gain_standards,
                           goal_types=[GoalType.muscle_gain], chunk_id='c_mg'),
            KnowledgeChunk(document_id='d2', title='减脂', content='c',
                           category=KnowledgeCategory.fat_loss_standards,
                           goal_types=[GoalType.fat_loss], chunk_id='c_fl'),
            KnowledgeChunk(document_id='d3', title='通用', content='c',
                           category=KnowledgeCategory.nutrition_planning,
                           goal_types=[GoalType.general], chunk_id='c_gen'),
        ]
        mg = self._make_mg(chunks)
        q = SearchQuery(query='test', goal_type=GoalType.fat_loss, top_k=10)
        rr = r._filter_and_rerank(mg, q)
        kept = {ch.chunk_id for ch, _, _ in rr}
        self.assertIn('c_fl', kept)
        self.assertIn('c_gen', kept)
        self.assertNotIn('c_mg', kept)

    def test_general_goal_keeps_all(self):
        """goal_type=general 不过滤任何 chunk"""
        from app.rag.models import GoalType, KnowledgeChunk, KnowledgeCategory, SearchQuery
        r = self._build_retriever()
        chunks = [
            KnowledgeChunk(document_id='d1', title='增肌', content='c',
                           category=KnowledgeCategory.muscle_gain_standards,
                           goal_types=[GoalType.muscle_gain], chunk_id='c_mg'),
            KnowledgeChunk(document_id='d2', title='减脂', content='c',
                           category=KnowledgeCategory.fat_loss_standards,
                           goal_types=[GoalType.fat_loss], chunk_id='c_fl'),
        ]
        mg = self._make_mg(chunks)
        q = SearchQuery(query='test', goal_type=GoalType.general, top_k=10)
        rr = r._filter_and_rerank(mg, q)
        kept = {ch.chunk_id for ch, _, _ in rr}
        self.assertEqual(kept, {'c_mg', 'c_fl'})

    def test_no_goal_type_keeps_all(self):
        """未指定 goal_type 不过滤"""
        from app.rag.models import GoalType, KnowledgeChunk, KnowledgeCategory, SearchQuery
        r = self._build_retriever()
        chunks = [
            KnowledgeChunk(document_id='d1', title='增肌', content='c',
                           category=KnowledgeCategory.muscle_gain_standards,
                           goal_types=[GoalType.muscle_gain], chunk_id='c_mg'),
            KnowledgeChunk(document_id='d2', title='减脂', content='c',
                           category=KnowledgeCategory.fat_loss_standards,
                           goal_types=[GoalType.fat_loss], chunk_id='c_fl'),
        ]
        mg = self._make_mg(chunks)
        q = SearchQuery(query='test', top_k=10)
        rr = r._filter_and_rerank(mg, q)
        kept = {ch.chunk_id for ch, _, _ in rr}
        self.assertEqual(kept, {'c_mg', 'c_fl'})


class TrainingLevelFilteringTests(unittest.TestCase):
    """训练水平过滤：构造 chunk 直接测试 _filter_and_rerank。"""

    def _build_retriever(self):
        from app.rag.retriever import get_retriever
        r = get_retriever()
        r.initialize()
        return r

    def _make_mg(self, chunks, score=0.8):
        return {ch.chunk_id: (ch, score, 'vector') for ch in chunks}

    def _chunks(self):
        from app.rag.models import KnowledgeChunk, KnowledgeCategory
        return [
            KnowledgeChunk(document_id='d1', title='基础', content='c',
                           category=KnowledgeCategory.training_principles,
                           training_level='general', chunk_id='c_gen'),
            KnowledgeChunk(document_id='d2', title='新手', content='c',
                           category=KnowledgeCategory.training_principles,
                           training_level='beginner', chunk_id='c_beg'),
            KnowledgeChunk(document_id='d3', title='中级', content='c',
                           category=KnowledgeCategory.training_principles,
                           training_level='intermediate', chunk_id='c_int'),
            KnowledgeChunk(document_id='d4', title='高级', content='c',
                           category=KnowledgeCategory.training_principles,
                           training_level='advanced', chunk_id='c_adv'),
        ]

    def test_beginner_level(self):
        """beginner 查询保留 general + beginner，排除 intermediate + advanced"""
        from app.rag.models import SearchQuery
        r = self._build_retriever()
        mg = self._make_mg(self._chunks())
        q = SearchQuery(query='test', training_level='beginner', top_k=10)
        rr = r._filter_and_rerank(mg, q)
        kept = {ch.chunk_id for ch, _, _ in rr}
        self.assertIn('c_gen', kept)
        self.assertIn('c_beg', kept)
        self.assertNotIn('c_int', kept)
        self.assertNotIn('c_adv', kept)

    def test_intermediate_level(self):
        """intermediate 查询保留 general + beginner + intermediate"""
        from app.rag.models import SearchQuery
        r = self._build_retriever()
        mg = self._make_mg(self._chunks())
        q = SearchQuery(query='test', training_level='intermediate', top_k=10)
        rr = r._filter_and_rerank(mg, q)
        kept = {ch.chunk_id for ch, _, _ in rr}
        self.assertIn('c_gen', kept)
        self.assertIn('c_beg', kept)
        self.assertIn('c_int', kept)
        self.assertNotIn('c_adv', kept)

    def test_advanced_level(self):
        """advanced 查询保留全部等级"""
        from app.rag.models import SearchQuery
        r = self._build_retriever()
        mg = self._make_mg(self._chunks())
        q = SearchQuery(query='test', training_level='advanced', top_k=10)
        rr = r._filter_and_rerank(mg, q)
        kept = {ch.chunk_id for ch, _, _ in rr}
        self.assertEqual(kept, {'c_gen', 'c_beg', 'c_int', 'c_adv'})

    def test_no_level_keeps_all(self):
        """未指定 training_level 不过滤"""
        from app.rag.models import SearchQuery
        r = self._build_retriever()
        mg = self._make_mg(self._chunks())
        q = SearchQuery(query='test', top_k=10)
        rr = r._filter_and_rerank(mg, q)
        kept = {ch.chunk_id for ch, _, _ in rr}
        self.assertEqual(kept, {'c_gen', 'c_beg', 'c_int', 'c_adv'})

    def test_real_docs_contain_multiple_levels(self):
        """真实知识文档应包含多个训练水平"""
        from pathlib import Path
        from app.rag.indexer import load_all_documents
        _, chunks, _ = load_all_documents(Path('data/knowledge_docs'))
        levels = {c.training_level for c in chunks}
        self.assertIn('beginner', levels, "Should have beginner chunks")
        self.assertIn('intermediate', levels, "Should have intermediate chunks")
        self.assertIn('advanced', levels, "Should have advanced chunks")


class PageContextTests(unittest.TestCase):
    """页面上下文加分：current_page 影响排序。"""

    def _build_retriever(self):
        from app.rag.retriever import get_retriever
        r = get_retriever()
        r.initialize()
        return r

    def _make_mg(self, chunks, score=0.7):
        return {ch.chunk_id: (ch, score, 'vector') for ch in chunks}

    def test_pose_page_boosts_exercise_knowledge(self):
        """pose 页面应提升 exercise_technique 和 risk_rules 的分数"""
        from app.rag.models import SearchQuery, KnowledgeChunk, KnowledgeCategory
        r = self._build_retriever()
        chunks = [
            KnowledgeChunk(document_id='d1', title='深蹲', content='c',
                           category=KnowledgeCategory.exercise_technique, chunk_id='c_ex'),
            KnowledgeChunk(document_id='d2', title='营养', content='c',
                           category=KnowledgeCategory.nutrition_planning, chunk_id='c_np'),
        ]
        mg = self._make_mg(chunks)
        q_pose = SearchQuery(query='test', current_page='pose', top_k=10)
        rr = r._filter_and_rerank(mg, q_pose)
        scores = {ch.chunk_id: sc for ch, sc, _ in rr}
        self.assertGreater(scores['c_ex'], scores['c_np'],
                           "pose page should boost exercise_technique over nutrition")

    def test_food_page_boosts_nutrition(self):
        """food 页面应提升 nutrition_planning 和 chinese_meals"""
        from app.rag.models import SearchQuery, KnowledgeChunk, KnowledgeCategory
        r = self._build_retriever()
        chunks = [
            KnowledgeChunk(document_id='d1', title='营养', content='c',
                           category=KnowledgeCategory.nutrition_planning, chunk_id='c_np'),
            KnowledgeChunk(document_id='d2', title='深蹲', content='c',
                           category=KnowledgeCategory.exercise_technique, chunk_id='c_ex'),
        ]
        mg = self._make_mg(chunks)
        q_food = SearchQuery(query='test', current_page='food', top_k=10)
        rr = r._filter_and_rerank(mg, q_food)
        scores = {ch.chunk_id: sc for ch, sc, _ in rr}
        self.assertGreater(scores['c_np'], scores['c_ex'],
                           "food page should boost nutrition over exercise")

    def test_unknown_page_no_effect(self):
        """未知页面值不应改变结果"""
        from app.rag.models import SearchQuery, KnowledgeChunk, KnowledgeCategory
        r = self._build_retriever()
        chunks = [
            KnowledgeChunk(document_id='d1', title='A', content='c',
                           category=KnowledgeCategory.exercise_technique, chunk_id='c_a'),
        ]
        mg = self._make_mg(chunks, score=0.7)
        q = SearchQuery(query='test', current_page='nonexistent_page_xyz', top_k=10)
        rr = r._filter_and_rerank(mg, q)
        self.assertEqual(len(rr), 1)
        # 分数不应有页面加分（0.7 base + 0.02 general goal = 0.72 max）
        _, sc, _ = rr[0]
        self.assertLessEqual(sc, 0.75)

    def test_applicable_condition_boost(self):
        """applicable_conditions 匹配时应获得加分"""
        from app.rag.models import SearchQuery, KnowledgeChunk, KnowledgeCategory
        from app.rag.retriever import _PAGE_CONTEXT
        r = self._build_retriever()
        pose_conds = _PAGE_CONTEXT['pose']['conditions']
        chunks = [
            KnowledgeChunk(document_id='d1', title='A', content='c',
                           category=KnowledgeCategory.exercise_technique,
                           applicable_conditions=pose_conds, chunk_id='c_match'),
            KnowledgeChunk(document_id='d2', title='B', content='c',
                           category=KnowledgeCategory.exercise_technique,
                           applicable_conditions=[], chunk_id='c_nomatch'),
        ]
        mg = self._make_mg(chunks, score=0.7)
        q = SearchQuery(query='test', current_page='pose', top_k=10)
        rr = r._filter_and_rerank(mg, q)
        scores = {ch.chunk_id: sc for ch, sc, _ in rr}
        self.assertGreater(scores['c_match'], scores['c_nomatch'],
                           "Matching applicable_conditions should get a boost")

    def test_named_exercise_boosts_matching_technique(self):
        """An explicitly named exercise should outrank other technique chunks."""
        from app.rag.models import SearchQuery, KnowledgeChunk, KnowledgeCategory
        r = self._build_retriever()
        chunks = [
            KnowledgeChunk(
                document_id='d1', title='\u786c\u62c9 - \u5e38\u89c1\u9519\u8bef',
                content='\u786c\u62c9\u65f6\u4fdd\u6301\u8170\u690e\u4e2d\u7acb',
                category=KnowledgeCategory.exercise_technique,
                knowledge_role='correction', chunk_id='c_deadlift',
            ),
            KnowledgeChunk(
                document_id='d2', title='\u4fef\u5367\u6491 - \u5e38\u89c1\u9519\u8bef',
                content='\u584c\u8170\u4f1a\u589e\u52a0\u8170\u690e\u53d7\u4f24\u98ce\u9669',
                category=KnowledgeCategory.exercise_technique,
                knowledge_role='correction', chunk_id='c_pushup',
            ),
        ]
        mg = {
            'c_deadlift': (chunks[0], 0.62, 'hybrid'),
            'c_pushup': (chunks[1], 0.70, 'hybrid'),
        }
        q = SearchQuery(
            query='\u8170\u690e\u53d7\u4f24\u505a\u786c\u62c9\u6709\u4ec0\u4e48\u98ce\u9669',
            injuries=['back'], current_page='pose', top_k=10,
        )
        rr = r._filter_and_rerank(mg, q)
        self.assertEqual(rr[0][0].chunk_id, 'c_deadlift')


class DietaryRestrictionTests(unittest.TestCase):
    """饮食限制过滤：别名映射 + 知识角色区分。"""

    def _build_retriever(self):
        from app.rag.retriever import get_retriever
        r = get_retriever()
        r.initialize()
        return r

    def _make_mg(self, chunks, score=0.7):
        return {ch.chunk_id: (ch, score, 'vector') for ch in chunks}

    def test_egg_aliases_match(self):
        """dietary_restrictions=["egg"] 和 ["鸡蛋"] 应产生相同过滤结果"""
        from app.rag.models import SearchQuery, KnowledgeChunk, KnowledgeCategory
        r = self._build_retriever()
        # 包含"鸡蛋"的推荐 chunk
        rec = KnowledgeChunk(
            document_id='d1', title='早餐推荐', content='鸡蛋是优质蛋白质来源',
            category=KnowledgeCategory.nutrition_planning,
            knowledge_role='recommendation', chunk_id='c_egg',
        )
        gen = KnowledgeChunk(
            document_id='d2', title='通用知识', content='均衡饮食很重要',
            category=KnowledgeCategory.nutrition_planning,
            knowledge_role='general', chunk_id='c_gen',
        )
        mg = self._make_mg([rec, gen])
        q_egg = SearchQuery(query='test', dietary_restrictions=['egg'], top_k=10)
        q_cn = SearchQuery(query='test', dietary_restrictions=['鸡蛋'], top_k=10)
        rr_egg = r._filter_and_rerank(mg, q_egg)
        rr_cn = r._filter_and_rerank(mg, q_cn)
        ids_egg = {ch.chunk_id for ch, _, _ in rr_egg}
        ids_cn = {ch.chunk_id for ch, _, _ in rr_cn}
        self.assertEqual(ids_egg, ids_cn, "egg and 鸡蛋 should produce same filtering")

    def test_unsafe_recommendation_excluded(self):
        """推荐鸡蛋且无替代方案的 chunk 应被排除"""
        from app.rag.models import SearchQuery, KnowledgeChunk, KnowledgeCategory
        r = self._build_retriever()
        rec = KnowledgeChunk(
            document_id='d1', title='早餐推荐', content='鸡蛋是优质蛋白质来源',
            category=KnowledgeCategory.nutrition_planning,
            knowledge_role='recommendation', chunk_id='c_egg',
            safe_alternatives=[], contraindications=[],
        )
        mg = self._make_mg([rec])
        q = SearchQuery(query='test', dietary_restrictions=['egg'], top_k=10)
        rr = r._filter_and_rerank(mg, q)
        kept = {ch.chunk_id for ch, _, _ in rr}
        self.assertNotIn('c_egg', kept)

    def test_unrelated_contraindication_does_not_make_food_safe(self):
        """An unrelated medical contraindication must not bypass an allergy filter."""
        from app.rag.models import SearchQuery, KnowledgeChunk, KnowledgeCategory
        r = self._build_retriever()
        food_list = KnowledgeChunk(
            document_id='d1', title='Protein foods',
            content='\u9e21\u86cb\u662f\u5e38\u89c1\u9ad8\u86cb\u767d\u98df\u6750',
            category=KnowledgeCategory.nutrition_planning,
            knowledge_role='general', chunk_id='c_egg_list',
            contraindications=['kidney_disease'],
        )
        mg = self._make_mg([food_list])
        q = SearchQuery(query='protein', dietary_restrictions=['egg'], top_k=10)
        rr = r._filter_and_rerank(mg, q)
        kept = {ch.chunk_id for ch, _, _ in rr}
        self.assertNotIn('c_egg_list', kept)

    def test_risk_warning_preserved(self):
        """鸡蛋过敏风险警告应被保留"""
        from app.rag.models import SearchQuery, KnowledgeChunk, KnowledgeCategory
        r = self._build_retriever()
        risk = KnowledgeChunk(
            document_id='d1', title='鸡蛋过敏风险', content='鸡蛋是常见过敏原',
            category=KnowledgeCategory.risk_rules,
            knowledge_role='risk_warning', chunk_id='c_risk',
        )
        mg = self._make_mg([risk])
        q = SearchQuery(query='test', dietary_restrictions=['egg'], top_k=10)
        rr = r._filter_and_rerank(mg, q)
        kept = {ch.chunk_id for ch, _, _ in rr}
        self.assertIn('c_risk', kept)

    def test_alternative_preserved(self):
        """提供替代方案的知识应被保留"""
        from app.rag.models import SearchQuery, KnowledgeChunk, KnowledgeCategory
        r = self._build_retriever()
        alt = KnowledgeChunk(
            document_id='d1', title='无蛋早餐', content='可以用豆腐替代鸡蛋',
            category=KnowledgeCategory.nutrition_planning,
            knowledge_role='alternative', chunk_id='c_alt',
        )
        mg = self._make_mg([alt])
        q = SearchQuery(query='test', dietary_restrictions=['egg'], top_k=10)
        rr = r._filter_and_rerank(mg, q)
        kept = {ch.chunk_id for ch, _, _ in rr}
        self.assertIn('c_alt', kept)

    def test_general_protein_not_deleted(self):
        """通用蛋白质知识不应被误删"""
        from app.rag.models import SearchQuery, KnowledgeChunk, KnowledgeCategory
        r = self._build_retriever()
        gen = KnowledgeChunk(
            document_id='d1', title='蛋白质摄入', content='每公斤体重需要1.6g蛋白质',
            category=KnowledgeCategory.fat_loss_standards,
            knowledge_role='general', chunk_id='c_gen',
        )
        mg = self._make_mg([gen])
        q = SearchQuery(query='test', dietary_restrictions=['egg'], top_k=10)
        rr = r._filter_and_rerank(mg, q)
        kept = {ch.chunk_id for ch, _, _ in rr}
        self.assertIn('c_gen', kept)

    def test_multiple_restrictions(self):
        """多个限制同时生效"""
        from app.rag.models import SearchQuery, KnowledgeChunk, KnowledgeCategory
        r = self._build_retriever()
        egg_rec = KnowledgeChunk(
            document_id='d1', title='鸡蛋推荐', content='鸡蛋',
            category=KnowledgeCategory.nutrition_planning,
            knowledge_role='recommendation', chunk_id='c_egg',
        )
        milk_rec = KnowledgeChunk(
            document_id='d2', title='牛奶推荐', content='牛奶是乳制品',
            category=KnowledgeCategory.nutrition_planning,
            knowledge_role='recommendation', chunk_id='c_milk',
        )
        gen = KnowledgeChunk(
            document_id='d3', title='通用', content='均衡饮食',
            category=KnowledgeCategory.nutrition_planning,
            knowledge_role='general', chunk_id='c_gen',
        )
        mg = self._make_mg([egg_rec, milk_rec, gen])
        q = SearchQuery(query='test', dietary_restrictions=['egg', 'dairy'], top_k=10)
        rr = r._filter_and_rerank(mg, q)
        kept = {ch.chunk_id for ch, _, _ in rr}
        self.assertNotIn('c_egg', kept)
        self.assertNotIn('c_milk', kept)
        self.assertIn('c_gen', kept)


class InjuryKnowledgeRoleTests(unittest.TestCase):
    """伤病查询与知识角色：recommendation 被排除，risk_warning/correction 保留。"""

    def _build_retriever(self):
        from app.rag.retriever import get_retriever
        r = get_retriever()
        r.initialize()
        return r

    def _make_mg(self, chunks, score=0.7):
        return {ch.chunk_id: (ch, score, 'vector') for ch in chunks}

    def test_knee_query_preserves_squat_risk_warning(self):
        """膝盖伤病查询应保留深蹲风险警告"""
        from app.rag.models import SearchQuery, KnowledgeChunk, KnowledgeCategory
        r = self._build_retriever()
        risk = KnowledgeChunk(
            document_id='d1', title='深蹲 - 膝关节风险说明', content='膝关节伤病者应避免深蹲',
            category=KnowledgeCategory.exercise_technique,
            knowledge_role='risk_warning', risk_tags=['squat_knee_risk'],
            safe_alternatives=['臀桥'], chunk_id='c_risk',
        )
        mg = self._make_mg([risk])
        q = SearchQuery(query='test', injuries=['knee'], top_k=10)
        rr = r._filter_and_rerank(mg, q)
        kept = {ch.chunk_id for ch, _, _ in rr}
        self.assertIn('c_risk', kept)

    def test_knee_query_excludes_squat_recommendation(self):
        """膝盖伤病查询应排除深蹲推荐"""
        from app.rag.models import SearchQuery, KnowledgeChunk, KnowledgeCategory
        r = self._build_retriever()
        rec = KnowledgeChunk(
            document_id='d1', title='深蹲 - 深蹲标准', content='双脚与肩同宽',
            category=KnowledgeCategory.exercise_technique,
            knowledge_role='recommendation', contraindications=['knee_injury'],
            chunk_id='c_rec',
        )
        mg = self._make_mg([rec])
        q = SearchQuery(query='test', injuries=['knee'], top_k=10)
        rr = r._filter_and_rerank(mg, q)
        kept = {ch.chunk_id for ch, _, _ in rr}
        self.assertNotIn('c_rec', kept)

    def test_knee_query_preserves_squat_correction(self):
        """膝盖伤病查询应保留深蹲纠错知识"""
        from app.rag.models import SearchQuery, KnowledgeChunk, KnowledgeCategory
        r = self._build_retriever()
        corr = KnowledgeChunk(
            document_id='d1', title='深蹲 - 常见错误与纠正', content='膝盖内扣',
            category=KnowledgeCategory.exercise_technique,
            knowledge_role='correction', risk_tags=['squat_knee_risk'],
            chunk_id='c_corr',
        )
        mg = self._make_mg([corr])
        q = SearchQuery(query='test', injuries=['knee'], top_k=10)
        rr = r._filter_and_rerank(mg, q)
        kept = {ch.chunk_id for ch, _, _ in rr}
        self.assertIn('c_corr', kept)

    def test_back_query_preserves_deadlift_risk_warning(self):
        """腰椎伤病查询应保留硬拉风险警告"""
        from app.rag.models import SearchQuery, KnowledgeChunk, KnowledgeCategory
        r = self._build_retriever()
        risk = KnowledgeChunk(
            document_id='d1', title='硬拉 - 腰椎风险说明', content='腰椎伤病者应避免硬拉',
            category=KnowledgeCategory.exercise_technique,
            knowledge_role='risk_warning', risk_tags=['deadlift_back_risk'],
            safe_alternatives=['平板支撑'], chunk_id='c_risk',
        )
        mg = self._make_mg([risk])
        q = SearchQuery(query='test', injuries=['back'], top_k=10)
        rr = r._filter_and_rerank(mg, q)
        kept = {ch.chunk_id for ch, _, _ in rr}
        self.assertIn('c_risk', kept)

    def test_shoulder_query_preserves_bench_risk_warning(self):
        """肩部伤病查询应保留卧推风险警告"""
        from app.rag.models import SearchQuery, KnowledgeChunk, KnowledgeCategory
        r = self._build_retriever()
        risk = KnowledgeChunk(
            document_id='d1', title='卧推 - 肩关节风险说明', content='肩关节伤病者应避免卧推',
            category=KnowledgeCategory.exercise_technique,
            knowledge_role='risk_warning', risk_tags=['bench_shoulder_risk'],
            safe_alternatives=['地板卧推'], chunk_id='c_risk',
        )
        mg = self._make_mg([risk])
        q = SearchQuery(query='test', injuries=['shoulder'], top_k=10)
        rr = r._filter_and_rerank(mg, q)
        kept = {ch.chunk_id for ch, _, _ in rr}
        self.assertIn('c_risk', kept)

    def test_unrelated_exercise_not_wrongly_excluded(self):
        """无关动作不应被伤病查询错误排除"""
        from app.rag.models import SearchQuery, KnowledgeChunk, KnowledgeCategory
        r = self._build_retriever()
        pushup = KnowledgeChunk(
            document_id='d1', title='俯卧撑标准', content='身体一条直线',
            category=KnowledgeCategory.exercise_technique,
            knowledge_role='recommendation', contraindications=[],
            chunk_id='c_pushup',
        )
        mg = self._make_mg([pushup])
        q = SearchQuery(query='test', injuries=['knee'], top_k=10)
        rr = r._filter_and_rerank(mg, q)
        kept = {ch.chunk_id for ch, _, _ in rr}
        self.assertIn('c_pushup', kept, "Unrelated exercise should not be excluded for knee injury")


class EvaluationSuiteTests(unittest.TestCase):
    """Issue 7: 评测套件正确性。"""

    def test_all_cases_pass(self):
        """评测套件所有 case 应全部通过"""
        from app.rag.evaluate import run_evaluation
        result = run_evaluation()
        self.assertEqual(result["failed"], 0, f"Failed cases: {[r['id'] for r in result['results'] if not r['passed']]}")
        self.assertEqual(result["pass_rate"], 100.0)

    def test_insufficient_case_uses_flag(self):
        """证据不足 case 应检查 insufficient_evidence 标志而非分数阈值"""
        from app.rag.evaluate import _EVAL_CASES
        insuff_cases = [c for c in _EVAL_CASES if c.get("must_be_empty_or_insufficient")]
        self.assertGreater(len(insuff_cases), 0, "Should have at least one insufficient_evidence case")
        for c in insuff_cases:
            self.assertNotIn("max_score_threshold", c, f"Case {c['id']} should not use max_score_threshold")


class RollbackTests(unittest.TestCase):
    """索引重建回滚：使用 tempfile 隔离，不污染真实向量库。"""

    def test_reopen_failure_restores_old_index(self):
        """reopen 失败时应从备份恢复旧索引"""
        import tempfile
        from pathlib import Path
        from app.rag.models import KnowledgeChunk, KnowledgeCategory
        from app.rag.vectorstore import VectorStoreManager

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vs_dir = base / "vectorstore"
            vs_dir.mkdir()
            (vs_dir / "old-index-marker.txt").write_text("old")

            mgr = VectorStoreManager()
            mock_old_store = MagicMock()
            mock_old_store._client = MagicMock()
            mgr._store = mock_old_store

            mock_new_store = MagicMock()
            mock_new_store._collection.count.return_value = 5
            mock_new_store._client = MagicMock()

            chunks = [
                KnowledgeChunk(
                    document_id='d1', title='T', content='C',
                    category=KnowledgeCategory.fat_loss_standards,
                    chunk_id='chk_test',
                ),
            ]

            # from_documents 成功，但 Chroma() 构造函数 reopen 失败
            with patch("app.rag.vectorstore.Chroma") as MockChroma:
                MockChroma.from_documents.return_value = mock_new_store
                # Chroma() reopen 抛异常
                MockChroma.side_effect = RuntimeError("Chroma reopen failed")
                with patch("app.rag.vectorstore.VectorStoreManager._get_embeddings"):
                    with patch("app.rag.vectorstore._BASE_DIR", base):
                        with patch("app.rag.vectorstore._VECTORSTORE_DIR", vs_dir):
                            with self.assertRaises(RuntimeError):
                                mgr.index_chunks(chunks)

            # 断言：旧索引被恢复
            self.assertTrue((vs_dir / "old-index-marker.txt").exists(),
                            "Old index marker should be restored")
            # 断言：backup 被清理
            backup_dir = base / "vectorstore_backup"
            self.assertFalse(backup_dir.exists(), "Backup should be cleaned up")
            # 断言：tmp 被清理
            tmp_dir = base / "vectorstore_tmp"
            self.assertFalse(tmp_dir.exists(), "Tmp dir should be cleaned up")
            # 断言：manager._store is None
            self.assertIsNone(mgr._store, "Store should be None after rollback")

    def test_successful_swap_removes_backup(self):
        """成功重建后 backup 应被清理，manager 持有新 store"""
        import tempfile
        from pathlib import Path
        from app.rag.models import KnowledgeChunk, KnowledgeCategory
        from app.rag.vectorstore import VectorStoreManager

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vs_dir = base / "vectorstore"
            # 无旧索引

            mgr = VectorStoreManager()

            mock_new_store = MagicMock()
            mock_new_store._collection.count.return_value = 5
            mock_new_client = MagicMock()
            mock_new_store._client = mock_new_client

            chunks = [
                KnowledgeChunk(
                    document_id='d1', title='T', content='C',
                    category=KnowledgeCategory.fat_loss_standards,
                    chunk_id='chk_test',
                ),
            ]

            with patch("app.rag.vectorstore.Chroma") as MockChroma:
                MockChroma.from_documents.return_value = mock_new_store
                MockChroma.return_value = mock_new_store
                with patch("app.rag.vectorstore.VectorStoreManager._get_embeddings"):
                    with patch("app.rag.vectorstore._BASE_DIR", base):
                        with patch("app.rag.vectorstore._VECTORSTORE_DIR", vs_dir):
                            stats = mgr.index_chunks(chunks)
                            reloaded = VectorStoreManager()

            # 断言：stats 正确
            self.assertEqual(stats.total_chunks, 1)
            self.assertEqual(stats.total_documents, 1)
            self.assertEqual(stats.content_hashes, 1)
            self.assertIsNotNone(stats.last_rebuild)
            self.assertEqual(reloaded._stats.model_dump(), stats.model_dump())
            # 断言：manager 持有新 store
            self.assertIs(mgr._store, mock_new_store)
            # 断言：backup 不残留
            backup_dir = base / "vectorstore_backup"
            self.assertFalse(backup_dir.exists(), "Backup should not remain after success")


class ChunkMetadataTests(unittest.TestCase):
    """验证 chunk 包含新增的元数据字段。"""

    def test_chunks_have_risk_tags(self):
        """加载的 chunks 应包含 risk_tags 字段"""
        from pathlib import Path
        from app.rag.indexer import load_document
        docs_dir = Path(__file__).parent.parent / "data" / "knowledge_docs"
        doc, chunks, err = load_document(docs_dir / "squat_technique.md")
        self.assertIsNotNone(doc)
        self.assertGreater(len(chunks), 0)
        # 深蹲文档应有 risk_tags
        has_risk = any(ch.risk_tags for ch in chunks)
        self.assertTrue(has_risk, "Squat technique should have risk_tags")

    def test_chunks_have_safe_alternatives(self):
        """深蹲文档应有 safe_alternatives"""
        from pathlib import Path
        from app.rag.indexer import load_document
        docs_dir = Path(__file__).parent.parent / "data" / "knowledge_docs"
        doc, chunks, err = load_document(docs_dir / "squat_technique.md")
        self.assertIsNotNone(doc)
        has_alts = any(ch.safe_alternatives for ch in chunks)
        self.assertTrue(has_alts, "Squat technique should have safe_alternatives")

    def test_chunks_have_contraindications(self):
        """深蹲文档应有 contraindications"""
        from pathlib import Path
        from app.rag.indexer import load_document
        docs_dir = Path(__file__).parent.parent / "data" / "knowledge_docs"
        doc, chunks, err = load_document(docs_dir / "squat_technique.md")
        self.assertIsNotNone(doc)
        has_contra = any(ch.contraindications for ch in chunks)
        self.assertTrue(has_contra, "Squat technique should have contraindications")

    def test_deprecated_doc_skipped(self):
        """已废弃的 exercise_technique.md 不应被加载"""
        from pathlib import Path
        from app.rag.indexer import load_all_documents
        docs_dir = Path(__file__).parent.parent / "data" / "knowledge_docs"
        docs, _, rpt = load_all_documents(docs_dir)
        self.assertEqual(rpt.deprecated, 1, "Should have 1 deprecated doc")


class VectorstoreMetadataTests(unittest.TestCase):
    """验证 vectorstore 元数据包含新字段。"""

    def test_similarity_search_returns_risk_tags(self):
        """vectorstore 搜索结果应包含 risk_tags"""
        from app.rag.vectorstore import get_vectorstore_manager
        vs = get_vectorstore_manager()
        results = vs.similarity_search("深蹲膝盖", k=5)
        self.assertGreater(len(results), 0)
        # 检查是否有 chunk 携带 risk_tags
        has_risk = any(ch.risk_tags for ch, _ in results)
        self.assertTrue(has_risk, "Search results should include risk_tags from metadata")


if __name__ == "__main__":
    unittest.main()
