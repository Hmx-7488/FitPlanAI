from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.core.database import init_db
from app.api.profile import router as profile_router
from app.api.plan import router as plan_router
from app.api.checkin import router as checkin_router
from app.api.vision import router as vision_router

UPLOAD_DIR = Path(__file__).parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="FitPlanAI",
    description="基于 LLM + LangGraph + RAG 的个性化减脂/增肌 AI Agent",
    version="0.4.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(profile_router, prefix="/api/profile", tags=["用户信息"])
app.include_router(plan_router, prefix="/api/plan", tags=["减脂计划"])
app.include_router(checkin_router, prefix="/api/checkin", tags=["每日打卡"])
app.include_router(vision_router, prefix="/api/vision", tags=["食材识别"])

# 静态文件：上传的图片
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


@app.get("/")
async def root():
    return {"message": "FitPlanAI API", "version": "0.4.0"}
