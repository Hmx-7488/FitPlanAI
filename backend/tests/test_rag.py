"""Tests for RAG knowledge layer."""
import unittest
from pathlib import Path
from app.rag.models import (
    DocStatus, EvidenceLevel, GoalType, KnowledgeCategory,
    KnowledgeChunk, KnowledgeDocument, SearchQuery, content_hash, make_stable_id,
)
from app.rag.indexer import parse_frontmatter, load_document, load_all_documents
from app.rag.keyword_index import KeywordIndex


class StableIdTests(unittest.TestCase):
    def test_same_content_same_id(self):
        self.assertEqual(make_stable_id("x", "doc"), make_stable_id("x", "doc"))
    def test_different_content_different_id(self):
        self.assertNotEqual(make_stable_id("a", "doc"), make_stable_id("b", "doc"))
    def test_content_hash_stable(self):
        self.assertEqual(content_hash("test"), content_hash("test"))
        self.assertEqual(content_hash("  test  "), content_hash("test"))
        self.assertNotEqual(content_hash("a"), content_hash("b"))


class DocumentModelTests(unittest.TestCase):
    def test_valid_document(self):
        doc = KnowledgeDocument(title="X", category=KnowledgeCategory.fat_loss_standards, source_name="S", evidence_level=EvidenceLevel.guideline)
        self.assertTrue(doc.document_id.startswith("doc_"))
    def test_guideline_requires_source(self):
        with self.assertRaises(Exception):
            KnowledgeDocument(title="X", category=KnowledgeCategory.fat_loss_standards, evidence_level=EvidenceLevel.guideline)
    def test_internal_no_source(self):
        doc = KnowledgeDocument(title="X", category=KnowledgeCategory.risk_rules)
        self.assertEqual(doc.evidence_level, EvidenceLevel.internal)


class ChunkModelTests(unittest.TestCase):
    def test_auto_id_and_hash(self):
        ch = KnowledgeChunk(document_id="d", title="T", content="C")
        self.assertTrue(ch.chunk_id.startswith("chk_"))
        self.assertTrue(len(ch.content_hash) > 0)
    def test_tags_normalized(self):
        ch = KnowledgeChunk(document_id="d", title="T", content="C", tags=["  A ", "B"])
        self.assertEqual(ch.tags, ["a", "b"])


class FrontmatterTests(unittest.TestCase):
    def test_parses_yaml(self):
        meta, body = parse_frontmatter("---\ntitle: T\ncategory: fat_loss_standards\n---\nBody")
        self.assertEqual(meta["title"], "T")
        self.assertIn("Body", body)
    def test_no_frontmatter(self):
        meta, body = parse_frontmatter("# Just markdown")
        self.assertEqual(meta, {})


class DocumentLoadingTests(unittest.TestCase):
    DIR = Path(__file__).parent.parent / "data" / "knowledge_docs"
    def test_loads_all(self):
        docs, chunks, rpt = load_all_documents(self.DIR)
        self.assertGreater(len(docs), 0)
        self.assertGreater(len(chunks), 0)
        self.assertEqual(rpt.failed, 0)
    def test_all_categories(self):
        docs, _, _ = load_all_documents(self.DIR)
        cats = {d.category for d in docs}
        self.assertIn(KnowledgeCategory.fat_loss_standards, cats)
        self.assertIn(KnowledgeCategory.risk_rules, cats)
        self.assertIn(KnowledgeCategory.exercise_technique, cats)
    def test_chunks_have_metadata(self):
        _, chunks, _ = load_all_documents(self.DIR)
        for ch in chunks[:5]:
            self.assertTrue(ch.chunk_id)
            self.assertTrue(ch.content)
    def test_no_duplicate_hashes(self):
        _, chunks, _ = load_all_documents(self.DIR)
        hashes = [ch.content_hash for ch in chunks]
        self.assertEqual(len(hashes), len(set(hashes)))
    def test_single_doc_load(self):
        doc, chs, err = load_document(self.DIR / "fat_loss_core_principles.md")
        self.assertIsNotNone(doc)
        self.assertGreater(len(chs), 0)
        self.assertEqual(err, "")


class KeywordIndexTests(unittest.TestCase):
    def setUp(self):
        self.chunks = [
            KnowledgeChunk(document_id="d1", title="减脂热量", content="安全热量缺口300-500kcal", category=KnowledgeCategory.fat_loss_standards, goal_types=[GoalType.fat_loss]),
            KnowledgeChunk(document_id="d2", title="增肌蛋白质", content="增肌期每公斤1.8-2.4g蛋白质", category=KnowledgeCategory.muscle_gain_standards, goal_types=[GoalType.muscle_gain]),
            KnowledgeChunk(document_id="d3", title="膝关节禁忌", content="膝盖受伤避免深蹲跳跃", category=KnowledgeCategory.risk_rules, contraindications=["knee_injury"]),
        ]
        self.kw = KeywordIndex()
        self.kw.build(self.chunks)
    def test_relevant_results(self):
        r = self.kw.search("减脂 热量", top_k=3)
        self.assertGreater(len(r), 0)
        self.assertEqual(r[0][0].document_id, "d1")
    def test_no_results_for_unrelated(self):
        r = self.kw.search("量子力学", top_k=3)
        self.assertEqual(len(r), 0)
    def test_chinese_matching(self):
        r = self.kw.search("膝盖", top_k=3)
        self.assertGreater(len(r), 0)
        self.assertEqual(r[0][0].document_id, "d3")


class SearchQueryTests(unittest.TestCase):
    def test_defaults(self):
        q = SearchQuery(query="test")
        self.assertEqual(q.top_k, 5)
        self.assertIsNone(q.goal_type)


if __name__ == "__main__":
    unittest.main()
