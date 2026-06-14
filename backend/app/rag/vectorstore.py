"""RAG vectorstore - Chroma wrapper with version management."""
from __future__ import annotations
import logging
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document

from app.rag.models import KnowledgeChunk, IndexStats

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).parent.parent.parent / "data"
_VECTORSTORE_DIR = _BASE_DIR / "vectorstore"


class VectorStoreManager:
    """Manages Chroma vectorstore with version-safe rebuild."""

    def __init__(self):
        self._store: Optional[Chroma] = None
        self._index_version: str = ""
        self._last_rebuild: Optional[float] = None
        self._stats = self._load_stats()
        self._index_version = self._stats.index_version

    @staticmethod
    def _meta_file() -> Path:
        return _BASE_DIR / "index_meta.json"

    def _load_stats(self) -> IndexStats:
        meta_file = self._meta_file()
        if not meta_file.exists():
            return IndexStats()
        try:
            return IndexStats.model_validate_json(meta_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load index metadata: %s", exc)
            return IndexStats()

    def _save_stats(self, stats: IndexStats) -> None:
        meta_file = self._meta_file()
        meta_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = meta_file.with_suffix(".json.tmp")
        tmp_file.write_text(stats.model_dump_json(indent=2), encoding="utf-8")
        tmp_file.replace(meta_file)

    def _get_embeddings(self) -> OpenAIEmbeddings:
        from app.core.config import get_settings
        s = get_settings()
        return OpenAIEmbeddings(
            model="text-embedding-v3",
            openai_api_key=s.LLM_API_KEY,
            openai_api_base=s.LLM_BASE_URL,
            check_embedding_ctx_length=False,  # DashScope 不接受 token IDs，需要直接传文本
            chunk_size=10,  # DashScope embedding API 限制 batch size ≤ 10
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
        previous_stats = self._stats
        categories = {}
        for chunk in chunks:
            category = chunk.category.value
            categories[category] = categories.get(category, 0) + 1

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
                "training_level": ch.training_level or "general",
                "knowledge_role": ch.knowledge_role or "general",
                "goal_types": ",".join(g.value for g in ch.goal_types),
                "applicable_conditions": ",".join(ch.applicable_conditions),
                "contraindications": ",".join(ch.contraindications),
                "risk_tags": ",".join(ch.risk_tags),
                "safe_alternatives": ",".join(ch.safe_alternatives),
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

        backup_dir = _BASE_DIR / "vectorstore_backup"
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

            # Close both stores to release file locks (required on Windows)
            try:
                new_store._client.close()
            except Exception:
                pass
            if self._store is not None:
                try:
                    self._store._client.close()
                except Exception:
                    pass
                self._store = None

            # Swap: old -> backup, tmp -> current
            if _VECTORSTORE_DIR.exists():
                if backup_dir.exists():
                    shutil.rmtree(backup_dir)
                shutil.move(str(_VECTORSTORE_DIR), str(backup_dir))
            shutil.move(str(tmp_dir), str(_VECTORSTORE_DIR))

            # Reopen store from new location
            self._store = Chroma(
                embedding_function=embeddings,
                persist_directory=str(_VECTORSTORE_DIR),
                collection_name="slim_agent_knowledge",
            )
            self._index_version = f"v_{int(time.time())}"
            self._last_rebuild = time.time()

            stats = IndexStats(
                total_documents=len({chunk.document_id for chunk in chunks}),
                total_chunks=len(chunks),
                categories=categories,
                index_version=self._index_version,
                last_rebuild=datetime.now(UTC),
                content_hashes=len({
                    chunk.content_hash for chunk in chunks if chunk.content_hash
                }),
            )
            self._save_stats(stats)
            self._stats = stats

            # Cleanup backup
            if backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)

            logger.info("Vectorstore built: %d chunks in %.0fms", count, (time.time()-t0)*1000)

        except Exception as e:
            logger.error("Vectorstore build failed: %s", e)
            self._store = None
            self._stats = previous_stats
            self._index_version = previous_stats.index_version
            # 清理可能存在的损坏新目录
            if _VECTORSTORE_DIR.exists():
                shutil.rmtree(_VECTORSTORE_DIR, ignore_errors=True)
            # 清理 tmp
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
            # 从备份恢复
            if backup_dir.exists():
                shutil.move(str(backup_dir), str(_VECTORSTORE_DIR))
                logger.info("Vectorstore restored from backup")
            raise

        return stats

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
                    training_level=meta.get("training_level", "general"),
                    knowledge_role=meta.get("knowledge_role", "general"),
                    tags=meta.get("tags", "").split(",") if meta.get("tags") else [],
                    applicable_conditions=meta.get("applicable_conditions", "").split(",") if meta.get("applicable_conditions") else [],
                    contraindications=meta.get("contraindications", "").split(",") if meta.get("contraindications") else [],
                    risk_tags=meta.get("risk_tags", "").split(",") if meta.get("risk_tags") else [],
                    safe_alternatives=meta.get("safe_alternatives", "").split(",") if meta.get("safe_alternatives") else [],
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
            return self._stats
        try:
            count = store._collection.count()
        except Exception:
            count = 0
        if self._stats.total_chunks == count:
            return self._stats
        return self._stats.model_copy(update={"total_chunks": count})


# Singleton
_manager: Optional[VectorStoreManager] = None

def get_vectorstore_manager() -> VectorStoreManager:
    global _manager
    if _manager is None:
        _manager = VectorStoreManager()
    return _manager
