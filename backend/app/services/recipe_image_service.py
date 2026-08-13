from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import and_, desc, or_, select, update
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


class RecipeJobLeaseLost(RuntimeError):
    """Raised inside the provider thread when this worker no longer owns a job."""


def _lease_expiry() -> datetime:
    seconds = get_settings().RECIPE_IMAGE_JOB_LEASE_SECONDS
    return datetime.utcnow() + timedelta(seconds=seconds)


async def _renew_recipe_image_job_lease(
    job_id: int,
    lease_owner: str,
    provider_task_id: str,
    provider_request_id: str,
) -> bool:
    values: dict[str, object] = {
        "lease_expires_at": _lease_expiry(),
        "updated_at": datetime.utcnow(),
    }
    if provider_task_id:
        values["provider_task_id"] = provider_task_id
    if provider_request_id:
        values["provider_request_id"] = provider_request_id
    async with async_session() as db:
        renewed = await db.execute(
            update(RecipeImageJob)
            .where(
                RecipeImageJob.id == job_id,
                RecipeImageJob.status == "generating",
                RecipeImageJob.lease_owner == lease_owner,
            )
            .values(**values)
        )
        await db.commit()
        return renewed.rowcount == 1


def _remove_orphaned_generated_image(url: str) -> None:
    if not url.startswith("/uploads/recipes/"):
        return
    recipe_root = (UPLOAD_DIR / "recipes").resolve()
    candidate = (recipe_root / Path(url).name).resolve()
    if candidate.parent != recipe_root:
        return
    try:
        candidate.unlink(missing_ok=True)
    except OSError:
        logger.warning("Orphaned recipe image cleanup will retry file=%s", candidate.name)


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
    lease_owner = uuid.uuid4().hex
    async with async_session() as db:
        claimed_at = datetime.utcnow()
        claim = await db.execute(
            update(RecipeImageJob)
            .where(
                RecipeImageJob.id == job_id,
                RecipeImageJob.status == "queued",
            )
            .values(
                status="generating",
                error_code="",
                error_message="",
                lease_owner=lease_owner,
                lease_expires_at=_lease_expiry(),
                updated_at=claimed_at,
            )
        )
        await db.commit()
        if claim.rowcount != 1:
            return
        job = await db.get(RecipeImageJob, job_id)
        if job is None:
            return
        prompt = job.prompt
        recipe_id = job.recipe_id
        recipe_index = job.recipe_index
        provider_task_id = job.provider_task_id
        provider_request_id = job.provider_request_id

    loop = asyncio.get_running_loop()

    def persist_provider_progress(task_id: str, request_id: str) -> None:
        future = asyncio.run_coroutine_threadsafe(
            _renew_recipe_image_job_lease(
                job_id,
                lease_owner,
                task_id,
                request_id,
            ),
            loop,
        )
        try:
            renewed = future.result(timeout=30)
        except Exception as exc:
            future.cancel()
            raise RecipeJobLeaseLost("Could not renew recipe image job lease") from exc
        if not renewed:
            raise RecipeJobLeaseLost("Recipe image job lease is no longer owned")

    try:
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
                persist_provider_progress,
            )
        if not isinstance(result, dict) or result.get("status") not in {"ready", "failed"}:
            raise ValueError("Image generator returned an invalid result")
    except Exception as exc:
        logger.error(
            "Unexpected recipe image job failure job_id=%s recipe_id=%s "
            "index=%s error_type=%s",
            job_id,
            recipe_id,
            recipe_index,
            type(exc).__name__,
        )
        result = {
            "status": "failed",
            "url": "",
            "task_id": provider_task_id,
            "request_id": provider_request_id,
            "error_code": "INTERNAL_ERROR",
            "error_message": "图片生成任务异常，请稍后重试",
        }

    terminal_values: dict[str, object] = {
        "status": result["status"],
        "image_url": result.get("url", ""),
        "error_code": result.get("error_code", ""),
        "error_message": result.get("error_message", ""),
        "lease_owner": None,
        "lease_expires_at": None,
        "updated_at": datetime.utcnow(),
    }
    if result.get("task_id"):
        terminal_values["provider_task_id"] = result["task_id"]
    if result.get("request_id"):
        terminal_values["provider_request_id"] = result["request_id"]
    async with async_session() as db:
        published = await db.execute(
            update(RecipeImageJob)
            .where(
                RecipeImageJob.id == job_id,
                RecipeImageJob.status == "generating",
                RecipeImageJob.lease_owner == lease_owner,
            )
            .values(**terminal_values)
        )
        await db.commit()
    if published.rowcount != 1:
        _remove_orphaned_generated_image(str(result.get("url", "")))
        logger.info("Discarded stale recipe image result job_id=%s", job_id)


async def process_recipe_image_jobs(recipe_id: int) -> None:
    async with async_session() as db:
        jobs = await get_recipe_image_jobs(db, recipe_id)
        queued_ids = [job.id for job in jobs if job.status == "queued"]
    await asyncio.gather(
        *(process_recipe_image_job(job_id) for job_id in queued_ids)
    )


async def requeue_stale_recipe_image_jobs(
    db: AsyncSession,
    *,
    stale_before: datetime,
) -> int:
    """Atomically requeue only jobs whose persistent lease has expired."""
    now = datetime.utcnow()
    recovered = await db.execute(
        update(RecipeImageJob)
        .where(
            RecipeImageJob.status == "generating",
            or_(
                RecipeImageJob.lease_expires_at <= now,
                and_(
                    RecipeImageJob.lease_expires_at.is_(None),
                    RecipeImageJob.updated_at <= stale_before,
                ),
            ),
        )
        .values(
            status="queued",
            lease_owner=None,
            lease_expires_at=None,
            error_code="",
            error_message="",
            updated_at=now,
        )
    )
    await db.commit()
    return max(0, recovered.rowcount or 0)


async def recover_recipe_image_jobs(
    *,
    stale_after_seconds: int | None = None,
    batch_size: int = 100,
) -> dict[str, int]:
    """Recover expired work and drain the durable queued task set."""
    batch_size = max(1, min(batch_size, 500))
    if stale_after_seconds is None:
        stale_after_seconds = get_settings().RECIPE_IMAGE_JOB_LEASE_SECONDS
    stale_after_seconds = max(60, min(stale_after_seconds, 86_400))
    stale_before = datetime.utcnow() - timedelta(seconds=stale_after_seconds)
    async with async_session() as db:
        requeued = await requeue_stale_recipe_image_jobs(
            db,
            stale_before=stale_before,
        )
        queued_stmt = (
            select(RecipeImageJob.id)
            .where(RecipeImageJob.status == "queued")
            .order_by(RecipeImageJob.updated_at, RecipeImageJob.id)
        )
        queued_ids = list((await db.execute(queued_stmt)).scalars().all())
    for start in range(0, len(queued_ids), batch_size):
        wave = queued_ids[start:start + batch_size]
        await asyncio.gather(
            *(process_recipe_image_job(job_id) for job_id in wave)
        )
    return {"requeued": requeued, "processed": len(queued_ids)}


async def recipe_image_maintenance_worker(
    *,
    stop_event: asyncio.Event | None = None,
    interval_seconds: float | None = None,
) -> None:
    """Continuously recover expired jobs; atomic leases make this multi-worker safe."""
    interval = (
        get_settings().RECIPE_IMAGE_MAINTENANCE_INTERVAL_SECONDS
        if interval_seconds is None
        else max(0.05, interval_seconds)
    )
    while stop_event is None or not stop_event.is_set():
        try:
            await recover_recipe_image_jobs()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Recipe image maintenance cycle failed",
                extra={"error_type": type(exc).__name__},
            )
        if stop_event is None:
            await asyncio.sleep(interval)
            continue
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            pass


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
    job.lease_owner = None
    job.lease_expires_at = None
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
