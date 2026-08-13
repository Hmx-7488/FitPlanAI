from __future__ import annotations

import json
import ipaddress
import logging
import os
import re
import socket
import ssl
import time
import uuid
from dataclasses import asdict, dataclass
from http.client import RemoteDisconnected
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from app.core.config import get_settings
from app.services.image_utils import image_extension, validate_image

logger = logging.getLogger(__name__)

RECIPES_UPLOAD_DIR = Path(__file__).parent.parent.parent / "data" / "uploads" / "recipes"
RECIPES_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_GENERATED_IMAGE_BYTES = 15 * 1024 * 1024
_TRUSTED_IMAGE_HOST_PATTERNS = (
    re.compile(r"^(?:[a-z0-9-]+\.)*dashscope\.aliyuncs\.com$"),
    re.compile(
        r"^[a-z0-9][a-z0-9.-]*\.oss-(?:accelerate|cn-[a-z0-9-]+)\.aliyuncs\.com$"
    ),
)


@dataclass
class ImageGenerationResult:
    status: str
    url: str = ""
    task_id: str = ""
    request_id: str = ""
    error_code: str = ""
    error_message: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class DashScopeImageError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "",
        request_id: str = "",
        task_id: str = "",
    ):
        super().__init__(message)
        self.code = code
        self.request_id = request_id
        self.task_id = task_id


def _uses_mihomo_fake_ip(url: str) -> bool:
    hostname = urlparse(url).hostname
    if not hostname:
        return False
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        }
    except OSError:
        return False
    fake_ip_network = ipaddress.ip_network("198.18.0.0/15")
    return any(
        ipaddress.ip_address(address) in fake_ip_network
        for address in addresses
        if ":" not in address
    )


def _network_error_message(url: str, exc: BaseException) -> str:
    reason = str(getattr(exc, "reason", exc))[:300]
    message = f"连接 DashScope 图片服务失败：{reason}"
    if _uses_mihomo_fake_ip(url):
        message += (
            "。检测到域名由 Mihomo/TUN Fake-IP 接管，请检查代理节点或将 "
            "dashscope.aliyuncs.com 配置为稳定可用的代理规则后重试"
        )
    return message


def _public_image_error_message(code: str) -> str:
    if code in {"NETWORK_ERROR", "POLL_TIMEOUT"}:
        return "图片生成服务网络繁忙，请稍后重试"
    if "Quota" in code or "QUOTA" in code.upper():
        return "图片生成服务额度暂时不可用，请稍后重试"
    return "图片生成失败，请稍后重试"


def _request_json(
    url: str,
    headers: dict,
    payload: dict | None = None,
    timeout: int = 120,
    attempts: int = 1,
    retry_delay_seconds: float = 1.0,
) -> dict:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers=headers,
        method="GET" if payload is None else "POST",
    )
    total_attempts = max(1, attempts)
    for attempt in range(1, total_attempts + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(body)
            except json.JSONDecodeError:
                detail = {}
            raise DashScopeImageError(
                detail.get("message") or f"DashScope HTTP {exc.code}",
                code=detail.get("code") or f"HTTP_{exc.code}",
                request_id=detail.get("request_id", ""),
            ) from exc
        except (
            URLError,
            TimeoutError,
            ConnectionError,
            ssl.SSLError,
            RemoteDisconnected,
        ) as exc:
            if attempt >= total_attempts:
                raise DashScopeImageError(
                    _network_error_message(url, exc),
                    code="NETWORK_ERROR",
                ) from exc
            delay = retry_delay_seconds * (2 ** (attempt - 1))
            logger.warning(
                "Transient DashScope transport failure method=%s attempt=%s/%s "
                "error_type=%s message=%s; retrying in %.1fs",
                request.method,
                attempt,
                total_attempts,
                type(exc).__name__,
                str(getattr(exc, "reason", exc))[:300],
                delay,
            )
            time.sleep(delay)

    raise AssertionError("unreachable")


def _download_file(
    url: str,
    path: Path,
    timeout: int = 30,
    attempts: int = 2,
) -> None:
    parsed = urlparse(url)
    candidates = [url]
    accelerate_suffix = ".oss-accelerate.aliyuncs.com"
    if parsed.hostname and parsed.hostname.endswith(accelerate_suffix):
        bucket = parsed.hostname.removesuffix(accelerate_suffix)
        regional_url = urlunparse(
            parsed._replace(netloc=f"{bucket}.oss-cn-beijing.aliyuncs.com")
        )
        candidates = [regional_url, url]

    last_error: BaseException | None = None
    for candidate in candidates:
        _validate_provider_image_url(candidate)
        request = Request(candidate, headers={"User-Agent": "SlimAgent/1.0"})
        hostname = urlparse(candidate).hostname
        for attempt in range(1, max(1, attempts) + 1):
            try:
                with _open_download_request(request, timeout) as response:
                    final_url = response.geturl()
                    if isinstance(final_url, str) and final_url:
                        _validate_provider_image_url(final_url)
                    chunks: list[bytes] = []
                    downloaded = 0
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        downloaded += len(chunk)
                        if downloaded > MAX_GENERATED_IMAGE_BYTES:
                            raise ValueError("Generated image response is too large")
                        chunks.append(chunk)
                    content = b"".join(chunks)
                    mime_type, _, _ = validate_image(content)
                    if image_extension(mime_type) != path.suffix.lower():
                        raise ValueError("Generated image type does not match destination")

                    path.parent.mkdir(parents=True, exist_ok=True)
                    temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
                    try:
                        temporary_path.write_bytes(content)
                        os.replace(temporary_path, path)
                    finally:
                        temporary_path.unlink(missing_ok=True)
                    logger.info(
                        "Recipe image downloaded host=%s bytes=%s",
                        hostname,
                        downloaded,
                    )
                    return
            except (
                URLError,
                TimeoutError,
                ConnectionError,
                ssl.SSLError,
                RemoteDisconnected,
            ) as exc:
                last_error = exc
                logger.warning(
                    "Recipe image download failed host=%s attempt=%s/%s "
                    "error_type=%s message=%s",
                    hostname,
                    attempt,
                    attempts,
                    type(exc).__name__,
                    str(getattr(exc, "reason", exc))[:300],
                )
                if attempt < attempts:
                    time.sleep(2 ** (attempt - 1))
    if last_error is not None:
        raise last_error
    raise RuntimeError("No recipe image download URL available")


def _is_trusted_provider_image_host(hostname: str) -> bool:
    normalized = hostname.rstrip(".").lower()
    return any(pattern.fullmatch(normalized) for pattern in _TRUSTED_IMAGE_HOST_PATTERNS)


def _validate_provider_image_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        raise ValueError("Provider image URL must use HTTPS")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Provider image URL is not trusted")
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if not hostname or not _is_trusted_provider_image_host(hostname):
        raise ValueError("Provider image URL host is not trusted")
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        raise ValueError("Unable to resolve provider image host") from exc
    if not addresses:
        raise ValueError("Unable to resolve provider image host")
    try:
        if any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise ValueError("Provider image host must resolve only to public addresses")
    except ValueError as exc:
        if "public addresses" in str(exc):
            raise
        raise ValueError("Provider image host resolved to an invalid address") from exc


class _SafeImageRedirectHandler(HTTPRedirectHandler):
    max_redirections = 3
    max_repeats = 2

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_provider_image_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_download_request(request: Request, timeout: int):
    return build_opener(_SafeImageRedirectHandler()).open(request, timeout=timeout)


def _wan26_payload(prompt: str, model: str) -> dict:
    return {
        "model": model,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ]
        },
        "parameters": {
            "prompt_extend": True,
            "watermark": False,
            "n": 1,
            "negative_prompt": (
                "文字，水印，标志，多份餐盘，多道菜拼图，不相关食材，塑料质感，"
                "过度饱和，低清晰度，模糊，畸形餐具"
            ),
            "size": "1280*1280",
        },
    }


def _legacy_payload(prompt: str, model: str) -> dict:
    return {
        "model": model,
        "input": {
            "prompt": prompt,
            "negative_prompt": "文字，水印，标志，多份餐盘，不相关食材，低清晰度，模糊",
        },
        "parameters": {
            "n": 1,
            "size": "1024*1024",
            "prompt_extend": True,
            "watermark": False,
        },
    }


def _result_image_url(task: dict, wan26: bool) -> str:
    output = task.get("output") or {}
    if wan26:
        for choice in output.get("choices") or []:
            content = ((choice.get("message") or {}).get("content")) or []
            for item in content:
                if item.get("image"):
                    return item["image"]
        return ""
    for item in output.get("results") or []:
        if item.get("url"):
            return item["url"]
    return ""


def generate_recipe_image(
    prompt: str,
    recipe_id: int,
    index: int,
    existing_task_id: str = "",
    existing_request_id: str = "",
    progress_callback: Callable[[str, str], None] | None = None,
) -> dict:
    settings = get_settings()
    if not settings.IMAGE_GENERATION_ENABLED:
        return ImageGenerationResult(
            status="failed",
            error_code="DISABLED",
            error_message="图片生成功能未启用",
        ).to_dict()
    if not settings.LLM_API_KEY:
        return ImageGenerationResult(
            status="failed",
            error_code="MISSING_API_KEY",
            error_message="图片生成服务未配置",
        ).to_dict()

    model = settings.IMAGE_MODEL
    wan26 = model.startswith("wan2.6")
    endpoint_path = (
        "/services/aigc/image-generation/generation"
        if wan26
        else "/services/aigc/text2image/image-synthesis"
    )
    endpoint = f"{settings.IMAGE_BASE_URL.rstrip('/')}{endpoint_path}"
    final_prompt = (
        f"{prompt}。单人份完整成品，菜品主体居中，食材比例自然，真实可食用，"
        "专业健康餐摄影，自然日光，白色或浅色餐盘，45度视角，背景简洁，"
        "画面只出现这一道菜，不出现人物、文字、水印或品牌标志。"
    )
    headers = {
        "Authorization": f"Bearer {settings.LLM_API_KEY}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    payload = _wan26_payload(final_prompt, model) if wan26 else _legacy_payload(final_prompt, model)
    task_id = existing_task_id
    request_id = existing_request_id

    try:
        if not task_id:
            logger.info(
                "Creating recipe image task recipe_id=%s index=%s model=%s prompt_length=%s",
                recipe_id,
                index,
                model,
                len(final_prompt),
            )
            created = _request_json(
                endpoint,
                headers,
                payload,
                timeout=45,
                attempts=4,
            )
            request_id = created.get("request_id", "")
            task_id = (created.get("output") or {}).get("task_id", "")
            if not task_id:
                raise DashScopeImageError(
                    created.get("message") or "DashScope response did not contain task_id",
                    code=created.get("code") or "MISSING_TASK_ID",
                    request_id=request_id,
                )
            if progress_callback is not None:
                progress_callback(task_id, request_id)
        else:
            logger.info(
                "Resuming recipe image task recipe_id=%s index=%s task_id=%s request_id=%s",
                recipe_id,
                index,
                task_id,
                request_id,
            )
            if progress_callback is not None:
                progress_callback(task_id, request_id)

        task_url = f"{settings.IMAGE_BASE_URL.rstrip('/')}/tasks/{task_id}"
        task = {}
        consecutive_network_errors = 0
        for poll_index in range(51):
            if poll_index > 0:
                time.sleep(3)
            try:
                task = _request_json(
                    task_url,
                    {"Authorization": f"Bearer {settings.LLM_API_KEY}"},
                    None,
                    timeout=30,
                    attempts=2,
                )
                consecutive_network_errors = 0
            except DashScopeImageError as exc:
                if exc.code != "NETWORK_ERROR":
                    raise
                consecutive_network_errors += 1
                logger.warning(
                    "Transient recipe image polling failure recipe_id=%s index=%s "
                    "task_id=%s attempt=%s message=%s",
                    recipe_id,
                    index,
                    task_id,
                    consecutive_network_errors,
                    str(exc),
                )
                if consecutive_network_errors >= 3:
                    raise DashScopeImageError(
                        str(exc),
                        code=exc.code,
                        request_id=request_id,
                        task_id=task_id,
                    ) from exc
                continue
            request_id = task.get("request_id", request_id)
            if progress_callback is not None:
                progress_callback(task_id, request_id)
            output = task.get("output") or {}
            status = output.get("task_status")
            logger.info(
                "Recipe image task status recipe_id=%s index=%s task_id=%s request_id=%s status=%s",
                recipe_id,
                index,
                task_id,
                request_id,
                status,
            )
            if status in {"SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN"}:
                break

        output = task.get("output") or {}
        if output.get("task_status") != "SUCCEEDED":
            task_status = output.get("task_status", "")
            timed_out = task_status in {"PENDING", "RUNNING", ""}
            raise DashScopeImageError(
                (
                    "Timed out while waiting for image generation"
                    if timed_out
                    else output.get("message") or task.get("message") or "Image generation did not succeed"
                ),
                code=(
                    "POLL_TIMEOUT"
                    if timed_out
                    else output.get("code") or task.get("code") or task_status or "FAILED"
                ),
                request_id=request_id,
                task_id=task_id,
            )
        image_url = _result_image_url(task, wan26)
        if not image_url:
            raise DashScopeImageError(
                "DashScope response did not contain an image URL",
                code="MISSING_IMAGE_URL",
                request_id=request_id,
                task_id=task_id,
            )

        filename = f"{recipe_id}_{index}_{uuid.uuid4().hex[:8]}.png"
        saved_path = RECIPES_UPLOAD_DIR / filename
        try:
            _download_file(image_url, saved_path)
        except (
            URLError,
            TimeoutError,
            ConnectionError,
            ssl.SSLError,
            RemoteDisconnected,
        ) as exc:
            raise DashScopeImageError(
                f"生成完成，但下载成品图失败：{str(exc)[:300]}",
                code="NETWORK_ERROR",
                request_id=request_id,
                task_id=task_id,
            ) from exc
        logger.info(
            "Recipe image ready recipe_id=%s index=%s task_id=%s request_id=%s file=%s",
            recipe_id,
            index,
            task_id,
            request_id,
            filename,
        )
        return ImageGenerationResult(
            status="ready",
            url=f"/uploads/recipes/{filename}",
            task_id=task_id,
            request_id=request_id,
        ).to_dict()
    except DashScopeImageError as exc:
        logger.error(
            "Recipe image generation failed recipe_id=%s index=%s model=%s task_id=%s "
            "request_id=%s code=%s",
            recipe_id,
            index,
            model,
            exc.task_id or task_id,
            exc.request_id or request_id,
            exc.code,
        )
        return ImageGenerationResult(
            status="failed",
            task_id=exc.task_id or task_id,
            request_id=exc.request_id or request_id,
            error_code=exc.code or "GENERATION_FAILED",
            error_message=_public_image_error_message(exc.code),
        ).to_dict()
    except Exception as exc:
        logger.error(
            "Unexpected recipe image failure recipe_id=%s index=%s model=%s "
            "task_id=%s request_id=%s error_type=%s",
            recipe_id,
            index,
            model,
            task_id,
            request_id,
            type(exc).__name__,
        )
        return ImageGenerationResult(
            status="failed",
            task_id=task_id,
            request_id=request_id,
            error_code="INTERNAL_ERROR",
            error_message="图片生成服务出现异常，请稍后重试",
        ).to_dict()
