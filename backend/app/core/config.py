from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import model_validator
from functools import lru_cache

BACKEND_DIR = Path(__file__).parent.parent.parent


class Settings(BaseSettings):
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://token-plan-cn.xiaomimimo.com/v1"
    LLM_MODEL: str = "mimo-v2.5-pro"
    VISION_MODEL: str = ""  # 留空则使用 LLM_MODEL
    DATABASE_URL: str = "sqlite+aiosqlite:///./slim_agent.db"

    model_config = {
        "env_file": str(BACKEND_DIR / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
