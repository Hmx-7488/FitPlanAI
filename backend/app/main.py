from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.core.config import get_settings
from app.core.database import init_db
from app.api.profile import router as profile_router
from app.api.plan import router as plan_router
from app.api.checkin import router as checkin_router
from app.api.vision import router as vision_router
from app.api.body import router as body_router
from app.api.pose import router as pose_router
from app.api.meal import router as meal_router
from app.api.dashboard import router as dashboard_router
from app.api.knowledge import router as knowledge_router
from app.api.chat import router as chat_router

UPLOAD_DIR = Path(__file__).parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="FitPlanAI",
    description="基于 LLM + LangGraph + RAG 的个性化减脂/增肌 AI Agent",
    version="0.6.0",
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

# 静态文件：上传的图片
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


@app.get("/")
async def root():
    return {"message": "FitPlanAI API", "version": "0.6.0"}
