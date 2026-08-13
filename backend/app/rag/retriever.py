"""RAG hybrid retriever."""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from app.rag.models import (
    GoalType, KnowledgeCategory, KnowledgeChunk,
    RetrievedChunk, SearchQuery, SearchResult,
)
from app.rag.indexer import load_all_documents
from app.rag.keyword_index import KeywordIndex
from app.rag.vectorstore import KnowledgeVectorUnavailable, get_vectorstore_manager

logger = logging.getLogger(__name__)
_DATA_DIR = Path(__file__).parent.parent.parent / "data" / "knowledge_docs"

# ── 证据不足判定阈值（集中配置）──
# top-1 分数低于此值 → 证据不足
_SCORE_FLOOR = 0.30
# top-1 分数高于此值 → 直接判为证据充分（跳过覆盖率检查）
_SCORE_CEILING = 0.55
# 查询关键 token 在结果中的覆盖率低于此值 → 证据不足（仅在灰色区间生效）
_COVERAGE_THRESHOLD = 0.25
_RRF_K = 60
# 训练水平兼容性映射：查询级别 → 可接受的 chunk 级别集合
_LEVEL_COMPAT: dict[str, set[str]] = {
    "general": {"general"},
    "beginner": {"general", "beginner"},
    "intermediate": {"general", "beginner", "intermediate"},
    "advanced": {"general", "beginner", "intermediate", "advanced"},
}

# ── 页面上下文映射 ──
_PAGE_CONTEXT: dict[str, dict] = {
    "plan": {
        "preferred_categories": [
            "fat_loss_standards", "muscle_gain_standards",
            "nutrition_planning", "training_principles",
        ],
        "conditions": ["plan_generation"],
    },
    "food": {
        "preferred_categories": ["nutrition_planning", "chinese_meals"],
        "conditions": ["food_recognition", "recipe_generation"],
    },
    "meal": {
        "preferred_categories": ["nutrition_planning", "chinese_meals"],
        "conditions": ["meal_analysis"],
    },
    "pose": {
        "preferred_categories": ["exercise_technique", "risk_rules"],
        "conditions": ["pose_analysis"],
    },
    "body": {
        "preferred_categories": [
            "fat_loss_standards", "muscle_gain_standards", "risk_rules",
        ],
        "conditions": ["body_analysis"],
    },
}

# ── 饮食限制别名映射 ──
_DIETARY_ALIASES: dict[str, set[str]] = {
    "egg": {"egg", "鸡蛋", "蛋类", "蛋制品"},
    "dairy": {"dairy", "milk", "乳制品", "牛奶", "奶酪"},
    "peanut": {"peanut", "花生", "花生酱"},
    "gluten": {"gluten", "麸质", "小麦", "面筋"},
    "seafood": {"seafood", "海鲜", "虾", "蟹", "贝类", "三文鱼"},
}

_EXERCISE_ALIASES: dict[str, set[str]] = {
    "squat": {"squat", "深蹲"},
    "deadlift": {"deadlift", "硬拉"},
    "bench_press": {"bench press", "bench_press", "卧推"},
    "push_up": {"push up", "push-up", "push_up", "俯卧撑"},
    "pull_up": {"pull up", "pull-up", "pull_up", "引体向上"},
}


def _matched_concepts(text: str, aliases: dict[str, set[str]]) -> set[str]:
    normalized = text.lower()
    return {
        concept
        for concept, terms in aliases.items()
        if any(term in normalized for term in terms)
    }


class HybridRetriever:
    def __init__(self):
        self._kw: KeywordIndex | None = None
        self._ok = False
        self._last_search_diagnostics: dict[str, object] = {
            "vector_state": "not_queried",
            "degraded": False,
        }

    def initialize(self):
        if self._ok:
            return
        _, chunks, _ = load_all_documents(_DATA_DIR)
        if not chunks:
            self._ok = True
            return
        self._kw = KeywordIndex()
        self._kw.build(chunks)
        self._ok = True

    def search(self, q: SearchQuery) -> SearchResult:
        t0 = time.time()
        self.initialize()
        fdict = self._build_chroma_filter(q)
        vs = get_vectorstore_manager()
        vector_state = "ok"
        degraded = False
        try:
            vr = vs.similarity_search(q.query, k=q.top_k * 2, filter_dict=fdict)
            if not vr:
                vector_state = "empty"
        except KnowledgeVectorUnavailable as exc:
            vr = []
            vector_state = "unavailable"
            degraded = True
            logger.warning(
                "Knowledge retrieval degraded to keyword channel",
                extra={"error_type": type(exc.__cause__ or exc).__name__},
            )

        kr = []
        if self._kw:
            hits = self._kw.search(q.query, top_k=q.top_k * 2)
            if q.categories:
                cat_vals = {c.value for c in q.categories}
                hits = [(c, s) for c, s in hits if c.category.value in cat_vals]
            kr = [(c, s / 10) for c, s in hits]

        mg = self._merge(vr, kr)
        rr = self._filter_and_rerank(mg, q)

        out = []
        # Fusion scores are pure rank-derived RRF values. Evidence sufficiency
        # separately uses lexical coverage so an unrelated channel rank cannot
        # be mistaken for semantic confidence.
        raw_scores = [bs for _, bs, _ in mg.values()]
        raw_top = max(raw_scores) if raw_scores else 0.0

        for ch, sc, m in rr[: q.top_k]:
            ev = ch.evidence_level.value if hasattr(ch.evidence_level, "value") else str(ch.evidence_level)
            cat = ch.category.value if hasattr(ch.category, "value") else str(ch.category)
            out.append(RetrievedChunk(
                chunk_id=ch.chunk_id,
                document_id=ch.document_id,
                title=ch.title,
                content=ch.content,
                category=cat,
                source_name=ch.source_name,
                source_url=ch.source_url,
                evidence_level=ev,
                applicable_conditions=[c for c in (ch.applicable_conditions or []) if c],
                score=round(sc, 4),
                retrieval_method=m,
            ))

        ins = self._assess_evidence(q.query, out, raw_top_score=raw_top)
        self._last_search_diagnostics = {
            "vector_state": vector_state,
            "degraded": degraded,
            "vector_candidates": len(vr),
            "keyword_candidates": len(kr),
        }
        return SearchResult(
            query=q.query,
            documents=out if not ins else [],
            insufficient_evidence=ins,
            total_candidates=len(vr) + len(kr),
            retrieval_time_ms=round((time.time() - t0) * 1000, 1),
        )

    # ── Chroma 元数据过滤 ──

    def _build_chroma_filter(self, q: SearchQuery) -> dict | None:
        c: dict = {}
        if q.categories:
            c["category"] = {"$in": [x.value for x in q.categories]}
        return c or None

    # ── 合并去重 ──

    def _merge(self, vr, kr):
        # Reciprocal Rank Fusion compares ranks rather than raw Chroma relevance
        # and BM25 scores, whose numeric scales are unrelated. Normalize by the
        # theoretical two-channel maximum so downstream evidence scores stay in
        # the established 0..1 contract.
        entries: dict[str, dict[str, object]] = {}
        for channel, results in (("vector", vr), ("keyword", kr)):
            for rank, (chunk, _raw_score) in enumerate(results, start=1):
                item = entries.setdefault(
                    chunk.chunk_id,
                    {"chunk": chunk, "channels": set(), "rrf": 0.0},
                )
                channels = item["channels"]
                assert isinstance(channels, set)
                if channel in channels:
                    continue
                channels.add(channel)
                item["rrf"] = float(item["rrf"]) + 1 / (_RRF_K + rank)

        maximum = 2 / (_RRF_K + 1)
        merged: dict[str, tuple[KnowledgeChunk, float, str]] = {}
        for chunk_id, item in entries.items():
            channels = item["channels"]
            assert isinstance(channels, set)
            method = "hybrid" if len(channels) > 1 else next(iter(channels))
            merged[chunk_id] = (
                item["chunk"],
                min(1.0, float(item["rrf"]) / maximum),
                method,
            )
        return merged

    # ── 过滤 + 重排序 ──

    def _filter_and_rerank(self, mg, q: SearchQuery):
        # 页面上下文
        page_ctx = _PAGE_CONTEXT.get(q.current_page, {}) if q.current_page else {}
        page_cat_set = set(page_ctx.get("preferred_categories", []))
        page_conds = set(page_ctx.get("conditions", []))
        query_exercises = _matched_concepts(q.query, _EXERCISE_ALIASES)

        rs = []
        for cid, (ch, bs, m) in mg.items():
            # ── 硬过滤 ──

            # 1) goal_type 兼容性：general 块对所有目标可用；
            #    仅 fat_loss 块不返回给 muscle_gain 查询，反之亦然。
            if q.goal_type and q.goal_type != GoalType.general:
                gts = set(ch.goal_types or [GoalType.general])
                if GoalType.general not in gts and q.goal_type not in gts:
                    continue

            # 2) training_level 兼容性
            if q.training_level and q.training_level != "general":
                chunk_level = getattr(ch, "training_level", "general") or "general"
                if chunk_level != "general":
                    compat = _LEVEL_COMPAT.get(q.training_level, {"general", q.training_level})
                    if chunk_level not in compat:
                        continue

            # 3) dietary_restrictions：使用别名映射检查
            if q.dietary_restrictions:
                chunk_text = " ".join([
                    " ".join(ch.tags or []),
                    " ".join(ch.applicable_conditions or []),
                    ch.content[:300],
                ]).lower()
                blocked = False
                for restriction in q.dietary_restrictions:
                    r = restriction.lower().strip()
                    if not r:
                        continue
                    # 展开别名
                    aliases = _DIETARY_ALIASES.get(r, {r})
                    matched = any(a in chunk_text for a in aliases)
                    kr = getattr(ch, "knowledge_role", "general") or "general"
                    if matched:
                        # 风险警告和替代方案知识不被排除
                        if (
                            kr in ("risk_warning", "alternative")
                            or ch.category == KnowledgeCategory.risk_rules
                        ):
                            continue
                        # 明确提供安全替代方案的知识可保留；其他禁忌字段
                        # 可能与当前过敏原无关，不能据此绕过过滤。
                        if ch.safe_alternatives:
                            continue
                        blocked = True
                        break
                if blocked:
                    continue

            # 4) 伤病过滤 — 区分风险知识和动作推荐
            if q.injuries:
                kr = getattr(ch, "knowledge_role", "general") or "general"
                is_risk_knowledge = (
                    ch.category == KnowledgeCategory.risk_rules
                    or bool(ch.risk_tags)
                    or kr == "risk_warning"
                )
                if not is_risk_knowledge:
                    # 非风险知识：检查 contraindications
                    skip = False
                    for inj in q.injuries:
                        inj_l = inj.lower()
                        for co in (ch.contraindications or []):
                            if inj_l in co.lower():
                                skip = True
                                break
                        if skip:
                            break
                    if skip:
                        continue

            # ── 重排序加分 ──
            s = bs
            if q.goal_type and q.goal_type in ch.goal_types:
                s += 0.1
            elif GoalType.general in (ch.goal_types or []):
                s += 0.02
            ev = ch.evidence_level.value if hasattr(ch.evidence_level, "value") else str(ch.evidence_level)
            if ev == "guideline":
                s += 0.05
            elif ev == "research":
                s += 0.03
            elif ev == "expert":
                s += 0.01
            if q.categories and ch.category in q.categories:
                s += 0.08
            # 页面上下文加分（有限，不会把低相关结果提升为有效证据）
            cat_val = ch.category.value if hasattr(ch.category, "value") else str(ch.category)
            if page_cat_set and cat_val in page_cat_set:
                s += 0.05
            chunk_conds = set(ch.applicable_conditions or [])
            if page_conds and chunk_conds & page_conds:
                s += 0.03
            # 查询明确指定动作时，优先同一动作的知识，并降低其他动作
            # 因通用风险词（腰椎、受伤、风险）造成的误排。
            if query_exercises:
                chunk_text = " ".join([ch.title, ch.topic, " ".join(ch.tags or [])])
                chunk_exercises = _matched_concepts(chunk_text, _EXERCISE_ALIASES)
                if query_exercises & chunk_exercises:
                    s += 0.12
                elif ch.category == KnowledgeCategory.exercise_technique and chunk_exercises:
                    s -= 0.10
            rs.append((ch, max(0.0, min(1.0, s)), m))
        rs.sort(key=lambda x: x[1], reverse=True)
        return rs

    # ── 证据不足判定（多信号）──

    @staticmethod
    def _assess_evidence(
        query: str, docs: list[RetrievedChunk],
        raw_top_score: float = 0.0,
    ) -> bool:
        """多信号证据不足判定（三级策略）：
        使用 rerank 前的原始合并分数（raw_top_score）做判定，避免 reranking bonus 虚高。
        1. 无结果 → 证据不足
        2. raw_top_score < _SCORE_FLOOR → 证据不足
        3. raw_top_score >= _SCORE_CEILING → 证据充分（高置信度）
        4. 灰色区间 (_SCORE_FLOOR ~ _SCORE_CEILING)：查询关键 token 覆盖率 < _COVERAGE_THRESHOLD → 证据不足
        """
        if not docs:
            return True
        normalized_query = re.sub(r"\s+", "", query.lower())
        categories = {document.category for document in docs}
        has_risk_evidence = "risk_rules" in categories
        safety_query = (
            any(
                cue in normalized_query
                for cue in (
                    "受伤", "伤病", "疼痛", "膝盖", "膝关节", "腰椎",
                    "肩关节", "过敏", "不耐受",
                )
            )
            or bool(
                re.search(
                    r"(?:每天|每日|一天)?(?:只吃|仅吃|摄入)?.{0,3}[1-8]\d{2}(?:大卡|千卡|kcal)",
                    normalized_query,
                )
            )
        )
        if safety_query and has_risk_evidence:
            return False
        q_tokens = _extract_query_tokens(query)
        if q_tokens:
            combined_text = " ".join(
                document.title + " " + document.content[:300]
                for document in docs
            ).lower()
            hits = sum(1 for token in q_tokens if token in combined_text)
            coverage = hits / len(q_tokens)
            # Partial overlap with poor coverage (for example a query that only
            # shares “减脂” while asking about unsupported quantum mechanics)
            # remains insufficient even if both channels rank it first.
            if 0 < hits and coverage < _COVERAGE_THRESHOLD:
                return True
        # 优先使用原始合并分数；向后兼容时回退到 reranked score
        top_score = raw_top_score if raw_top_score > 0 else docs[0].score
        if top_score < _SCORE_FLOOR:
            return True
        if top_score >= _SCORE_CEILING:
            return False
        # 灰色区间：用覆盖率辅助判定
        if not q_tokens:
            return False
        if hits == 0:
            return True
        if coverage < _COVERAGE_THRESHOLD:
            return True
        return False

    # ── 管理操作 ──

    def rebuild(self):
        _, chunks, report = load_all_documents(_DATA_DIR)
        if not chunks:
            return {"error": "No chunks", "report": report.model_dump()}
        vs = get_vectorstore_manager()
        stats = vs.index_chunks(chunks)
        self._kw = KeywordIndex()
        self._kw.build(chunks)
        self._ok = True
        return {"stats": stats.model_dump(), "report": report.model_dump()}

    def get_status(self):
        vs = get_vectorstore_manager()
        stats = vs.get_stats()
        return {
            "vectorstore": stats.model_dump(),
            "keyword_index": {
                "initialized": self._ok,
                "chunks": len(self._kw._chunks) if self._kw else 0,
            },
            "last_search": dict(self._last_search_diagnostics),
        }


def _extract_query_tokens(query: str) -> list[str]:
    """提取查询中有意义的 token（中文 bigram + 英文单词，去停用词）。"""
    tokens = []
    # 英文单词（≥2 字符）
    for t in re.findall(r"[a-z]{2,}", query.lower()):
        tokens.append(t)
    # 中文 bigram
    cjk = re.findall(r"[一-鿿]+", query)
    for seg in cjk:
        if len(seg) >= 2:
            for i in range(len(seg) - 1):
                tokens.append(seg[i:i + 2])
        tokens.append(seg)
    # 去重
    return list(dict.fromkeys(tokens))


# ── 单例 ──

_inst: HybridRetriever | None = None


def get_retriever() -> HybridRetriever:
    global _inst
    if _inst is None:
        _inst = HybridRetriever()
    return _inst


def retrieve_knowledge(query: str, k: int = 3) -> list[str]:
    """向后兼容接口 — 内部使用 HybridRetriever。"""
    from app.rag.models import SearchQuery
    r = get_retriever()
    res = r.search(SearchQuery(query=query, top_k=k))
    return [d.content for d in res.documents]
