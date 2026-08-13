import os as _os
import certifi as _certifi
# 修复 WSL/Windows 混合环境下 OpenSSL 找不到 CA 证书的问题
_os.environ.setdefault("SSL_CERT_FILE", _certifi.where())
_os.environ.setdefault("REQUESTS_CA_BUNDLE", _certifi.where())

from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import model_validator
from functools import lru_cache

BACKEND_DIR = Path(__file__).parent.parent.parent


def _proxy_url(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    if "://" in raw:
        return raw
    return f"http://{raw}"


def _windows_proxy_from_registry() -> dict[str, str]:
    if _os.name != "nt":
        return {}
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if not proxy_enable:
                return {}
            proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
    except OSError:
        return {}

    proxy_server = str(proxy_server).strip()
    if not proxy_server:
        return {}

    parsed: dict[str, str] = {}
    for part in proxy_server.split(";"):
        if "=" not in part:
            continue
        scheme, value = part.split("=", 1)
        parsed[scheme.lower().strip()] = _proxy_url(value)

    if parsed:
        return {
            key: value
            for key, value in {
                "HTTP_PROXY": parsed.get("http"),
                "HTTPS_PROXY": parsed.get("https") or parsed.get("http"),
            }.items()
            if value
        }

    proxy = _proxy_url(proxy_server)
    return {"HTTP_PROXY": proxy, "HTTPS_PROXY": proxy}


def _configure_process_proxy() -> None:
    if _os.environ.get("HTTP_PROXY") or _os.environ.get("HTTPS_PROXY"):
        return
    for key, value in _windows_proxy_from_registry().items():
        _os.environ.setdefault(key, value)
        _os.environ.setdefault(key.lower(), value)


_configure_process_proxy()


class Settings(BaseSettings):
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    LLM_MODEL: str = "qwen-plus"
    VISION_MODEL: str = "qwen-vl-plus"
    IMAGE_MODEL: str = "wan2.6-t2i"
    IMAGE_BASE_URL: str = "https://dashscope.aliyuncs.com/api/v1"
    IMAGE_GENERATION_ENABLED: bool = True
    DATABASE_URL: str = "sqlite+aiosqlite:///./slim_agent.db"
    APP_ENV: str = "development"
    KNOWLEDGE_ADMIN_KEY: str = ""
    # 聊天上下文预算。默认值保持保守，并允许按模型能力通过环境变量覆盖。
    CHAT_CONTEXT_WINDOW_TOKENS: int = 32768
    CHAT_CONTEXT_MAX_OUTPUT_TOKENS: int = 1200
    CHAT_CONTEXT_SAFETY_BUFFER_TOKENS: int = 2048
    CHAT_CONTEXT_MAX_HISTORY_MESSAGES: int = 500
    # 会话摘要在响应流结束后异步触发，不阻塞当前回答。
    CHAT_SUMMARY_TRIGGER_TOKENS: int = 6000
    CHAT_SUMMARY_TRIGGER_MESSAGES: int = 40
    CHAT_SUMMARY_KEEP_RECENT_TOKENS: int = 2000
    CHAT_SUMMARY_MAX_OUTPUT_TOKENS: int = 1200
    CHAT_MICROCOMPACT_FULL_ARTIFACT_TOKENS: int = 800
    CHAT_MICROCOMPACT_TARGET_ARTIFACT_TOKENS: int = 240
    # 跨会话长期记忆：后台提取，召回时只读取已确认且有效的记录。
    CHAT_MEMORY_EXTRACTION_ENABLED: bool = True
    CHAT_MEMORY_EXTRACTION_MAX_OUTPUT_TOKENS: int = 800
    CHAT_MEMORY_RECALL_LIMIT: int = 12
    CHAT_MEMORY_RECALL_CANDIDATE_LIMIT: int = 100
    CHAT_MEMORY_AUTO_CONFIRM_MIN_CONFIDENCE: float = 0.8
    MEMORY_RETRIEVAL_MODE: str = "hybrid"
    MEMORY_VECTOR_ENABLED: bool = True
    MEMORY_EMBEDDING_MODEL: str = "text-embedding-v3"
    MEMORY_VECTOR_COLLECTION: str = "slim_agent_user_memory_v1"
    MEMORY_VECTOR_CANDIDATE_LIMIT: int = 40
    MEMORY_KEYWORD_CANDIDATE_LIMIT: int = 100
    MEMORY_HEALTH_RECALL_LIMIT: int = 4
    MEMORY_RRF_K: int = 60
    MEMORY_INDEX_BATCH_SIZE: int = 20
    MEMORY_INDEX_MAX_ATTEMPTS: int = 5
    MEMORY_INDEX_RETRY_BASE_SECONDS: int = 5
    MEMORY_INDEX_MAINTENANCE_INTERVAL_SECONDS: float = 5.0
    RECIPE_IMAGE_JOB_LEASE_SECONDS: int = 300
    RECIPE_IMAGE_MAINTENANCE_INTERVAL_SECONDS: float = 30.0
    # 仅在当前 collection 已完整覆盖 SQL 活跃记忆后清理旧版本，避免模型
    # 或 index_version 切换后继续保留已经删除的敏感向量。
    MEMORY_CLEANUP_OBSOLETE_COLLECTIONS: bool = True
    CHAT_MEMORY_EXTRACTION_SCAN_LIMIT: int = 100
    CHAT_MEMORY_EXTRACTION_MAX_ATTEMPTS: int = 5
    CHAT_MEMORY_EXTRACTION_RETRY_BASE_SECONDS: int = 30
    CHAT_SUMMARY_SCAN_LIMIT: int = 50
    CHAT_SUMMARY_PENDING_LEASE_SECONDS: int = 300
    CHAT_BACKGROUND_MAINTENANCE_INTERVAL_SECONDS: float = 30.0
    # 非 development 环境下，记忆 API 必须由可信反向代理注入该密钥。
    MEMORY_API_ACCESS_KEY: str = ""
    # 允许的前端来源，逗号分隔；默认仅本地开发端口
    CORS_ORIGINS: str = (
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:5173,http://127.0.0.1:5173"
    )

    model_config = {
        "env_file": str(BACKEND_DIR / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @property
    def cors_origin_list(self) -> list[str]:
        """解析 CORS_ORIGINS 为来源列表，忽略空项。"""
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @model_validator(mode="after")
    def validate_chat_context_budget(self):
        if self.CHAT_CONTEXT_WINDOW_TOKENS <= 0:
            raise ValueError("CHAT_CONTEXT_WINDOW_TOKENS must be positive")
        if self.CHAT_CONTEXT_MAX_OUTPUT_TOKENS <= 0:
            raise ValueError("CHAT_CONTEXT_MAX_OUTPUT_TOKENS must be positive")
        if self.CHAT_CONTEXT_SAFETY_BUFFER_TOKENS < 0:
            raise ValueError("CHAT_CONTEXT_SAFETY_BUFFER_TOKENS cannot be negative")
        reserved = (
            self.CHAT_CONTEXT_MAX_OUTPUT_TOKENS
            + self.CHAT_CONTEXT_SAFETY_BUFFER_TOKENS
        )
        if reserved >= self.CHAT_CONTEXT_WINDOW_TOKENS:
            raise ValueError("chat context reserves must be smaller than the window")
        if self.CHAT_CONTEXT_MAX_HISTORY_MESSAGES <= 0:
            raise ValueError("CHAT_CONTEXT_MAX_HISTORY_MESSAGES must be positive")
        if self.CHAT_SUMMARY_TRIGGER_TOKENS <= 0:
            raise ValueError("CHAT_SUMMARY_TRIGGER_TOKENS must be positive")
        if self.CHAT_SUMMARY_TRIGGER_MESSAGES <= 0:
            raise ValueError("CHAT_SUMMARY_TRIGGER_MESSAGES must be positive")
        if self.CHAT_SUMMARY_KEEP_RECENT_TOKENS <= 0:
            raise ValueError("CHAT_SUMMARY_KEEP_RECENT_TOKENS must be positive")
        if self.CHAT_SUMMARY_KEEP_RECENT_TOKENS >= self.CHAT_SUMMARY_TRIGGER_TOKENS:
            raise ValueError(
                "CHAT_SUMMARY_KEEP_RECENT_TOKENS must be smaller than the token trigger"
            )
        if self.CHAT_SUMMARY_MAX_OUTPUT_TOKENS <= 0:
            raise ValueError("CHAT_SUMMARY_MAX_OUTPUT_TOKENS must be positive")
        if self.CHAT_MICROCOMPACT_FULL_ARTIFACT_TOKENS <= 0:
            raise ValueError(
                "CHAT_MICROCOMPACT_FULL_ARTIFACT_TOKENS must be positive"
            )
        if self.CHAT_MICROCOMPACT_TARGET_ARTIFACT_TOKENS <= 0:
            raise ValueError(
                "CHAT_MICROCOMPACT_TARGET_ARTIFACT_TOKENS must be positive"
            )
        if (
            self.CHAT_MICROCOMPACT_TARGET_ARTIFACT_TOKENS
            >= self.CHAT_MICROCOMPACT_FULL_ARTIFACT_TOKENS
        ):
            raise ValueError(
                "microcompact target must be smaller than the full artifact limit"
            )
        if self.CHAT_MEMORY_EXTRACTION_MAX_OUTPUT_TOKENS <= 0:
            raise ValueError(
                "CHAT_MEMORY_EXTRACTION_MAX_OUTPUT_TOKENS must be positive"
            )
        if self.CHAT_MEMORY_RECALL_LIMIT <= 0:
            raise ValueError("CHAT_MEMORY_RECALL_LIMIT must be positive")
        if self.CHAT_MEMORY_RECALL_CANDIDATE_LIMIT < self.CHAT_MEMORY_RECALL_LIMIT:
            raise ValueError(
                "CHAT_MEMORY_RECALL_CANDIDATE_LIMIT must be at least recall limit"
            )
        if not 0 <= self.CHAT_MEMORY_AUTO_CONFIRM_MIN_CONFIDENCE <= 1:
            raise ValueError(
                "CHAT_MEMORY_AUTO_CONFIRM_MIN_CONFIDENCE must be between 0 and 1"
            )
        if self.MEMORY_RETRIEVAL_MODE not in {"keyword", "vector", "hybrid"}:
            raise ValueError("MEMORY_RETRIEVAL_MODE must be keyword, vector, or hybrid")
        if self.MEMORY_VECTOR_CANDIDATE_LIMIT <= 0:
            raise ValueError("MEMORY_VECTOR_CANDIDATE_LIMIT must be positive")
        if self.MEMORY_KEYWORD_CANDIDATE_LIMIT < self.CHAT_MEMORY_RECALL_LIMIT:
            raise ValueError(
                "MEMORY_KEYWORD_CANDIDATE_LIMIT must be at least recall limit"
            )
        if self.MEMORY_HEALTH_RECALL_LIMIT <= 0:
            raise ValueError("MEMORY_HEALTH_RECALL_LIMIT must be positive")
        if self.MEMORY_RRF_K <= 0:
            raise ValueError("MEMORY_RRF_K must be positive")
        if self.MEMORY_INDEX_BATCH_SIZE <= 0:
            raise ValueError("MEMORY_INDEX_BATCH_SIZE must be positive")
        if self.MEMORY_INDEX_MAX_ATTEMPTS <= 0:
            raise ValueError("MEMORY_INDEX_MAX_ATTEMPTS must be positive")
        if self.MEMORY_INDEX_RETRY_BASE_SECONDS <= 0:
            raise ValueError("MEMORY_INDEX_RETRY_BASE_SECONDS must be positive")
        if self.MEMORY_INDEX_MAINTENANCE_INTERVAL_SECONDS <= 0:
            raise ValueError(
                "MEMORY_INDEX_MAINTENANCE_INTERVAL_SECONDS must be positive"
            )
        if self.RECIPE_IMAGE_JOB_LEASE_SECONDS < 60:
            raise ValueError("RECIPE_IMAGE_JOB_LEASE_SECONDS must be at least 60")
        if self.RECIPE_IMAGE_MAINTENANCE_INTERVAL_SECONDS <= 0:
            raise ValueError(
                "RECIPE_IMAGE_MAINTENANCE_INTERVAL_SECONDS must be positive"
            )
        if self.CHAT_MEMORY_EXTRACTION_SCAN_LIMIT <= 0:
            raise ValueError("CHAT_MEMORY_EXTRACTION_SCAN_LIMIT must be positive")
        if self.CHAT_MEMORY_EXTRACTION_MAX_ATTEMPTS <= 0:
            raise ValueError("CHAT_MEMORY_EXTRACTION_MAX_ATTEMPTS must be positive")
        if self.CHAT_MEMORY_EXTRACTION_RETRY_BASE_SECONDS <= 0:
            raise ValueError(
                "CHAT_MEMORY_EXTRACTION_RETRY_BASE_SECONDS must be positive"
            )
        if self.CHAT_SUMMARY_SCAN_LIMIT <= 0:
            raise ValueError("CHAT_SUMMARY_SCAN_LIMIT must be positive")
        if self.CHAT_SUMMARY_PENDING_LEASE_SECONDS <= 0:
            raise ValueError("CHAT_SUMMARY_PENDING_LEASE_SECONDS must be positive")
        if self.CHAT_BACKGROUND_MAINTENANCE_INTERVAL_SECONDS <= 0:
            raise ValueError(
                "CHAT_BACKGROUND_MAINTENANCE_INTERVAL_SECONDS must be positive"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
