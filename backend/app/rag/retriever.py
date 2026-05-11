"""RAG 知识检索模块 — 基于 Chroma 向量库的语义检索"""

from pathlib import Path
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from app.core.config import get_settings

settings = get_settings()

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "docs"
VECTORSTORE_DIR = Path(__file__).parent.parent.parent / "data" / "vectorstore"

_vectorstore: Chroma | None = None


def _get_embeddings() -> OpenAIEmbeddings:
    """获取嵌入模型（复用 LLM 的 API 配置）"""
    return OpenAIEmbeddings(
        model="text-embedding-v3",
        openai_api_key=settings.LLM_API_KEY,
        openai_api_base=settings.LLM_BASE_URL,
    )


def _build_vectorstore() -> Chroma:
    """从知识文档构建向量库（首次调用时构建，之后持久化）"""
    VECTORSTORE_DIR.mkdir(parents=True, exist_ok=True)

    # 加载文档
    loader = DirectoryLoader(
        str(DATA_DIR),
        glob="**/*.md",
        loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"},
    )
    docs = loader.load()

    # 文本切分
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=80,
        separators=["\n## ", "\n### ", "\n| ", "\n\n", "\n", " "],
    )
    splits = text_splitter.split_documents(docs)

    # 构建 Chroma 向量库并持久化
    vectorstore = Chroma.from_documents(
        documents=splits,
        embedding=_get_embeddings(),
        persist_directory=str(VECTORSTORE_DIR),
        collection_name="slim_agent_docs",
    )
    return vectorstore


def get_vectorstore() -> Chroma:
    """获取向量库实例（单例）"""
    global _vectorstore
    if _vectorstore is not None:
        return _vectorstore

    # 如果已有持久化的向量库，直接加载
    if (VECTORSTORE_DIR / "chroma.sqlite3").exists():
        _vectorstore = Chroma(
            embedding_function=_get_embeddings(),
            persist_directory=str(VECTORSTORE_DIR),
            collection_name="slim_agent_docs",
        )
    else:
        _vectorstore = _build_vectorstore()

    return _vectorstore


def retrieve_knowledge(query: str, k: int = 3) -> list[str]:
    """基于向量相似度的知识检索"""
    try:
        vectorstore = get_vectorstore()
        results = vectorstore.similarity_search(query, k=k)
        return [doc.page_content for doc in results]
    except Exception:
        # 向量检索失败时回退到关键词匹配
        return _fallback_retrieve(query, k)


def rebuild_vectorstore() -> None:
    """重建向量库（知识文档更新后调用）"""
    global _vectorstore
    _vectorstore = None
    # 清除旧的 Chroma 缓存，因为需要重新加载 embedding
    import shutil
    if VECTORSTORE_DIR.exists():
        shutil.rmtree(VECTORSTORE_DIR)
    _vectorstore = _build_vectorstore()


def _fallback_retrieve(query: str, k: int = 3) -> list[str]:
    """降级方案：直接加载文档并关键词匹配"""
    try:
        loader = DirectoryLoader(
            str(DATA_DIR),
            glob="**/*.md",
            loader_cls=TextLoader,
            loader_kwargs={"encoding": "utf-8"},
        )
        docs = loader.load()

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500, chunk_overlap=50,
        )
        splits = text_splitter.split_documents(docs)
        all_texts = [doc.page_content for doc in splits]

        keywords = query.lower().split()
        scored = []
        for text in all_texts:
            text_lower = text.lower()
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scored.append((score, text))

        scored.sort(key=lambda x: x[0], reverse=True)
        if scored:
            return [text for _, text in scored[:k]]
        return all_texts[:k]
    except Exception:
        return ["暂无相关知识库内容"]
