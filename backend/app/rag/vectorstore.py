"""RAG vectorstore - Chroma wrapper with version management."""
from __future__ import annotations
import logging
import shutil
import time
from pathlib import Path
from typing import Optional

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document

from app.rag.models import KnowledgeChunk, IndexStats

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).parent.parent.parent / "data"
_VECTORSTORE_DIR = _BASE_DIR / "vectorstore"
_INDEX_META_FILE = _BASE_DIR / "index_meta.json"


class VectorStoreManager:
    """Manages Chroma vectorstore with version-safe rebuild."""

    def __init__(self):
        self._store: Optional[Chroma] = None
        self._index_version: str = ""
        self._last_rebuild: Optional[float] = None

    def _get_embeddings(self) -> OpenAIEmbeddings:
        from app.core.config import get_settings
        s = get_settings()
        return OpenAIEmbeddings(
            model="text-embedding-v3",
            openai_api_key=s.LLM_API_KEY,
            openai_api_base=s.LLM_BASE_URL,
        )

    def get_store(self) -> Chroma:
        if self._store is not None:
            return self._store
        if (_VECTORSTORE_DIR / "chroma.sqlite3").exists():
            self._store = Chroma(
                embedding_function=self._get_embeddings(),
                persist_directory=str(_VECTORSTORE_DIR),
                collection_name="slim_agent_knowledge",
            )
            logger.info("Loaded existing vectorstore from %s", _VECTORSTORE_DIR)
        else:
            logger.info("No existing vectorstore found, will build on first index call")
        return self._store

    def index_chunks(self, chunks: list[KnowledgeChunk]) -> IndexStats:
        """Build vectorstore from chunks. Uses safe-rebuild pattern."""
        if not chunks:
            return IndexStats()

        t0 = time.time()
        embeddings = self._get_embeddings()

        # Prepare LangChain documents
        docs = []
        metadatas = []
        ids = []
        for ch in chunks:
            meta = {
                "chunk_id": ch.chunk_id,
                "document_id": ch.document_id,
                "title": ch.title,
                "category": ch.category.value,
                "evidence_level": ch.evidence_level.value,
                "source_name": ch.source_name,
                "source_url": ch.source_url,
                "topic": ch.topic,
                "goal_types": ",".join(g.value for g in ch.goal_types),
                "applicable_conditions": ",".join(ch.applicable_conditions),
                "contraindications": ",".join(ch.contraindications),
                "tags": ",".join(ch.tags),
                "content_hash": ch.content_hash,
            }
            docs.append(Document(page_content=ch.content, metadata=meta))
            ids.append(ch.chunk_id)

        # Build new store in a temp dir first
        tmp_dir = _BASE_DIR / "vectorstore_tmp"
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        tmp_dir.mkdir(parents=True, exist_ok=True)

        try:
            new_store = Chroma.from_documents(
                documents=docs,
                embedding=embeddings,
                persist_directory=str(tmp_dir),
                collection_name="slim_agent_knowledge",
                ids=ids,
            )
            # Verify: check count
            count = new_store._collection.count()
            if count < 1:
                raise ValueError(f"New vectorstore has {count} documents, expected >= 1")

            # Swap: rename old -> backup, tmp -> current
            backup_dir = _BASE_DIR / "vectorstore_backup"
            if _VECTORSTORE_DIR.exists():
                if backup_dir.exists():
                    shutil.rmtree(backup_dir)
                _VECTORSTORE_DIR.rename(backup_dir)
            tmp_dir.rename(_VECTORSTORE_DIR)

            self._store = new_store
            self._index_version = f"v_{int(time.time())}"
            self._last_rebuild = time.time()

            # Cleanup backup
            if backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)

            logger.info("Vectorstore built: %d chunks in %.0fms", count, (time.time()-t0)*1000)

        except Exception as e:
            # Rollback: restore old store if available
            logger.error("Vectorstore build failed: %s", e)
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
            # Try to restore backup
            backup_dir = _BASE_DIR / "vectorstore_backup"
            if backup_dir.exists() and not _VECTORSTORE_DIR.exists():
                backup_dir.rename(_VECTORSTORE_DIR)
            raise

        # Build stats
        cats = {}
        for ch in chunks:
            c = ch.category.value
            cats[c] = cats.get(c, 0) + 1

        return IndexStats(
            total_documents=len(set(ch.document_id for ch in chunks)),
            total_chunks=len(chunks),
            categories=cats,
            index_version=self._index_version,
            last_rebuild=None,
        )

    def similarity_search(
        self, query: str, k: int = 5,
        filter_dict: Optional[dict] = None,
    ) -> list[tuple[KnowledgeChunk, float]]:
        """Search vectorstore, return (chunk, score) pairs."""
        store = self.get_store()
        if store is None:
            return []
        try:
            results = store.similarity_search_with_relevance_scores(
                query, k=k, filter=filter_dict,
            )
            out = []
            for doc, score in results:
                meta = doc.metadata
                ch = KnowledgeChunk(
                    chunk_id=meta.get("chunk_id", ""),
                    document_id=meta.get("document_id", ""),
                    title=meta.get("title", ""),
                    content=doc.page_content,
                    category=meta.get("category", "fat_loss_standards"),
                    evidence_level=meta.get("evidence_level", "internal"),
                    source_name=meta.get("source_name", ""),
                    source_url=meta.get("source_url", ""),
                    topic=meta.get("topic", ""),
                    tags=meta.get("tags", "").split(",") if meta.get("tags") else [],
                    applicable_conditions=meta.get("applicable_conditions", "").split(",") if meta.get("applicable_conditions") else [],
                    contraindications=meta.get("contraindications", "").split(",") if meta.get("contraindications") else [],
                    content_hash=meta.get("content_hash", ""),
                )
                out.append((ch, max(0.0, min(1.0, score))))
            return out
        except Exception as e:
            logger.warning("Vector search failed: %s", e)
            return []

    def get_stats(self) -> IndexStats:
        store = self.get_store()
        if store is None:
            return IndexStats()
        try:
            count = store._collection.count()
        except Exception:
            count = 0
        return IndexStats(
            total_chunks=count,
            index_version=self._index_version,
        )


# Singleton
_manager: Optional[VectorStoreManager] = None

def get_vectorstore_manager() -> VectorStoreManager:
    global _manager
    if _manager is None:
        _manager = VectorStoreManager()
    return _manager
