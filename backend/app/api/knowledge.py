"""Knowledge management API endpoints."""
from fastapi import APIRouter, HTTPException
from app.rag.models import SearchQuery, SearchResult, IndexStats
from app.rag.retriever import get_retriever
from app.rag.vectorstore import get_vectorstore_manager

router = APIRouter()


@router.post("/rebuild")
async def rebuild_index():
    """Rebuild the knowledge index (vector + keyword).
    Requires admin authorization in production.
    """
    retriever = get_retriever()
    result = retriever.rebuild()
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return {"status": "ok", **result}


@router.post("/search", response_model=SearchResult)
async def search_knowledge(query: SearchQuery):
    """Search the knowledge base with hybrid retrieval."""
    retriever = get_retriever()
    return retriever.search(query)


@router.get("/status")
async def get_status():
    """Get current knowledge index status."""
    retriever = get_retriever()
    return retriever.get_status()


@router.get("/documents")
async def list_documents():
    """List all indexed knowledge documents."""
    from app.rag.indexer import load_all_documents
    from pathlib import Path
    docs_dir = Path(__file__).parent.parent.parent / "data" / "knowledge_docs"
    docs, _, _ = load_all_documents(docs_dir)
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


@router.post("/evaluate")
async def evaluate_retrieval():
    """Run the RAG evaluation suite."""
    from app.rag.evaluate import run_evaluation
    return run_evaluation()

