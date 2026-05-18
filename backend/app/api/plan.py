import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.user import Plan
from app.schemas.plan import PlanGenerateRequest, PlanResponse, NeedInfoResponse, CalorieInfo, MacrosInfo
from app.services.plan_service import generate_plan

router = APIRouter()


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

    # 从存储的 JSON 还原完整数据
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
