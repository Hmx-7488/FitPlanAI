import json
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User, Plan
from app.schemas.plan import PlanGenerateRequest, PlanResponse, NeedInfoResponse, CalorieInfo, MacrosInfo
from app.graph.workflow import run_workflow
from app.services.supplement_service import generate_supplement_recommendations
from app.services.user_memory_service import recall_user_memories

logger = logging.getLogger(__name__)


async def generate_plan(
    db: AsyncSession, request: PlanGenerateRequest
) -> PlanResponse | NeedInfoResponse:
    """生成减脂计划。返回 PlanResponse 或 NeedInfoResponse。"""
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
        "body_fat_rate": user.body_fat_rate,
        "activity_level": user.activity_level,
        "diet_preference": user.diet_preference,
        "goal_type": user.goal_type,
        "forbidden_foods": json.loads(user.forbidden_foods),
        "injuries": json.loads(user.injuries),
        "allergies": json.loads(user.allergies),
        # 训练条件
        "training_days_per_week": user.training_days_per_week,
        "session_duration_minutes": user.session_duration_minutes,
        "training_location": user.training_location,
        "equipment": json.loads(user.equipment) if user.equipment else [],
        "training_experience": user.training_experience,
        "preferred_training_time": user.preferred_training_time,
        # 中国饮食习惯
        "region_preference": user.region_preference,
        "meal_scenario": user.meal_scenario,
        "prep_time_limit_minutes": user.prep_time_limit_minutes,
    }

    # Long-term memories do not mutate the authoritative profile. They are
    # supplied as a lower-priority, traceable personalization layer.
    try:
        recalled_memories = await recall_user_memories(
            db,
            user.id,
            "生成饮食和训练计划，结合长期目标、偏好、习惯和已确认限制",
        )
    except Exception as exc:
        recalled_memories = []
        logger.warning(
            "Plan memory recall failed; continuing without memories",
            extra={"user_id": user.id, "error_type": type(exc).__name__},
        )
    user_profile["confirmed_memories"] = [
        {
            "id": memory.id,
            "memory_type": memory.memory_type,
            "memory_key": memory.memory_key,
            "content_text": memory.content_text,
            "sensitivity": memory.sensitivity,
        }
        for memory in recalled_memories
    ]

    # 执行LangGraph工作流
    result = await run_workflow(user_profile)

    # Agent 判断信息不完整，返回追问
    if result["status"] == "need_info":
        return NeedInfoResponse(
            missing_fields=result["missing_fields"],
            field_warnings=result["field_warnings"],
            followup_questions=result["followup_questions"],
        )

    # 保存计划到数据库
    # 生成补剂推荐
    goal_type = user.goal_type or "fat_loss"
    injuries_list = json.loads(user.injuries) if user.injuries else []
    allergies_list = json.loads(user.allergies) if user.allergies else []
    forbidden_foods_list = json.loads(user.forbidden_foods) if user.forbidden_foods else []
    supplements = await generate_supplement_recommendations(
        goal_type=goal_type,
        injuries=injuries_list,
        diet_preference=user.diet_preference or "balanced",
        allergies=allergies_list,
        forbidden_foods=forbidden_foods_list,
    )
    supplements_json = json.dumps(supplements, ensure_ascii=False) if supplements else ""

    plan = Plan(
        user_id=user.id,
        daily_calorie_target=result["calorie_info"]["target_calories"],
        calorie_info_json=json.dumps(result["calorie_info"], ensure_ascii=False),
        macros_json=json.dumps(result["macros"], ensure_ascii=False),
        meal_plan=result["meal_plan"],
        meal_plan_json=result.get("meal_plan_json", ""),
        workout_plan=result["workout_plan"],
        workout_plan_json=result.get("workout_plan_json", ""),
        supplements_json=supplements_json,
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
        meal_plan_json=result.get("meal_plan_json", ""),
        workout_plan=result["workout_plan"],
        workout_plan_json=result.get("workout_plan_json", ""),
        supplements_json=supplements_json,
        summary=result["summary"],
        created_at=plan.created_at,
    )
