import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.user import Plan, User
from app.schemas.plan import (
    CalorieAdjustRequest,
    PlanGenerateRequest,
    PlanResponse,
    NeedInfoResponse,
    CalorieInfo,
    MacrosInfo,
)
from app.services.plan_service import generate_plan
from app.tools.calorie_tools import calc_macros

router = APIRouter()


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
        workout_plan=plan.workout_plan,
        summary=plan.summary,
        created_at=plan.created_at,
    )


@router.get("/latest/{user_id}", response_model=PlanResponse | None)
async def get_latest_plan(
    user_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取用户最新的计划"""
    stmt = select(Plan).where(Plan.user_id == user_id).order_by(desc(Plan.created_at)).limit(1)
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
        .order_by(desc(Plan.created_at))
        .limit(1)
    )
    plan = (await db.execute(stmt)).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="请先生成计划")

    new_target = request.daily_calorie_target
    plan.daily_calorie_target = new_target

    calorie_info = json.loads(plan.calorie_info_json) if plan.calorie_info_json else {}
    calorie_info["target_calories"] = new_target
    if calorie_info.get("tdee"):
        calorie_info["deficit"] = calorie_info["tdee"] - new_target
    plan.calorie_info_json = json.dumps(calorie_info, ensure_ascii=False)

    macros = calc_macros(
        new_target,
        user.weight,
        user.activity_level or "medium",
        user.goal_type or "fat_loss",
    )
    plan.macros_json = json.dumps(macros, ensure_ascii=False)

    await db.commit()
    await db.refresh(plan)
    return _to_plan_response(plan)


@router.post("/generate")
async def generate_fat_loss_plan(
    request: PlanGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    """生成减脂计划。信息不完整时返回 422 + 追问内容。"""
    try:
        result = await generate_plan(db, request)
        # Agent 判断信息不完整
        if isinstance(result, NeedInfoResponse):
            return JSONResponse(
                status_code=422,
                content=result.model_dump(),
            )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成计划失败: {str(e)}")
