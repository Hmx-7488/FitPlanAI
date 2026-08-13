import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.core.config import get_settings
from app.core.database import init_db, async_session
from app.api.profile import router as profile_router
from app.api.plan import router as plan_router
from app.api.checkin import router as checkin_router
from app.api.vision import router as vision_router
from app.api.body import cleanup_body_deletion_quarantine, router as body_router
from app.api.pose import cleanup_pose_deletion_quarantine, router as pose_router
from app.api.meal import router as meal_router
from app.api.dashboard import router as dashboard_router
from app.api.knowledge import router as knowledge_router
from app.api.chat import router as chat_router
from app.api.exercises import router as exercises_router
from app.api.foods import router as foods_router
from app.services.exercise_service import import_exercises_if_empty
from app.services.food_service import import_foods_if_empty
from app.services.memory_index_service import memory_index_maintenance_worker
from app.services.conversation_summary_service import chat_background_maintenance_worker
from app.services.recipe_image_service import recipe_image_maintenance_worker

UPLOAD_DIR = Path(__file__).parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

EXERCISE_MEDIA_DIR = Path(__file__).parent.parent / "data" / "exercises" / "exercise_media"
EXERCISE_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)


async def _cleanup_media_deletion_quarantine() -> None:
    for label, cleanup in (
        ("body", cleanup_body_deletion_quarantine),
        ("pose", cleanup_pose_deletion_quarantine),
    ):
        try:
            removed = await asyncio.to_thread(cleanup)
            if removed:
                logger.info("Cleaned %s quarantined %s media files", removed, label)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "%s media quarantine cleanup failed",
                label.capitalize(),
                extra={"error_type": type(exc).__name__},
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.APP_ENV != "development":
        logger.warning(
            "APP_ENV=%s：本应用 API 无用户鉴权，定位为单用户本地应用。"
            "请勿将后端暴露到公网或不受信网络；如需远程访问，"
            "请在反向代理层增加访问控制。",
            settings.APP_ENV,
        )
    await init_db()
    # 首次启动自动导入动作库
    async with async_session() as session:
        imported = await import_exercises_if_empty(session)
        if imported:
            logger.info("Exercise dataset imported: %d records.", imported)
        # 首次启动自动导入食物热量库
        food_imported = await import_foods_if_empty(session)
        if food_imported:
            logger.info("Food database imported: %d records.", food_imported)
    maintenance_tasks = [
        asyncio.create_task(memory_index_maintenance_worker()),
        asyncio.create_task(chat_background_maintenance_worker()),
        asyncio.create_task(recipe_image_maintenance_worker()),
        asyncio.create_task(_cleanup_media_deletion_quarantine()),
    ]
    try:
        yield
    finally:
        for task in maintenance_tasks:
            if not task.done():
                task.cancel()
        for task in maintenance_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="FitPlanAI",
    description="基于 LLM + LangGraph + RAG 的个性化减脂/增肌 AI Agent",
    version="0.7.1",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # 仅允许配置的前端来源；前端未使用 Cookie/凭据，credentials 保持关闭
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(profile_router, prefix="/api/profile", tags=["用户信息"])
app.include_router(plan_router, prefix="/api/plan", tags=["减脂计划"])
app.include_router(checkin_router, prefix="/api/checkin", tags=["每日打卡"])
app.include_router(vision_router, prefix="/api/vision", tags=["食材识别"])
app.include_router(body_router, prefix="/api/body", tags=["身材照片分析"])
app.include_router(pose_router, prefix="/api/pose", tags=["动作分析"])
app.include_router(meal_router, prefix="/api/meal", tags=["餐食热量识别"])
app.include_router(dashboard_router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(knowledge_router, prefix="/api/knowledge", tags=["知识库"])
app.include_router(chat_router, prefix="/api/chat", tags=["聊天 Agent"])
app.include_router(exercises_router, prefix="/api/exercises", tags=["动作库"])
app.include_router(foods_router, prefix="/api/foods", tags=["食物库"])

# 静态文件：上传的图片
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# 静态文件：动作库媒体（GIF + 缩略图，© Gym visual）
app.mount("/exercises/media", StaticFiles(directory=str(EXERCISE_MEDIA_DIR)), name="exercise-media")


@app.get("/")
async def root():
    return {"message": "FitPlanAI API", "version": "0.7.1"}
