"""食物热量库检索 API。"""
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.user import Food

router = APIRouter()


def _to_dict(food: Food) -> dict:
    """Serialize food record for frontend."""
    return {
        "id": food.id,
        "name_zh": food.name_zh,
        "aliases": json.loads(food.aliases) if food.aliases else [],
        "category": food.category,
        "calories_kcal": food.calories_kcal,
        "protein_g": food.protein_g,
        "carbs_g": food.carbs_g,
        "fat_g": food.fat_g,
        "fiber_g": food.fiber_g,
        "sodium_mg": food.sodium_mg,
        "default_portion_g": food.default_portion_g,
        "default_portion_name": food.default_portion_name,
        "diet_tags": json.loads(food.diet_tags) if food.diet_tags else [],
        "common_dishes": json.loads(food.common_dishes) if food.common_dishes else [],
    }


@router.get("")
async def search_foods(
    category: str | None = Query(None, description="protein/carb/vegetable/fruit/fat/dairy/beverage"),
    diet_tags: str | None = Query(None, description="Comma-separated tags: high_protein,low_carb,..."),
    q: str | None = Query(None, description="Search by name or alias"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Search food database with optional filters."""
    stmt = select(Food)

    if category:
        stmt = stmt.where(Food.category == category)
    if q:
        stmt = stmt.where(
            (Food.name_zh.ilike(f"%{q}%"))
            | (Food.aliases.ilike(f"%{q}%"))
            | (Food.common_dishes.ilike(f"%{q}%"))
        )

    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(Food.id).limit(limit).offset(offset)
    result = await db.execute(stmt)
    foods = result.scalars().all()

    return {
        "total": total,
        "items": [_to_dict(f) for f in foods],
    }


@router.get("/{food_id}")
async def get_food(
    food_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get single food detail."""
    food = await db.get(Food, food_id)
    if not food:
        raise HTTPException(status_code=404, detail="Food not found")
    return _to_dict(food)


@router.get("/search/dish")
async def search_by_dish(
    dish: str = Query(..., description="Dish name to match"),
    db: AsyncSession = Depends(get_db),
):
    """Match a dish name to food database entries.

    Used by meal recognition to anchor LLM estimates with real data.
    """
    stmt = select(Food).where(
        (Food.name_zh.ilike(f"%{dish}%"))
        | (Food.aliases.ilike(f"%{dish}%"))
        | (Food.common_dishes.ilike(f"%{dish}%"))
    ).limit(10)
    result = await db.execute(stmt)
    foods = result.scalars().all()

    return {
        "query": dish,
        "matched": len(foods),
        "items": [_to_dict(f) for f in foods],
    }
