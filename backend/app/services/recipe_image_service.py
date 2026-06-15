from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import async_session
from app.models.user import RecipeImageJob
from app.schemas.vision import RecipeImage, RecipeItem
from app.services.image_generation_service import generate_recipe_image

logger = logging.getLogger(__name__)
UPLOAD_DIR = Path(__file__).parent.parent.parent / "data" / "uploads"
_generation_slots = asyncio.Semaphore(3)
_submission_lock = asyncio.Lock()
_last_submission_at = 0.0
_MIN_SUBMISSION_INTERVAL_SECONDS = 1.05


async def _wait_for_submission_slot() -> None:
    global _last_submission_at
    async with _submission_lock:
        now = asyncio.get_running_loop().time()
        remaining = _MIN_SUBMISSION_INTERVAL_SECONDS - (now - _last_submission_at)
        if remaining > 0:
            await asyncio.sleep(remaining)
        _last_submission_at = asyncio.get_running_loop().time()


def image_prompt_hash(prompt: str, model: str) -> str:
    normalized = " ".join(prompt.split()).strip().lower()
    return hashlib.sha256(f"{model}\n{normalized}".encode("utf-8")).hexdigest()


def _local_image_exists(url: str) -> bool:
    if not url.startswith("/uploads/"):
        return False
    return (UPLOAD_DIR / url.removeprefix("/uploads/")).is_file()


def apply_job_to_recipe_image(image: RecipeImage, job: RecipeImageJob) -> None:
    image.url = job.image_url or ""
    image.status = job.status
    image.model = job.model
    image.error_message = job.error_message
    image.retry_count = job.retry_count
    image.cache_hit = bool(job.cache_hit)


async def prepare_recipe_image_jobs(
    db: AsyncSession,
    recipe_id: int,
    recipes: list[RecipeItem],
) -> list[RecipeImageJob]:
    settings = get_settings()
    jobs: list[RecipeImageJob] = []
    for index, recipe in enumerate(recipes):
        prompt = recipe.image.generation_prompt
        digest = image_prompt_hash(prompt, settings.IMAGE_MODEL)
        cached_stmt = (
            select(RecipeImageJob)
            .where(
                RecipeImageJob.prompt_hash == digest,
                RecipeImageJob.model == settings.IMAGE_MODEL,
                RecipeImageJob.status == "ready",
            )
            .order_by(desc(RecipeImageJob.updated_at), desc(RecipeImageJob.id))
            .limit(1)
        )
        cached = (await db.execute(cached_stmt)).scalar_one_or_none()
        cache_valid = bool(cached and _local_image_exists(cached.image_url))
        job = RecipeImageJob(
            recipe_id=recipe_id,
            recipe_index=index,
            prompt=prompt,
            prompt_hash=digest,
            model=settings.IMAGE_MODEL,
            status="ready" if cache_valid else "queued",
            image_url=cached.image_url if cache_valid else "",
            cache_hit=1 if cache_valid else 0,
        )
        db.add(job)
        jobs.append(job)
    await db.commit()
    for job, recipe in zip(jobs, recipes):
        await db.refresh(job)
        apply_job_to_recipe_image(recipe.image, job)
    return jobs


async def get_recipe_image_jobs(
    db: AsyncSession,
    recipe_id: int,
) -> list[RecipeImageJob]:
    stmt = (
        select(RecipeImageJob)
        .where(RecipeImageJob.recipe_id == recipe_id)
        .order_by(RecipeImageJob.recipe_index, RecipeImageJob.id)
    )
    return list((await db.execute(stmt)).scalars().all())


async def import_legacy_recipe_image_jobs(
    db: AsyncSession,
    recipe_id: int,
    recipes: list[RecipeItem],
    legacy_images: list[dict],
) -> list[RecipeImageJob]:
    existing = await get_recipe_image_jobs(db, recipe_id)
    if existing:
        return existing

    settings = get_settings()
    jobs = []
    for index, recipe in enumerate(recipes):
        legacy = legacy_images[index] if index < len(legacy_images) else {}
        legacy_url = str(legacy.get("url", ""))
        ready = bool(
            legacy.get("status") == "ready"
            and "default-recipe" not in legacy_url
            and _local_image_exists(legacy_url)
        )
        model = str(legacy.get("model", "")).strip() or (
            "legacy" if ready else settings.IMAGE_MODEL
        )
        job = RecipeImageJob(
            recipe_id=recipe_id,
            recipe_index=index,
            prompt=recipe.image.generation_prompt,
            prompt_hash=image_prompt_hash(recipe.image.generation_prompt, model),
            model=model,
            status="ready" if ready else "failed",
            image_url=legacy_url if ready else "",
            error_code="" if ready else "LEGACY_FAILURE",
            error_message=(
                ""
                if ready
                else "历史图片任务生成失败，原任务未保存详细错误，可重新生成。"
            ),
        )
        db.add(job)
        jobs.append(job)
    await db.commit()
    for job in jobs:
        await db.refresh(job)
    return jobs


async def process_recipe_image_job(job_id: int) -> None:
    async with async_session() as db:
        job = await db.get(RecipeImageJob, job_id)
        if job is None or job.status != "queued":
            return
        job.status = "generating"
        job.error_code = ""
        job.error_message = ""
        job.updated_at = datetime.utcnow()
        await db.commit()
        prompt = job.prompt
        recipe_id = job.recipe_id
        recipe_index = job.recipe_index
        provider_task_id = job.provider_task_id
        provider_request_id = job.provider_request_id

    async with _generation_slots:
        if not provider_task_id:
            await _wait_for_submission_slot()
        result = await asyncio.to_thread(
            generate_recipe_image,
            prompt,
            recipe_id,
            recipe_index,
            provider_task_id,
            provider_request_id,
        )

    async with async_session() as db:
        job = await db.get(RecipeImageJob, job_id)
        if job is None:
            return
        job.status = result["status"]
        job.image_url = result.get("url", "")
        job.provider_task_id = result.get("task_id", "")
        job.provider_request_id = result.get("request_id", "")
        job.error_code = result.get("error_code", "")
        job.error_message = result.get("error_message", "")
        job.updated_at = datetime.utcnow()
        await db.commit()


async def process_recipe_image_jobs(recipe_id: int) -> None:
    async with async_session() as db:
        jobs = await get_recipe_image_jobs(db, recipe_id)
        queued_ids = [job.id for job in jobs if job.status == "queued"]
    await asyncio.gather(
        *(process_recipe_image_job(job_id) for job_id in queued_ids)
    )


async def queue_recipe_image_retry(
    db: AsyncSession,
    recipe_id: int,
    recipe_index: int,
) -> RecipeImageJob | None:
    stmt = (
        select(RecipeImageJob)
        .where(
            RecipeImageJob.recipe_id == recipe_id,
            RecipeImageJob.recipe_index == recipe_index,
        )
        .order_by(desc(RecipeImageJob.id))
        .limit(1)
    )
    job = (await db.execute(stmt)).scalar_one_or_none()
    if job is None:
        return None
    if job.status in {"queued", "generating"}:
        return job
    settings = get_settings()
    job.model = settings.IMAGE_MODEL
    job.prompt_hash = image_prompt_hash(job.prompt, settings.IMAGE_MODEL)
    previous_error_code = job.error_code
    job.status = "queued"
    job.image_url = ""
    job.error_code = ""
    job.error_message = ""
    job.retry_count += 1
    job.cache_hit = 0
    if previous_error_code not in {"NETWORK_ERROR", "POLL_TIMEOUT"}:
        job.provider_task_id = ""
        job.provider_request_id = ""
    job.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(job)
    logger.info(
        "Recipe image retry queued recipe_id=%s index=%s job_id=%s retry_count=%s",
        recipe_id,
        recipe_index,
        job.id,
        job.retry_count,
    )
    return job
