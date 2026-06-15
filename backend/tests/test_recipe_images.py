import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.user import RecipeImageJob
from app.schemas.vision import RecipeImage, RecipeItem
from app.services.image_generation_service import (
    DashScopeImageError,
    _result_image_url,
    _wan26_payload,
    generate_recipe_image,
)
from app.services.recipe_image_service import (
    image_prompt_hash,
    import_legacy_recipe_image_jobs,
    prepare_recipe_image_jobs,
    queue_recipe_image_retry,
)


def sample_recipe(prompt: str = "鸡胸肉西兰花轻食成品") -> RecipeItem:
    return RecipeItem(
        name="鸡胸肉西兰花",
        ingredients=["鸡胸肉 150g", "西兰花 120g"],
        calories_est=360,
        protein_est=42,
        carbs_est=22,
        fat_est=10,
        steps="1. 煎鸡胸肉\n2. 焯西兰花\n3. 装盘",
        image=RecipeImage(
            url="",
            alt="鸡胸肉西兰花成品图",
            generation_prompt=prompt,
            status="queued",
        ),
    )


class ImageProtocolTests(unittest.TestCase):
    def test_wan26_payload_uses_new_message_protocol(self):
        payload = _wan26_payload("一份轻食", "wan2.6-t2i")

        self.assertEqual(payload["model"], "wan2.6-t2i")
        self.assertEqual(
            payload["input"]["messages"][0]["content"][0]["text"],
            "一份轻食",
        )
        self.assertEqual(payload["parameters"]["n"], 1)
        self.assertEqual(payload["parameters"]["size"], "1280*1280")

    def test_wan26_result_reads_choice_image(self):
        task = {
            "output": {
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"type": "image", "image": "https://example.com/result.png"}
                            ]
                        }
                    }
                ]
            }
        }

        self.assertEqual(
            _result_image_url(task, True),
            "https://example.com/result.png",
        )

    @patch("app.services.image_generation_service._request_json")
    def test_provider_error_is_returned_without_secret(self, request_json):
        request_json.side_effect = DashScopeImageError(
            "quota exceeded",
            code="AllocationQuota.FreeTierOnly",
            request_id="request-1",
        )

        result = generate_recipe_image("一份轻食", 1, 0)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "AllocationQuota.FreeTierOnly")
        self.assertEqual(result["request_id"], "request-1")
        self.assertNotIn("sk-", result["error_message"])

    @patch("app.services.image_generation_service._download_file")
    @patch("app.services.image_generation_service.time.sleep")
    @patch("app.services.image_generation_service._request_json")
    def test_existing_task_is_resumed_without_duplicate_creation(
        self,
        request_json,
        _sleep,
        _download,
    ):
        request_json.return_value = {
            "request_id": "poll-request",
            "output": {
                "task_status": "SUCCEEDED",
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"type": "image", "image": "https://example.com/result.png"}
                            ]
                        }
                    }
                ],
            },
        }

        result = generate_recipe_image(
            "一份轻食",
            1,
            0,
            existing_task_id="existing-task",
            existing_request_id="create-request",
        )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["task_id"], "existing-task")
        self.assertEqual(request_json.call_count, 1)
        self.assertIn("/tasks/existing-task", request_json.call_args.args[0])


class RecipeImageJobTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "recipe-images.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

        async def prepare():
            async with self.engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)

        asyncio.run(prepare())

    def tearDown(self):
        asyncio.run(self.engine.dispose())
        self.temp_dir.cleanup()

    def test_prompt_hash_is_whitespace_insensitive(self):
        first = image_prompt_hash("鸡胸肉   西兰花", "wan2.6-t2i")
        second = image_prompt_hash(" 鸡胸肉 西兰花 ", "wan2.6-t2i")
        self.assertEqual(first, second)

    def test_ready_cache_is_reused(self):
        async def run():
            prompt = "鸡胸肉西兰花轻食成品"
            digest = image_prompt_hash(prompt, "wan2.6-t2i")
            async with self.session_factory() as db:
                db.add(
                    RecipeImageJob(
                        recipe_id=1,
                        recipe_index=0,
                        prompt=prompt,
                        prompt_hash=digest,
                        model="wan2.6-t2i",
                        status="ready",
                        image_url="/uploads/recipes/cached.png",
                    )
                )
                await db.commit()

                with patch(
                    "app.services.recipe_image_service._local_image_exists",
                    return_value=True,
                ):
                    recipes = [sample_recipe(prompt)]
                    jobs = await prepare_recipe_image_jobs(db, 2, recipes)

                self.assertEqual(jobs[0].status, "ready")
                self.assertEqual(jobs[0].image_url, "/uploads/recipes/cached.png")
                self.assertEqual(jobs[0].cache_hit, 1)
                self.assertTrue(recipes[0].image.cache_hit)

        asyncio.run(run())

    def test_failed_job_can_be_requeued(self):
        async def run():
            async with self.session_factory() as db:
                job = RecipeImageJob(
                    recipe_id=8,
                    recipe_index=1,
                    prompt="轻食",
                    prompt_hash="a" * 64,
                    model="wan2.6-t2i",
                    status="failed",
                    error_code="TIMEOUT",
                    error_message="timeout",
                )
                db.add(job)
                await db.commit()

                queued = await queue_recipe_image_retry(db, 8, 1)
                self.assertIsNotNone(queued)
                self.assertEqual(queued.status, "queued")
                self.assertEqual(queued.retry_count, 1)
                self.assertEqual(queued.error_code, "")

                stored = (
                    await db.execute(
                        select(RecipeImageJob).where(RecipeImageJob.id == queued.id)
                    )
                ).scalar_one()
                self.assertEqual(stored.status, "queued")

        asyncio.run(run())

    def test_legacy_failure_is_imported_as_retryable_job(self):
        async def run():
            async with self.session_factory() as db:
                jobs = await import_legacy_recipe_image_jobs(
                    db,
                    10,
                    [sample_recipe()],
                    [
                        {
                            "url": "/uploads/recipes/default-recipe.png",
                            "status": "failed",
                        }
                    ],
                )

                self.assertEqual(jobs[0].status, "failed")
                self.assertEqual(jobs[0].error_code, "LEGACY_FAILURE")
                queued = await queue_recipe_image_retry(db, 10, 0)
                self.assertEqual(queued.status, "queued")
                self.assertEqual(queued.model, "wan2.6-t2i")

        asyncio.run(run())

    def test_network_failure_retry_keeps_provider_task(self):
        async def run():
            async with self.session_factory() as db:
                job = RecipeImageJob(
                    recipe_id=12,
                    recipe_index=0,
                    prompt="轻食",
                    prompt_hash="b" * 64,
                    model="wan2.6-t2i",
                    status="failed",
                    provider_task_id="existing-task",
                    provider_request_id="existing-request",
                    error_code="NETWORK_ERROR",
                    error_message="temporary failure",
                )
                db.add(job)
                await db.commit()

                queued = await queue_recipe_image_retry(db, 12, 0)
                self.assertEqual(queued.provider_task_id, "existing-task")
                self.assertEqual(queued.provider_request_id, "existing-request")

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
