"""Knowledge management API endpoints."""
import asyncio
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException

from app.core.config import get_settings
from app.rag.models import SearchQuery, SearchResult
from app.rag.retriever import get_retriever

router = APIRouter()


# ── 鉴权依赖 ──


def require_admin_key(x_admin_key: str = Header(default="")):
    """校验 X-Admin-Key 请求头。

    规则：
    - 配置了密钥：请求头必须使用安全比较匹配。
    - development 且未配置密钥：放行。
    - 非 development 且未配置密钥：拒绝（必须配置密钥）。
    """
    settings = get_settings()
    expected = settings.KNOWLEDGE_ADMIN_KEY
    is_dev = settings.APP_ENV == "development"

    if expected:
        # 密钥已配置，必须匹配（防时序攻击）
        if not hmac.compare_digest(x_admin_key, expected):
            raise HTTPException(status_code=403, detail="Invalid or missing admin key")
        return

    # 未配置密钥
    if not is_dev:
        raise HTTPException(
            status_code=403,
            detail="Admin key not configured; refusing access in non-development environment",
        )
    # development 且未配置密钥：放行


# ── 公开接口（只读）──


@router.post("/search", response_model=SearchResult)
async def search_knowledge(query: SearchQuery):
    """Search the knowledge base with hybrid retrieval."""
    retriever = get_retriever()
    return await asyncio.to_thread(retriever.search, query)


@router.get("/status")
async def get_status():
    """Get current knowledge index status."""
    retriever = get_retriever()
    return await asyncio.to_thread(retriever.get_status)


# ── 管理接口（需鉴权）──


@router.post("/rebuild", dependencies=[Depends(require_admin_key)])
async def rebuild_index():
    """Rebuild the knowledge index (vector + keyword). Requires admin key."""
    retriever = get_retriever()
    result = await asyncio.to_thread(retriever.rebuild)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return {"status": "ok", **result}


@router.get("/documents", dependencies=[Depends(require_admin_key)])
async def list_documents():
    """List all indexed knowledge documents. Requires admin key."""
    from pathlib import Path
    from app.rag.indexer import load_all_documents

    docs_dir = Path(__file__).parent.parent.parent / "data" / "knowledge_docs"
    docs, _, _ = await asyncio.to_thread(load_all_documents, docs_dir)
    return {
        "documents": [
            {
                "document_id": d.document_id,
                "title": d.title,
                "category": d.category.value,
                "evidence_level": d.evidence_level.value,
                "source_name": d.source_name,
                "chunk_count": d.chunk_count,
                "status": d.status.value,
            }
            for d in docs
        ]
    }


@router.post("/evaluate", dependencies=[Depends(require_admin_key)])
async def evaluate_retrieval():
    """Run the RAG evaluation suite. Requires admin key."""
    from app.rag.evaluate import run_evaluation

    return await asyncio.to_thread(run_evaluation)

