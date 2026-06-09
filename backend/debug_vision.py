"""Debug DashScope-compatible Vision Model calls.

Usage:
    python debug_vision.py
    python debug_vision.py --image data/uploads/meals/example.jpg
"""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from pathlib import Path

from langchain_core.messages import HumanMessage

from app.api.meal import _detect_image_mime, _read_image_dimensions, SUPPORTED_IMAGE_MIME_TYPES
from app.core.config import get_settings
from app.services.vision_service import _encode_image, _get_vision_llm


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("debug_vision")


def _find_default_image() -> Path | None:
    roots = [
        Path("data/uploads/meals"),
        Path("data/uploads/body"),
        Path("data/uploads"),
        Path("../docs"),
    ]
    suffixes = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in suffixes:
                return path
    return None


def _print_config() -> None:
    settings = get_settings()
    logger.info("LLM_BASE_URL=%s", settings.LLM_BASE_URL)
    logger.info("LLM_MODEL=%s", settings.LLM_MODEL)
    logger.info("VISION_MODEL=%s", settings.VISION_MODEL or "<falls back to LLM_MODEL>")
    logger.info("LLM_API_KEY_CONFIGURED=%s", bool(settings.LLM_API_KEY))


def test_init():
    logger.info("Testing Vision Model initialization")
    llm = _get_vision_llm(max_tokens=200)
    logger.info("Vision Model client initialized")
    return llm


def test_text_call(llm) -> None:
    logger.info("Testing text-only call")
    response = llm.invoke([HumanMessage(content="Reply with exactly: OK")])
    logger.info("Text response raw type=%s content=%r", type(response).__name__, response.content)


def test_image_call(llm, image_path: Path) -> None:
    logger.info("Testing image call with %s", image_path)
    image_bytes = image_path.read_bytes()
    mime_type = _detect_image_mime(image_bytes, image_path.name, None)
    width, height = _read_image_dimensions(image_bytes, mime_type)
    logger.info(
        "Image info: mime=%s size_bytes=%s width=%s height=%s",
        mime_type,
        len(image_bytes),
        width,
        height,
    )

    if mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
        raise ValueError(f"Unsupported image MIME type: {mime_type}")
    if width is not None and height is not None and (width < 10 or height < 10):
        raise ValueError(f"Image must be at least 10x10 pixels, got {width}x{height}")

    image_data = _encode_image(image_bytes, mime_type=mime_type)
    logger.info("Encoded image data URL chars=%s prefix=%s", len(image_data), image_data[:40])

    prompt = (
        "Identify the food ingredients in this image. Return only a JSON array. "
        'Example: [{"name":"egg","display_name":"鸡蛋","estimated_weight_g":100,"confidence":0.9}]. '
        "Return [] if there is no food."
    )
    message = HumanMessage(
        content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_data, "detail": "low"}},
        ]
    )
    response = llm.invoke([message])
    logger.info("Image response raw type=%s content=%r", type(response).__name__, response.content)


def main() -> int:
    parser = argparse.ArgumentParser(description="Debug configured Vision Model calls")
    parser.add_argument("--image", type=Path, help="Path to a food image. Defaults to the first uploaded image found.")
    args = parser.parse_args()

    _print_config()

    image_path = args.image or _find_default_image()
    if image_path is None:
        logger.warning("No local image found. Text test will run, image test will be skipped.")
    elif not image_path.exists():
        logger.error("Image path does not exist: %s", image_path)
        return 2

    try:
        llm = test_init()
        test_text_call(llm)
        if image_path is not None:
            test_image_call(llm, image_path)
    except Exception:
        logger.error("Vision debug failed with full traceback:\n%s", traceback.format_exc())
        return 1

    logger.info("Vision debug completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
