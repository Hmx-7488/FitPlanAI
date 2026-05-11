import json
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User, Plan
from app.schemas.plan import PlanGenerateRequest, PlanResponse, CalorieInfo, MacrosInfo
from app.graph.workflow import run_workflow


async def generate_plan(db: AsyncSession, request: PlanGenerateRequest) -> PlanResponse:
    """生成减脂计划"""
    # 获取用户信息
    user = await db.get(User, request.user_id)
    if not user:
        raise ValueError("用户不存在")

    user_profile = {
        "gender": user.gender,
        "age": user.age,
        "height": user.height,
        "weight": user.weight,
        "target_weight": user.target_weight,
        "activity_level": user.activity_level,
        "diet_preference": user.diet_preference,
        "forbidden_foods": json.loads(user.forbidden_foods),
    }

    # 执行LangGraph工作流
    result = await run_workflow(user_profile)

    # 保存计划到数据库
    plan = Plan(
        user_id=user.id,
        daily_calorie_target=result["calorie_info"]["target_calories"],
        meal_plan=result["meal_plan"],
        workout_plan=result["workout_plan"],
        summary=result["summary"],
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)

    return PlanResponse(
        id=plan.id,
        user_id=plan.user_id,
        daily_calorie_target=plan.daily_calorie_target,
        calorie_info=CalorieInfo(**result["calorie_info"]),
        macros=MacrosInfo(**result["macros"]),
        meal_plan=result["meal_plan"],
        workout_plan=result["workout_plan"],
        summary=result["summary"],
    )
