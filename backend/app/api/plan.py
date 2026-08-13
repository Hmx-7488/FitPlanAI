import json
import logging
from pydantic import ValidationError
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select, desc, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.user import Checkin, Exercise, Plan, User
from app.schemas.plan import (
    CalorieAdjustRequest,
    PlanGenerateRequest,
    PlanResponse,
    NeedInfoResponse,
    CalorieInfo,
    MacrosInfo,
    WorkoutAdjustRequest,
    WorkoutPlanData,
)
from app.services.plan_service import generate_plan
from app.tools.calorie_tools import calc_macros

router = APIRouter()
logger = logging.getLogger(__name__)


def _to_plan_response(plan: Plan) -> PlanResponse:
    """从存储的 JSON 还原完整 PlanResponse。"""
    calorie_info = json.loads(plan.calorie_info_json) if plan.calorie_info_json else {}
    macros = json.loads(plan.macros_json) if plan.macros_json else {}

    return PlanResponse(
        id=plan.id,
        user_id=plan.user_id,
        daily_calorie_target=plan.daily_calorie_target,
        calorie_info=CalorieInfo(
            bmr=calorie_info.get("bmr", 0),
            tdee=calorie_info.get("tdee", 0),
            target_calories=calorie_info.get("target_calories", plan.daily_calorie_target),
            deficit=calorie_info.get("deficit", 0),
            goal_type=calorie_info.get("goal_type", "fat_loss"),
            strategy=calorie_info.get("strategy", "calorie_deficit"),
        ),
        macros=MacrosInfo(
            protein_g=macros.get("protein_g", 0),
            carbs_g=macros.get("carbs_g", 0),
            fat_g=macros.get("fat_g", 0),
            fiber_g=macros.get("fiber_g", 0),
            water_ml=macros.get("water_ml", 0),
        ),
        meal_plan=plan.meal_plan,
        meal_plan_json=plan.meal_plan_json if plan.meal_plan_json else None,
        workout_plan=plan.workout_plan,
        workout_plan_json=plan.workout_plan_json if plan.workout_plan_json else None,
        supplements_json=plan.supplements_json if plan.supplements_json else None,
        summary=plan.summary,
        created_at=plan.created_at,
    )


@router.get("/latest/{user_id}", response_model=PlanResponse | None)
async def get_latest_plan(
    user_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取用户最新的计划"""
    stmt = (
        select(Plan)
        .where(Plan.user_id == user_id)
        .order_by(desc(Plan.created_at), desc(Plan.id))
        .limit(1)
    )
    result = await db.execute(stmt)
    plan = result.scalar_one_or_none()
    if not plan:
        return None

    return _to_plan_response(plan)


@router.post("/adjust-calories", response_model=PlanResponse)
async def adjust_calories(
    request: CalorieAdjustRequest,
    db: AsyncSession = Depends(get_db),
):
    """用户确认后写入新的热量目标，并重算三大营养素。

    闭环的写入端：复盘产生的调整草案经用户确认后调用本接口。
    """
    user = await db.get(User, request.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    stmt = (
        select(Plan)
        .where(Plan.user_id == request.user_id)
        .order_by(desc(Plan.created_at), desc(Plan.id))
        .limit(1)
    )
    plan = (await db.execute(stmt)).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="请先生成计划")
    if plan.id != request.plan_id:
        raise HTTPException(status_code=409, detail="计划或打卡记录已更新，请重新生成复盘后再应用调整")
    new_target = request.daily_calorie_target

    calorie_info = json.loads(plan.calorie_info_json) if plan.calorie_info_json else {}
    calorie_info["target_calories"] = new_target
    if calorie_info.get("tdee"):
        calorie_info["deficit"] = calorie_info["tdee"] - new_target
    calorie_info_json = json.dumps(calorie_info, ensure_ascii=False)

    macros = calc_macros(
        new_target,
        user.weight,
        user.activity_level or "medium",
        user.goal_type or "fat_loss",
        user.diet_preference or "balanced",
    )
    macros_json = json.dumps(macros, ensure_ascii=False)

    result = await db.execute(
        update(Plan)
        .where(
            Plan.id == request.plan_id,
            Plan.user_id == request.user_id,
            Plan.daily_calorie_target == request.base_daily_calorie_target,
            Plan.id == (
                select(Plan.id)
                .where(Plan.user_id == request.user_id)
                .order_by(desc(Plan.created_at), desc(Plan.id))
                .limit(1)
                .scalar_subquery()
            ),
            request.source_checkin_id == (
                select(Checkin.id)
                .where(Checkin.user_id == request.user_id)
                .order_by(desc(Checkin.date), desc(Checkin.id))
                .limit(1)
                .scalar_subquery()
            ),
        )
        .values(
            daily_calorie_target=new_target,
            calorie_info_json=calorie_info_json,
            macros_json=macros_json,
        )
    )
    if result.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail="计划或打卡记录已更新，请重新生成复盘后再应用调整")
    await db.commit()
    await db.refresh(plan)
    return _to_plan_response(plan)


@router.post("/generate")
async def generate_fat_loss_plan(
    request: PlanGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    """生成减脂计划。信息不完整时返回 422 + 追问内容。"""
    if not await db.get(User, request.user_id):
        raise HTTPException(status_code=404, detail="用户不存在")
    try:
        result = await generate_plan(db, request)
        # Agent 判断信息不完整
        if isinstance(result, NeedInfoResponse):
            return JSONResponse(
                status_code=422,
                content=result.model_dump(),
            )
        return result
    except ValueError:
        logger.exception("Plan generation produced invalid domain output", extra={"user_id": request.user_id})
        raise HTTPException(status_code=502, detail="计划生成结果无效，请稍后重试")
    except Exception:
        logger.exception("Plan generation failed", extra={"user_id": request.user_id})
        raise HTTPException(status_code=500, detail="计划生成失败，请稍后重试")


@router.post("/adjust-workout", response_model=PlanResponse)
async def adjust_workout(
    request: WorkoutAdjustRequest,
    db: AsyncSession = Depends(get_db),
):
    """用户确认训练调整草案后写入 workout_plan_json。

    闭环的写入端：复盘产生的训练调整草案经用户确认后调用本接口。
    """
    user = await db.get(User, request.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    stmt = (
        select(Plan)
        .where(Plan.user_id == request.user_id)
        .order_by(desc(Plan.created_at), desc(Plan.id))
        .limit(1)
    )
    plan = (await db.execute(stmt)).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="请先生成计划")
    if plan.id != request.plan_id:
        raise HTTPException(status_code=409, detail="计划或打卡记录已更新，请重新生成复盘后再应用调整")

    # 将浏览器提交的 JSON 当作不可信输入，完整验证嵌套结构和数值范围。
    try:
        adjusted = json.loads(request.adjusted_workout_plan_json)
        validated = WorkoutPlanData.model_validate(adjusted)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning(
            "Rejected invalid workout adjustment",
            extra={
                "user_id": request.user_id,
                "plan_id": request.plan_id,
                "error_type": type(exc).__name__,
            },
        )
        raise HTTPException(status_code=400, detail="训练计划格式或数值无效")

    submitted_ids = {
        exercise.exercise_id
        for day in validated.weekly_plan
        for exercise in day.exercises
        if exercise.exercise_id != "manual"
    }
    if submitted_ids:
        known_ids = set((await db.execute(
            select(Exercise.id).where(Exercise.id.in_(submitted_ids))
        )).scalars().all())
        unknown_ids = sorted(submitted_ids - known_ids)
        if unknown_ids:
            raise HTTPException(
                status_code=400,
                detail=f"训练计划包含不存在的动作 ID: {', '.join(unknown_ids[:5])}",
            )

    adjusted_workout_plan_json = validated.model_dump_json(exclude_none=True, by_alias=True)

    # 同步更新文本版本
    text_lines = []
    for day in validated.weekly_plan:
        day_label = f"Day {day.day}"
        if day.theme == "rest":
            text_lines.append(f"**{day_label}** rest")
            continue
        ex_names = []
        for ex in day.exercises:
            ex_names.append(f"{ex.exercise_id} {ex.sets}x{ex.reps}")
        cardio = day.cardio
        cardio_text = f" / cardio: {cardio.type} {cardio.duration_minutes}min" if cardio else ""
        text_lines.append(f"**{day_label}** {day.theme}: {' / '.join(ex_names)}{cardio_text}")
    adjusted_workout_plan = "\n".join(text_lines) if text_lines else plan.workout_plan

    result = await db.execute(
        update(Plan)
        .where(
            Plan.id == request.plan_id,
            Plan.user_id == request.user_id,
            Plan.workout_plan_json == request.base_workout_plan_json,
            Plan.id == (
                select(Plan.id)
                .where(Plan.user_id == request.user_id)
                .order_by(desc(Plan.created_at), desc(Plan.id))
                .limit(1)
                .scalar_subquery()
            ),
            request.source_checkin_id == (
                select(Checkin.id)
                .where(Checkin.user_id == request.user_id)
                .order_by(desc(Checkin.date), desc(Checkin.id))
                .limit(1)
                .scalar_subquery()
            ),
        )
        .values(
            workout_plan_json=adjusted_workout_plan_json,
            workout_plan=adjusted_workout_plan,
        )
    )
    if result.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail="计划或打卡记录已更新，请重新生成复盘后再应用调整")
    await db.commit()
    await db.refresh(plan)
    return _to_plan_response(plan)
