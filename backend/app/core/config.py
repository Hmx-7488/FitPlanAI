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

    model_config = {
        "env_file": str(BACKEND_DIR / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
