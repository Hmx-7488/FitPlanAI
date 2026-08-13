"""A version-isolated Chroma backend for long-term user memories."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

from app.core.config import get_settings
from app.memory.types import MemoryVectorMatch
from app.models.user import UserMemory

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parents[2] / "data"
MEMORY_VECTORSTORE_DIR = _BASE_DIR / "memory_vectorstore"
_MEMORY_COLLECTION_PREFIX = "slim_agent_user_memories_"


class MemoryVectorUnavailable(RuntimeError):
    """Raised when a queryable memory vector index does not exist yet."""


def _collection_component(value: str) -> str:
    normalized = value.strip()
    component = re.sub(r"[^a-zA-Z0-9_-]+", "_", normalized).strip("_-")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:10]
    return f"{component[:37] or 'default'}_{digest}"


def memory_collection_name(embedding_model: str, index_version: str) -> str:
    """Return a stable collection name; models/versions never share vectors."""
    return (
        "slim_agent_user_memories_"
        f"{_collection_component(embedding_model)}_"
        f"{_collection_component(index_version)}"
    )


@runtime_checkable
class MemoryVectorBackend(Protocol):
    async def search(
        self, query: str, *, user_id: int, limit: int
    ) -> list[MemoryVectorMatch]: ...

    async def upsert(self, memory: UserMemory) -> None: ...

    async def delete(self, memory_id: int) -> None: ...

    async def list_memory_ids(self) -> set[int]: ...

    async def list_memory_revisions(self) -> dict[int, tuple[int, str]]: ...

    async def collection_exists(self) -> bool: ...

    async def close(self) -> None: ...

    async def cleanup_obsolete_collections(self) -> int: ...


def _close_chroma_client(client: Any) -> None:
    """Best-effort release of Chroma resources, including Windows file handles."""
    if client is None:
        return
    close = getattr(client, "close", None)
    if callable(close):
        close()
        return
    system = getattr(client, "_system", None)
    stop = getattr(system, "stop", None)
    if callable(stop):
        stop()
    clear_cache = getattr(client, "clear_system_cache", None)
    if callable(clear_cache):
        clear_cache()


class ChromaMemoryVectorStore:
    """Lazy Chroma adapter whose blocking calls always run off the event loop."""

    def __init__(
        self,
        *,
        persist_directory: Path | None = None,
        embedding_model: str | None = None,
        index_version: str | None = None,
        embedding_function: Any | None = None,
    ) -> None:
        settings = get_settings()
        self.persist_directory = persist_directory or MEMORY_VECTORSTORE_DIR
        self.embedding_model = embedding_model or settings.MEMORY_EMBEDDING_MODEL
        configured_collection = settings.MEMORY_VECTOR_COLLECTION
        self.index_version = index_version or configured_collection
        self.collection_name = memory_collection_name(
            self.embedding_model,
            self.index_version,
        )
        self._embedding_function = embedding_function
        self._store: Chroma | None = None

    def _embeddings(self) -> Any:
        if self._embedding_function is not None:
            return self._embedding_function
        settings = get_settings()
        return OpenAIEmbeddings(
            model=self.embedding_model,
            openai_api_key=settings.LLM_API_KEY,
            openai_api_base=settings.LLM_BASE_URL,
            check_embedding_ctx_length=False,
            chunk_size=10,
        )

    def _get_store(self) -> Chroma:
        if self._store is None:
            self.persist_directory.mkdir(parents=True, exist_ok=True)
            self._store = Chroma(
                embedding_function=self._embeddings(),
                persist_directory=str(self.persist_directory),
                collection_name=self.collection_name,
            )
        return self._store

    async def collection_exists(self) -> bool:
        if self._store is not None:
            return True
        if not (self.persist_directory / "chroma.sqlite3").is_file():
            return False
        return await asyncio.to_thread(self._collection_exists_sync)

    def _collection_exists_sync(self) -> bool:
        client = chromadb.PersistentClient(path=str(self.persist_directory))
        try:
            return self.collection_name in {
                collection.name for collection in client.list_collections()
            }
        finally:
            _close_chroma_client(client)

    @staticmethod
    def _document_id(memory_id: int) -> str:
        return f"memory:{memory_id}"

    @staticmethod
    def _index_revision(memory: UserMemory) -> int:
        return int(getattr(memory, "index_revision", 0) or 0)

    @staticmethod
    def _index_text(memory: UserMemory) -> str:
        # content_json and source messages are intentionally excluded. Sensitive
        # memories use the same minimal governed representation.
        return "\n".join(
            part
            for part in (
                memory.memory_type,
                memory.memory_key,
                " ".join(memory.content_text.split()),
            )
            if part
        )

    async def search(
        self, query: str, *, user_id: int, limit: int
    ) -> list[MemoryVectorMatch]:
        if not await self.collection_exists():
            # Querying a missing Chroma database would create an empty index and
            # may still invoke the remote embedding API. Index creation belongs
            # exclusively to the outbox/rebuild write path.
            raise MemoryVectorUnavailable("memory vector index is not initialized")
        return await asyncio.to_thread(
            self._search_sync, query, user_id=user_id, limit=limit
        )

    def _search_sync(
        self, query: str, *, user_id: int, limit: int
    ) -> list[MemoryVectorMatch]:
        if not query.strip() or limit <= 0:
            return []
        results = self._get_store().similarity_search_with_relevance_scores(
            query,
            k=limit,
            filter={"user_id": user_id},
        )
        matches: list[MemoryVectorMatch] = []
        for document, score in results:
            metadata = dict(document.metadata or {})
            try:
                matches.append(
                    MemoryVectorMatch(
                        memory_id=int(metadata["memory_id"]),
                        score=max(0.0, min(1.0, float(score))),
                        content_fingerprint=str(metadata["content_fingerprint"]),
                        index_revision=int(metadata["index_revision"]),
                        metadata=metadata,
                    )
                )
            except (KeyError, TypeError, ValueError):
                logger.warning("Ignored malformed memory vector metadata")
        return matches

    async def upsert(self, memory: UserMemory) -> None:
        await asyncio.to_thread(self._upsert_sync, memory)

    def _upsert_sync(self, memory: UserMemory) -> None:
        metadata = {
            "memory_id": memory.id,
            "user_id": memory.user_id,
            "content_fingerprint": memory.content_fingerprint,
            "index_revision": self._index_revision(memory),
            "embedding_model": self.embedding_model,
            "index_version": self.index_version,
            "collection": self.collection_name,
            "sensitivity": memory.sensitivity,
        }
        self._get_store().add_documents(
            [Document(page_content=self._index_text(memory), metadata=metadata)],
            ids=[self._document_id(memory.id)],
        )

    async def delete(self, memory_id: int) -> None:
        if not await self.collection_exists():
            return
        await asyncio.to_thread(
            self._get_store().delete, ids=[self._document_id(memory_id)]
        )

    async def list_memory_ids(self) -> set[int]:
        if not await self.collection_exists():
            return set()
        return set(await self.list_memory_revisions())

    async def list_memory_revisions(self) -> dict[int, tuple[int, str]]:
        if not await self.collection_exists():
            return {}
        return await asyncio.to_thread(self._list_memory_revisions_sync)

    def _list_memory_revisions_sync(self) -> dict[int, tuple[int, str]]:
        payload = self._get_store().get(include=["metadatas"])
        result: dict[int, tuple[int, str]] = {}
        for metadata in payload.get("metadatas") or []:
            try:
                value = metadata or {}
                result[int(value["memory_id"])] = (
                    int(value["index_revision"]),
                    str(value["content_fingerprint"]),
                )
            except (KeyError, TypeError, ValueError):
                continue
        return result

    async def cleanup_obsolete_collections(self) -> int:
        """Delete superseded SlimAgent memory collections after caller verifies coverage."""
        if not await self.collection_exists():
            return 0
        return await asyncio.to_thread(self._cleanup_obsolete_collections_sync)

    def _cleanup_obsolete_collections_sync(self) -> int:
        # Release this adapter before deleting collections that may share the
        # same persistent client/system cache.
        self._close_sync()
        client = chromadb.PersistentClient(path=str(self.persist_directory))
        deleted = 0
        try:
            names = [collection.name for collection in client.list_collections()]
            if self.collection_name not in names:
                return 0
            for name in names:
                if (
                    name.startswith(_MEMORY_COLLECTION_PREFIX)
                    and name != self.collection_name
                ):
                    client.delete_collection(name=name)
                    deleted += 1
        finally:
            _close_chroma_client(client)
        if deleted:
            logger.info(
                "Removed obsolete memory vector collections",
                extra={"deleted_collection_count": deleted},
            )
        return deleted

    async def close(self) -> None:
        await asyncio.to_thread(self._close_sync)

    def _close_sync(self) -> None:
        store = self._store
        self._store = None
        if store is not None:
            _close_chroma_client(getattr(store, "_client", None))
