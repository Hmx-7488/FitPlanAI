"""RAG hybrid retriever."""
from __future__ import annotations
import logging
import time
from pathlib import Path

from app.rag.models import GoalType, RetrievedChunk, SearchQuery, SearchResult
from app.rag.indexer import load_all_documents
from app.rag.keyword_index import KeywordIndex
from app.rag.vectorstore import get_vectorstore_manager

logger = logging.getLogger(__name__)
_DATA_DIR = Path(__file__).parent.parent.parent / "data" / "knowledge_docs"
_INSUFF_THRESHOLD = 0.15


class HybridRetriever:
    def __init__(self):
        self._kw: KeywordIndex | None = None
        self._ok = False

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
        vr = vs.similarity_search(q.query, k=q.top_k * 2, filter_dict=fdict)

        kr = []
        if self._kw:
            hits = self._kw.search(q.query, top_k=q.top_k * 2)
            # 关键词结果也按分类过滤
            if q.categories:
                cat_vals = {c.value for c in q.categories}
                hits = [(c, s) for c, s in hits if c.category.value in cat_vals]
            kr = [(c, s / 10) for c, s in hits]

        mg = self._merge(vr, kr)
        rr = self._rerank(mg, q)

        out = []
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
        ins = not out or out[0].score < _INSUFF_THRESHOLD
        return SearchResult(
            query=q.query,
            documents=out,
            insufficient_evidence=ins,
            total_candidates=len(vr) + len(kr),
            retrieval_time_ms=round((time.time() - t0) * 1000, 1),
        )

    def _build_chroma_filter(self, q: SearchQuery) -> dict | None:
        """构建 Chroma where 过滤器。goal_type/injuries 存储为逗号分隔字符串，
        Chroma 无法直接匹配，留给 _rerank 做后过滤。"""
        c: dict = {}
        if q.categories:
            c["category"] = {"$in": [x.value for x in q.categories]}
        return c or None

    def _merge(self, vr, kr):
        m: dict = {}
        for ch, sc in vr:
            if ch.chunk_id in m:
                ec, es, _ = m[ch.chunk_id]
                m[ch.chunk_id] = (ec, max(es, sc), "hybrid")
            else:
                m[ch.chunk_id] = (ch, sc, "vector")
        for ch, sc in kr:
            if ch.chunk_id in m:
                ec, es, _ = m[ch.chunk_id]
                m[ch.chunk_id] = (ec, max(es, sc), "hybrid")
            else:
                m[ch.chunk_id] = (ch, sc, "keyword")
        return m

    def _rerank(self, mg, q: SearchQuery):
        rs = []
        for cid, (ch, bs, m) in mg.items():
            # 硬过滤：伤病禁忌 — 命中 contraindications 的知识块直接排除
            if q.injuries:
                skip = False
                for inj in q.injuries:
                    for co in (ch.contraindications or []):
                        if inj.lower() in co.lower():
                            skip = True
                            break
                    if skip:
                        break
                if skip:
                    continue

            s = bs
            if q.goal_type and q.goal_type in ch.goal_types:
                s += 0.1
            elif GoalType.general in ch.goal_types:
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
            rs.append((ch, max(0.0, min(1.0, s)), m))
        rs.sort(key=lambda x: x[1], reverse=True)
        return rs

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
        }


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
