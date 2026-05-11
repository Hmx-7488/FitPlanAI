from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.database import init_db
from app.api.profile import router as profile_router
from app.api.plan import router as plan_router
from app.api.checkin import router as checkin_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="减脂 Agent",
    description="基于 Agentic RAG 的个性化减脂教练",
    version="0.2.0",
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


@app.get("/")
async def root():
    return {"message": "减脂 Agent API", "version": "0.2.0"}
