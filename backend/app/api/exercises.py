"""动作库检索 API。"""
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.user import Exercise

router = APIRouter()


def _to_dict(ex: Exercise) -> dict:
    """序列化动作记录为前端可用的字典。"""
    return {
        "id": ex.id,
        "name": ex.name,
        "name_zh": ex.name_zh or ex.name,
        "body_part": ex.body_part,
        "equipment": ex.equipment,
        "target": ex.target,
        "muscle_group": ex.muscle_group,
        "secondary_muscles": json.loads(ex.secondary_muscles) if ex.secondary_muscles else [],
        "difficulty": ex.difficulty,
        "instructions_zh": ex.instructions_zh,
        "instruction_steps_zh": json.loads(ex.instruction_steps_zh) if ex.instruction_steps_zh else [],
        "image_url": f"/exercises/media/{ex.image_path.split('/')[-1]}" if ex.image_path else "",
        "gif_url": f"/exercises/media/{ex.gif_path.split('/')[-1]}" if ex.gif_path else "",
    }


@router.get("")
async def search_exercises(
    body_part: str | None = Query(None, description="按部位过滤，如 chest/back/upper legs"),
    equipment: str | None = Query(None, description="按器械过滤，如 barbell/dumbbell/body weight"),
    difficulty: str | None = Query(None, description="按难度过滤：beginner/intermediate/advanced"),
    q: str | None = Query(None, description="按名称模糊搜索"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """检索动作库，支持多条件过滤。"""
    stmt = select(Exercise)

    if body_part:
        stmt = stmt.where(Exercise.body_part == body_part)
    if equipment:
        # 支持逗号分隔多器械
        eqs = [e.strip() for e in equipment.split(",") if e.strip()]
        if len(eqs) == 1:
            stmt = stmt.where(Exercise.equipment == eqs[0])
        else:
            stmt = stmt.where(Exercise.equipment.in_(eqs))
    if difficulty:
        stmt = stmt.where(Exercise.difficulty == difficulty)
    if q:
        stmt = stmt.where(
            (Exercise.name.ilike(f"%{q}%"))
            | (Exercise.name_zh.ilike(f"%{q}%"))
        )

    # 总数
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    # 分页
    stmt = stmt.order_by(Exercise.id).limit(limit).offset(offset)
    result = await db.execute(stmt)
    exercises = result.scalars().all()

    return {
        "total": total,
        "items": [_to_dict(ex) for ex in exercises],
    }


@router.get("/{exercise_id}")
async def get_exercise(
    exercise_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取单个动作详情。"""
    ex = await db.get(Exercise, exercise_id)
    if not ex:
        raise HTTPException(status_code=404, detail="动作不存在")
    return _to_dict(ex)


@router.get("/stats/overview")
async def get_exercise_stats(
    db: AsyncSession = Depends(get_db),
):
    """动作库统计信息（部位/器械/难度分布）。"""
    total = (await db.execute(select(func.count(Exercise.id)))).scalar() or 0

    bp_stmt = (
        select(Exercise.body_part, func.count(Exercise.id))
        .group_by(Exercise.body_part)
        .order_by(func.count(Exercise.id).desc())
    )
    body_parts = {row[0]: row[1] for row in (await db.execute(bp_stmt)).all()}

    eq_stmt = (
        select(Exercise.equipment, func.count(Exercise.id))
        .group_by(Exercise.equipment)
        .order_by(func.count(Exercise.id).desc())
    )
    equipments = {row[0]: row[1] for row in (await db.execute(eq_stmt)).all()}

    diff_stmt = (
        select(Exercise.difficulty, func.count(Exercise.id))
        .group_by(Exercise.difficulty)
    )
    difficulties = {row[0]: row[1] for row in (await db.execute(diff_stmt)).all()}

    return {
        "total": total,
        "by_body_part": body_parts,
        "by_equipment": equipments,
        "by_difficulty": difficulties,
    }
