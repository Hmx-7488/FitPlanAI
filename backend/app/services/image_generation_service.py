import json
import logging
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

RECIPES_UPLOAD_DIR = Path(__file__).parent.parent.parent / "data" / "uploads" / "recipes"
RECIPES_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _request_json(url: str, headers: dict, payload: dict | None = None, timeout: int = 120) -> dict:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=data, headers=headers, method="GET" if payload is None else "POST")
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _download_file(url: str, path: Path, timeout: int = 120) -> None:
    req = Request(url, headers={"User-Agent": "SlimAgent/1.0"})
    with urlopen(req, timeout=timeout) as response:
        path.write_bytes(response.read())


def generate_recipe_image(prompt: str, recipe_id: int, index: int) -> dict:
    if not settings.IMAGE_GENERATION_ENABLED:
        return {"url": "/uploads/recipes/default-recipe.png", "status": "disabled"}
    if not settings.LLM_API_KEY:
        return {"url": "/uploads/recipes/default-recipe.png", "status": "missing_api_key"}

    final_prompt = (
        f"{prompt}. Realistic healthy meal photography, natural daylight, clean plate, "
        "top-down or 45 degree angle, appetizing, no text, no watermark, no logo."
    )
    headers = {
        "Authorization": f"Bearer {settings.LLM_API_KEY}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    endpoint = f"{settings.IMAGE_BASE_URL.rstrip('/')}/services/aigc/text2image/image-synthesis"
    payload = {
        "model": settings.IMAGE_MODEL,
        "input": {"prompt": final_prompt},
        "parameters": {"n": 1, "size": "1024*1024"},
    }

    try:
        logger.info("Creating DashScope recipe image task: recipe_id=%s index=%s model=%s", recipe_id, index, settings.IMAGE_MODEL)
        created = _request_json(endpoint, headers, payload)
        task_id = created.get("output", {}).get("task_id")
        if not task_id:
            raise RuntimeError(f"DashScope image task missing task_id: {created}")

        task_url = f"{settings.IMAGE_BASE_URL.rstrip('/')}/tasks/{task_id}"
        task = {}
        for _ in range(24):
            time.sleep(5)
            task = _request_json(task_url, {"Authorization": f"Bearer {settings.LLM_API_KEY}"}, None)
            status = task.get("output", {}).get("task_status")
            logger.info("DashScope recipe image task status: task_id=%s status=%s", task_id, status)
            if status in {"SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN"}:
                break

        output = task.get("output", {})
        if output.get("task_status") != "SUCCEEDED":
            raise RuntimeError(f"DashScope image task did not succeed: {task}")
        results = output.get("results") or []
        image_url = results[0].get("url") if results else None
        if not image_url:
            raise RuntimeError(f"DashScope image task missing result url: {task}")

        filename = f"{recipe_id}_{index}_{uuid.uuid4().hex[:8]}.png"
        saved_path = RECIPES_UPLOAD_DIR / filename
        _download_file(image_url, saved_path)
        return {"url": f"/uploads/recipes/{filename}", "status": "ready"}
    except Exception as exc:
        logger.exception("DashScope recipe image generation failed: recipe_id=%s index=%s error=%s", recipe_id, index, exc)
        return {"url": "/uploads/recipes/default-recipe.png", "status": "failed"}
