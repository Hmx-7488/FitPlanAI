"""RAG knowledge indexer - document parsing, chunking, dedup."""
from __future__ import annotations
import re, time, logging
from pathlib import Path
from typing import Optional
import yaml
from app.rag.models import (
    DocStatus, EvidenceLevel, GoalType, ImportReport,
    KnowledgeCategory, KnowledgeChunk, KnowledgeDocument, content_hash,
)

logger = logging.getLogger(__name__)
_FM_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)
_HD_RE = re.compile(r'^(#{1,3})\s+(.+)$', re.MULTILINE)
# 章节级元数据注释：<!-- key: value -->
_META_COMMENT_RE = re.compile(r'<!--\s*(\w+)\s*:\s*(.+?)\s*-->')


def parse_frontmatter(text: str) -> tuple[dict, str]:
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    body = text[m.end():]
    try:
        meta = yaml.safe_load(m.group(1))
        return (meta if isinstance(meta, dict) else {}), body
    except yaml.YAMLError:
        return {}, body


def _norm_list(v) -> list[str]:
    if not v:
        return []
    if isinstance(v, str):
        return [v.strip().lower()]
    if isinstance(v, list):
        return [str(x).strip().lower() for x in v if x]
    return []


def _build_doc(meta: dict, body: str) -> Optional[KnowledgeDocument]:
    title = str(meta.get("title", "")).strip()
    if not title:
        return None
    try:
        cat = KnowledgeCategory(str(meta.get("category", "")).strip())
    except ValueError:
        cat = KnowledgeCategory.fat_loss_standards
    try:
        ev = EvidenceLevel(str(meta.get("evidence_level", "internal")).strip())
    except ValueError:
        ev = EvidenceLevel.internal
    try:
        st = DocStatus(str(meta.get("status", "active")).strip())
    except ValueError:
        st = DocStatus.active
    pa, ra = meta.get("published_at"), meta.get("reviewed_at")
    from datetime import date as _d
    if isinstance(pa, str):
        try:
            pa = _d.fromisoformat(pa)
        except Exception:
            pa = None
    if isinstance(ra, str):
        try:
            ra = _d.fromisoformat(ra)
        except Exception:
            ra = None
    try:
        return KnowledgeDocument(
            title=title, category=cat,
            source_name=str(meta.get("source_name", "")),
            source_url=str(meta.get("source_url", "")),
            published_at=pa, reviewed_at=ra,
            evidence_level=ev, version=str(meta.get("version", "1.0")),
            status=st, content_hash=content_hash(body),
        )
    except Exception as e:
        logger.warning("Doc build failed: %s", e)
        return None


def _parse_chapter_meta(text_before_heading: str) -> dict:
    """从标题前的 HTML 注释中解析章节级元数据。

    支持格式：
        <!-- knowledge_role: recommendation -->
        <!-- contraindications: [knee_injury] -->
        <!-- training_level: beginner -->
    """
    result = {}
    for m in _META_COMMENT_RE.finditer(text_before_heading):
        key, val = m.group(1).strip(), m.group(2).strip()
        # 解析列表值 [a, b, c]
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            result[key] = [v.strip() for v in inner.split(",") if v.strip()] if inner else []
        else:
            result[key] = val
    return result


def _split(body: str, doc: KnowledgeDocument, meta: dict) -> list[KnowledgeChunk]:
    chunks = []
    tags = _norm_list(meta.get("tags", []))
    gt_strs = _norm_list(meta.get("goal_types", []))
    conds = _norm_list(meta.get("applicable_conditions", []))
    contra = _norm_list(meta.get("contraindications", []))
    risk_tags = _norm_list(meta.get("risk_tags", []))
    safe_alts = _norm_list(meta.get("safe_alternatives", []))
    training_level = str(meta.get("training_level", "general")).strip().lower()
    if training_level not in ("general", "beginner", "intermediate", "advanced"):
        training_level = "general"
    knowledge_role = str(meta.get("knowledge_role", "general")).strip().lower()
    if knowledge_role not in ("recommendation", "correction", "risk_warning", "alternative", "general"):
        knowledge_role = "general"
    gts = []
    for g in gt_strs:
        try:
            gts.append(GoalType(g))
        except Exception:
            pass
    if not gts:
        gts = [GoalType.general]
    heads = list(_HD_RE.finditer(body))
    if not heads:
        c = body.strip()
        if c:
            chunks.append(KnowledgeChunk(
                document_id=doc.document_id, title=doc.title,
                content=c[:3000], topic=tags[0] if tags else "",
                goal_types=gts, training_level=training_level,
                knowledge_role=knowledge_role,
                applicable_conditions=conds, contraindications=contra,
                risk_tags=risk_tags, safe_alternatives=safe_alts, tags=tags,
                category=doc.category, evidence_level=doc.evidence_level,
                source_name=doc.source_name, source_url=doc.source_url,
            ))
        return chunks
    for i, m in enumerate(heads):
        ht = m.group(2).strip()
        # 章节级元数据：检查标题前的 HTML 注释
        text_before = body[max(0, m.start() - 500):m.start()]
        ch_meta = _parse_chapter_meta(text_before)
        s = m.end()
        e = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        c = body[s:e].strip()
        if not c:
            continue
        topic = ""
        for tag in tags:
            if tag in ht.lower():
                topic = tag
                break
        cgts = gts.copy()
        cp = c[:500]
        if any(k in cp for k in ["减脂", "脂肪", "热量缺口"]):
            if GoalType.fat_loss not in cgts:
                cgts.append(GoalType.fat_loss)
        if any(k in cp for k in ["增肌", "肌肉", "热量盈余"]):
            if GoalType.muscle_gain not in cgts:
                cgts.append(GoalType.muscle_gain)
        # 章节级元数据覆盖文档级默认值
        ch_kr = ch_meta.get("knowledge_role", knowledge_role)
        if ch_kr not in ("recommendation", "correction", "risk_warning", "alternative", "general"):
            ch_kr = knowledge_role
        ch_tl = ch_meta.get("training_level", training_level)
        if ch_tl not in ("general", "beginner", "intermediate", "advanced"):
            ch_tl = training_level
        ch_contra = _norm_list(ch_meta.get("contraindications", contra))
        ch_risk = _norm_list(ch_meta.get("risk_tags", risk_tags))
        ch_alts = _norm_list(ch_meta.get("safe_alternatives", safe_alts))
        ch_conds = _norm_list(ch_meta.get("applicable_conditions", conds))
        chunks.append(KnowledgeChunk(
            document_id=doc.document_id,
            title=f"{doc.title} - {ht}",
            content=c[:3000], topic=topic, goal_types=cgts,
            training_level=ch_tl, knowledge_role=ch_kr,
            applicable_conditions=ch_conds, contraindications=ch_contra,
            risk_tags=ch_risk, safe_alternatives=ch_alts, tags=tags,
            category=doc.category, evidence_level=doc.evidence_level,
            source_name=doc.source_name, source_url=doc.source_url,
        ))
    return chunks


def load_document(fp: Path):
    try:
        text = fp.read_text(encoding="utf-8")
    except Exception as e:
        return None, [], f"Read failed: {e}"
    meta, body = parse_frontmatter(text)
    if not meta:
        return None, [], f"Missing frontmatter: {fp.name}"
    doc = _build_doc(meta, body)
    if not doc:
        return None, [], f"Validation failed: {fp.name}"
    chs = _split(body, doc, meta)
    if not chs:
        return None, [], f"Empty content: {fp.name}"
    doc.chunk_count = len(chs)
    return doc, chs, ""


def load_all_documents(docs_dir: Path):
    t0 = time.time()
    rpt = ImportReport()
    docs, all_chs, seen = [], [], set()
    mds = sorted(docs_dir.glob("*.md"))
    if not mds:
        rpt.errors.append(f"No .md files in {docs_dir}")
        return [], [], rpt
    for fp in mds:
        doc, chs, err = load_document(fp)
        if err:
            rpt.failed += 1
            rpt.errors.append(err)
            continue
        if doc.status == DocStatus.deprecated:
            rpt.deprecated += 1
            continue
        if doc.content_hash in seen:
            rpt.skipped += 1
            continue
        seen.add(doc.content_hash)
        uniq = []
        for ch in chs:
            if ch.content_hash not in seen:
                seen.add(ch.content_hash)
                uniq.append(ch)
            else:
                rpt.skipped += 1
        doc.chunk_count = len(uniq)
        docs.append(doc)
        all_chs.extend(uniq)
        rpt.imported += 1
    rpt.duration_ms = (time.time() - t0) * 1000
    return docs, all_chs, rpt
