"""Request-scoped, read-only tools for the chat agent.

Identity is captured by ``ChatReadToolContext`` and never appears in a model
tool schema. Every database query is built by SQLAlchemy and bounded here.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import date as calendar_date
from typing import Literal
from urllib.parse import urlsplit

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Checkin, Exercise, Food, MealLog, Plan, User
from app.rag.models import KnowledgeCategory, SearchQuery
from app.rag.retriever import get_retriever
from app.services.memory_retrieval_service import retrieve_user_memory_result


_DIET_TAGS = frozenset({
    "antioxidant",
    "healthy_fat",
    "high_fiber",
    "high_protein",
    "high_vitamin_c",
    "low_calorie",
    "low_carb",
    "low_fat",
    "low_sodium",
    "low_sugar",
    "omega3",
    "vegetarian",
})


@dataclass(frozen=True, slots=True)
class ChatReadToolContext:
    db: AsyncSession
    user_id: int
    conversation_id: int
    source_message_id: int


class _StrictArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmptyArgs(_StrictArgs):
    pass


class LatestPlanArgs(_StrictArgs):
    section: Literal["summary", "nutrition", "meals", "workout", "all"] = (
        "summary"
    )


class RecentCheckinsArgs(_StrictArgs):
    limit: int = Field(default=7, ge=1, le=30)


class MealSummaryArgs(_StrictArgs):
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class SearchFoodsArgs(_StrictArgs):
    query: str = Field(default="", max_length=100)
    category: Literal[
        "protein", "carb", "vegetable", "fruit", "fat", "dairy", "beverage"
    ] | None = None
    diet_tags: list[str] = Field(default_factory=list, max_length=4)
    limit: int = Field(default=8, ge=1, le=10)

    @field_validator("diet_tags")
    @classmethod
    def validate_diet_tags(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(tag.strip().lower() for tag in value if tag))
        if any(tag not in _DIET_TAGS for tag in normalized):
            raise ValueError("unsupported diet tag")
        return normalized


class SearchExercisesArgs(_StrictArgs):
    query: str = Field(default="", max_length=100)
    body_part: str = Field(default="", max_length=50)
    equipment: str = Field(default="", max_length=50)
    difficulty: Literal["beginner", "intermediate", "advanced"] | None = None
    limit: int = Field(default=8, ge=1, le=10)


class SearchKnowledgeArgs(_StrictArgs):
    query: str = Field(min_length=1, max_length=200)
    categories: list[KnowledgeCategory] = Field(default_factory=list, max_length=4)
    limit: int = Field(default=5, ge=1, le=5)


class SearchMemoriesArgs(_StrictArgs):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=8, ge=1, le=12)


def _load_json(raw: str | None, fallback):
    try:
        value = json.loads(raw or "")
    except (TypeError, json.JSONDecodeError):
        return fallback
    return value


def _text(value: object, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _safe_url(value: object) -> str:
    candidate = _text(value, 500)
    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    return candidate


def _source(source_type: str, source_id: object, title: str, url: str = "") -> dict:
    return {
        "source_type": source_type,
        "source_id": str(source_id),
        "title": _text(title, 160),
        "url": _safe_url(url),
    }


def _envelope(
    *,
    title: str,
    summary: str,
    content: object,
    sources: list[dict],
    citations: list[dict] | None = None,
    memory_usage: dict | None = None,
) -> dict:
    return {
        "title": _text(title, 120),
        "summary": _text(summary, 180),
        "content": content,
        "sources": sources[:12],
        "citations": (citations or [])[:5],
        "memory_usage": memory_usage,
    }


def build_chat_read_tools(
    context: ChatReadToolContext,
) -> dict[str, StructuredTool]:
    db = context.db

    async def get_user_profile() -> dict:
        user = await db.get(User, context.user_id)
        if user is None:
            return _envelope(
                title="用户档案",
                summary="未找到用户档案",
                content={"found": False},
                sources=[],
            )
        content = {
            "found": True,
            "gender": user.gender,
            "age": user.age,
            "height_cm": user.height,
            "weight_kg": user.weight,
            "target_weight_kg": user.target_weight,
            "target_weeks": user.target_weeks,
            "body_fat_rate": user.body_fat_rate,
            "activity_level": user.activity_level,
            "diet_preference": user.diet_preference,
            "goal_type": user.goal_type,
            "forbidden_foods": _load_json(user.forbidden_foods, []),
            "allergies": _load_json(user.allergies, []),
            "injuries": _load_json(user.injuries, []),
            "training_days_per_week": user.training_days_per_week,
            "session_duration_minutes": user.session_duration_minutes,
            "training_location": user.training_location,
            "equipment": _load_json(user.equipment, []),
            "training_experience": user.training_experience,
        }
        return _envelope(
            title="用户档案",
            summary="已读取当前权威用户档案",
            content=content,
            sources=[_source("profile", context.user_id, "当前用户档案")],
        )

    async def get_latest_plan(section: str = "summary") -> dict:
        plan = (
            await db.execute(
                select(Plan)
                .where(Plan.user_id == context.user_id)
                .order_by(desc(Plan.created_at), desc(Plan.id))
                .limit(1)
            )
        ).scalar_one_or_none()
        if plan is None:
            return _envelope(
                title="当前计划",
                summary="当前没有可用计划",
                content={"found": False},
                sources=[],
            )
        content: dict[str, object] = {
            "found": True,
            "plan_id": plan.id,
            "daily_calorie_target": plan.daily_calorie_target,
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
        }
        if section in {"summary", "all"}:
            content["summary"] = _text(plan.summary, 1200)
        if section in {"nutrition", "all"}:
            content["calorie_info"] = _load_json(plan.calorie_info_json, {})
            content["macros"] = _load_json(plan.macros_json, {})
        if section in {"meals", "all"}:
            content["meal_plan"] = _text(plan.meal_plan, 1800)
        if section in {"workout", "all"}:
            content["workout_plan"] = _text(plan.workout_plan, 1800)
        return _envelope(
            title="当前计划",
            summary=f"已读取计划 #{plan.id} 的{section}信息",
            content=content,
            sources=[_source("plan", plan.id, f"当前计划 #{plan.id}")],
        )

    async def get_recent_checkins(limit: int = 7) -> dict:
        rows = list(
            (
                await db.execute(
                    select(Checkin)
                    .where(Checkin.user_id == context.user_id)
                    .order_by(desc(Checkin.date), desc(Checkin.id))
                    .limit(limit)
                )
            ).scalars()
        )
        items = [
            {
                "checkin_id": row.id,
                "date": row.date,
                "weight_kg": row.weight,
                "foods": _text(row.foods, 600),
                "exercises": _text(row.exercises, 600),
                "note": _text(row.note, 500),
            }
            for row in rows
        ]
        return _envelope(
            title="近期打卡",
            summary=f"读取到 {len(items)} 条近期打卡",
            content={"items": items},
            sources=[
                _source("checkin", row.id, f"{row.date} 打卡") for row in rows
            ],
        )

    async def get_meal_summary(date: str | None = None) -> dict:
        selected_date = date or str(calendar_date.today())
        rows = list(
            (
                await db.execute(
                    select(MealLog)
                    .where(
                        MealLog.user_id == context.user_id,
                        MealLog.date == selected_date,
                    )
                    .order_by(MealLog.meal_type, MealLog.id)
                )
            ).scalars()
        )
        totals = {
            "calories_kcal": 0.0,
            "protein_g": 0.0,
            "carbs_g": 0.0,
            "fat_g": 0.0,
        }
        meals = []
        for row in rows:
            meal_total = _load_json(row.meal_total_json, {})
            if not isinstance(meal_total, dict):
                meal_total = {}
            for key in totals:
                try:
                    totals[key] += float(meal_total.get(key) or 0)
                except (TypeError, ValueError):
                    continue
            meals.append({
                "meal_log_id": row.id,
                "meal_type": row.meal_type,
                "items": _load_json(row.items_json, []),
                "meal_total": meal_total,
            })
        totals = {key: round(value, 1) for key, value in totals.items()}
        return _envelope(
            title=f"{selected_date} 餐食汇总",
            summary=f"读取到 {len(meals)} 餐记录",
            content={"date": selected_date, "meals": meals, "daily_total": totals},
            sources=[
                _source("meal", row.id, f"{selected_date} {row.meal_type}")
                for row in rows
            ],
        )

    async def search_foods(
        query: str = "",
        category: str | None = None,
        diet_tags: list[str] | None = None,
        limit: int = 8,
    ) -> dict:
        stmt = select(Food)
        if query:
            stmt = stmt.where(or_(
                Food.name_zh.ilike(f"%{query}%"),
                Food.aliases.ilike(f"%{query}%"),
                Food.common_dishes.ilike(f"%{query}%"),
            ))
        if category:
            stmt = stmt.where(Food.category == category)
        for tag in diet_tags or []:
            stmt = stmt.where(Food.diet_tags.ilike(f'%"{tag}"%'))
        foods = list((await db.execute(stmt.order_by(Food.id).limit(limit))).scalars())
        items = [
            {
                "food_id": food.id,
                "name": food.name_zh,
                "category": food.category,
                "per_100g": {
                    "calories_kcal": food.calories_kcal,
                    "protein_g": food.protein_g,
                    "carbs_g": food.carbs_g,
                    "fat_g": food.fat_g,
                    "fiber_g": food.fiber_g,
                },
                "default_portion_g": food.default_portion_g,
                "diet_tags": _load_json(food.diet_tags, []),
            }
            for food in foods
        ]
        return _envelope(
            title="食物库检索",
            summary=f"食物库命中 {len(items)} 项",
            content={"items": items},
            sources=[_source("food", food.id, food.name_zh) for food in foods],
        )

    async def search_exercises(
        query: str = "",
        body_part: str = "",
        equipment: str = "",
        difficulty: str | None = None,
        limit: int = 8,
    ) -> dict:
        stmt = select(Exercise)
        if query:
            stmt = stmt.where(or_(
                Exercise.name.ilike(f"%{query}%"),
                Exercise.name_zh.ilike(f"%{query}%"),
            ))
        if body_part:
            stmt = stmt.where(Exercise.body_part == body_part)
        if equipment:
            stmt = stmt.where(Exercise.equipment == equipment)
        if difficulty:
            stmt = stmt.where(Exercise.difficulty == difficulty)
        rows = list((await db.execute(stmt.order_by(Exercise.id).limit(limit))).scalars())
        items = [
            {
                "exercise_id": row.id,
                "name": row.name_zh or row.name,
                "body_part": row.body_part,
                "equipment": row.equipment,
                "target": row.target,
                "difficulty": row.difficulty,
                "instructions": _load_json(row.instruction_steps_zh, [])[:8],
            }
            for row in rows
        ]
        return _envelope(
            title="动作库检索",
            summary=f"动作库命中 {len(items)} 项",
            content={"items": items},
            sources=[
                _source("exercise", row.id, row.name_zh or row.name) for row in rows
            ],
        )

    async def search_knowledge(
        query: str,
        categories: list[KnowledgeCategory] | None = None,
        limit: int = 5,
    ) -> dict:
        result = await asyncio.to_thread(
            get_retriever().search,
            SearchQuery(query=query, categories=categories or [], top_k=limit),
        )
        docs = [
            {
                "chunk_id": item.chunk_id,
                "title": item.title,
                "content": _text(item.content, 2400),
                "category": item.category,
                "source_name": item.source_name,
                "source_url": _safe_url(item.source_url),
                "evidence_level": item.evidence_level,
                "score": item.score,
            }
            for item in result.documents
        ]
        citations = [
            {
                "chunk_id": item["chunk_id"],
                "title": item["title"],
                "category": item["category"],
                "source_name": item["source_name"],
                "source_url": item["source_url"],
                "evidence_level": item["evidence_level"],
                "score": item["score"],
            }
            for item in docs
        ]
        return _envelope(
            title="专业知识检索",
            summary=f"专业知识命中 {len(docs)} 条",
            content={"documents": docs},
            sources=[
                _source("knowledge", item["chunk_id"], item["title"], item["source_url"])
                for item in docs
            ],
            citations=citations,
        )

    async def search_memories(query: str, limit: int = 8) -> dict:
        result, run_id = await retrieve_user_memory_result(
            db,
            context.user_id,
            query,
            consumer="chat_tool",
            conversation_id=context.conversation_id,
            source_message_id=context.source_message_id,
            limit=limit,
        )
        items = [
            {
                "memory_id": hit.memory.id,
                "memory_type": hit.memory.memory_type,
                "memory_key": hit.memory.memory_key,
                "content_text": _text(hit.memory.content_text, 500),
                "sensitivity": hit.memory.sensitivity,
                "channels": list(hit.channels),
                "rank": hit.final_rank,
            }
            for hit in result.hits
        ]
        memory_ids = [item["memory_id"] for item in items]
        return _envelope(
            title="长期记忆检索",
            summary=f"长期记忆命中 {len(items)} 条",
            content={
                "items": items,
                "retrieval_mode": result.effective_mode,
                "degraded": result.degraded,
            },
            sources=[
                _source("memory", item["memory_id"], item["memory_key"])
                for item in items
            ],
            memory_usage={
                "run_id": run_id,
                "memory_ids": memory_ids,
                "effective_mode": result.effective_mode,
                "degraded": result.degraded,
            },
        )

    definitions = (
        (
            "get_user_profile",
            "读取当前用户的权威健康目标、饮食限制和训练条件。无参数。",
            get_user_profile,
            EmptyArgs,
        ),
        (
            "get_latest_plan",
            "读取当前用户的最新有效计划，可选择摘要、营养、餐单或训练部分。",
            get_latest_plan,
            LatestPlanArgs,
        ),
        (
            "get_recent_checkins",
            "读取当前用户最近的打卡、体重、饮食、训练和备注。",
            get_recent_checkins,
            RecentCheckinsArgs,
        ),
        (
            "get_meal_summary",
            "读取当前用户指定日期的分餐记录和当日营养汇总。",
            get_meal_summary,
            MealSummaryArgs,
        ),
        (
            "search_foods",
            "按名称、分类和饮食标签检索结构化食物营养库。",
            search_foods,
            SearchFoodsArgs,
        ),
        (
            "search_exercises",
            "按名称、部位、器械和难度检索结构化动作库。",
            search_exercises,
            SearchExercisesArgs,
        ),
        (
            "search_knowledge",
            "使用混合检索查询专业营养、训练、动作和风险知识，并返回可引用来源。",
            search_knowledge,
            SearchKnowledgeArgs,
        ),
        (
            "search_memories",
            "使用混合检索查询当前用户已确认且仍有效的长期记忆。",
            search_memories,
            SearchMemoriesArgs,
        ),
    )
    return {
        name: StructuredTool.from_function(
            coroutine=coroutine,
            name=name,
            description=description,
            args_schema=args_schema,
        )
        for name, description, coroutine, args_schema in definitions
    }
