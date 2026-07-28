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

    model_config = {
        "env_file": str(BACKEND_DIR / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
