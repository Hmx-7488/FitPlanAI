import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.main import app, lifespan


class _SessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class AppLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_lifespan_runs_durable_background_maintenance(self):
        loop = asyncio.get_running_loop()
        memory_started = asyncio.Event()
        chat_started = asyncio.Event()
        recipe_started = asyncio.Event()
        media_cleaned = asyncio.Event()

        async def memory_worker():
            memory_started.set()
            await asyncio.Event().wait()

        async def chat_worker():
            chat_started.set()
            await asyncio.Event().wait()

        async def recipe_worker():
            recipe_started.set()
            await asyncio.Event().wait()

        def cleanup_body():
            loop.call_soon_threadsafe(media_cleaned.set)
            return 0

        settings = type('Settings', (), {'APP_ENV': 'development'})()
        with (
            patch('app.main.get_settings', return_value=settings),
            patch('app.main.init_db', new=AsyncMock()),
            patch('app.main.async_session', side_effect=lambda: _SessionContext()),
            patch('app.main.import_exercises_if_empty', new=AsyncMock(return_value=0)),
            patch('app.main.import_foods_if_empty', new=AsyncMock(return_value=0)),
            patch('app.main.memory_index_maintenance_worker', side_effect=memory_worker),
            patch('app.main.chat_background_maintenance_worker', side_effect=chat_worker),
            patch('app.main.recipe_image_maintenance_worker', side_effect=recipe_worker),
            patch('app.main.cleanup_body_deletion_quarantine', side_effect=cleanup_body),
            patch('app.main.cleanup_pose_deletion_quarantine', return_value=0),
        ):
            async with lifespan(app):
                await asyncio.wait_for(memory_started.wait(), timeout=1)
                await asyncio.wait_for(chat_started.wait(), timeout=1)
                await asyncio.wait_for(recipe_started.wait(), timeout=1)
                await asyncio.wait_for(media_cleaned.wait(), timeout=1)


if __name__ == '__main__':
    unittest.main()
