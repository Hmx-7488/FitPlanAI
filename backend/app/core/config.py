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


class Settings(BaseSettings):
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    LLM_MODEL: str = "qwen-plus"
    VISION_MODEL: str = "qwen-vl-plus"
    IMAGE_MODEL: str = "wanx2.1-t2i-turbo"
    IMAGE_BASE_URL: str = "https://dashscope.aliyuncs.com/api/v1"
    IMAGE_GENERATION_ENABLED: bool = True
    DATABASE_URL: str = "sqlite+aiosqlite:///./slim_agent.db"
    APP_ENV: str = "development"
    KNOWLEDGE_ADMIN_KEY: str = ""

    model_config = {
        "env_file": str(BACKEND_DIR / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
