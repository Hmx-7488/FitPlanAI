import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from app.models.user import Checkin, User
from app.schemas.checkin import (
    CalorieAdjustment,
    CheckinCreate,
    CheckinResponse,
    ReviewResponse,
    WorkoutAdjustment,
)
from app.graph.workflow import run_review_workflow
from app.services.adjustment_service import compute_calorie_adjustment
from app.services.calorie_target_service import (
    ResolvedCalorieTarget,
    resolve_calorie_target,
)


async def create_checkin(db: AsyncSession, data: CheckinCreate) -> CheckinResponse:
    """创建每日打卡"""
    # 验证用户存在
    user = await db.get(User, data.user_id)
    if not user:
        raise ValueError("用户不存在")

    values = {
        "user_id": data.user_id,
        "date": data.date,
        "foods": data.foods,
        "exercises": data.exercises,
        "weight": data.weight,
        "note": data.note,
    }
    # REPLACE intentionally assigns a new id when a day's evidence changes.
    # Review drafts use that id as their optimistic-concurrency source version.
    stmt = sqlite_insert(Checkin).values(**values).prefix_with("OR REPLACE").returning(Checkin.id)
    checkin_id = (await db.execute(stmt)).scalar_one()
    await db.commit()
    checkin = await db.get(Checkin, checkin_id)

    return CheckinResponse(
        id=checkin.id,
        user_id=checkin.user_id,
        date=checkin.date,
        foods=checkin.foods,
        exercises=checkin.exercises,
        weight=checkin.weight,
        note=checkin.note,
    )


async def get_checkin_history(
    db: AsyncSession, user_id: int, limit: int = 7
) -> list[CheckinResponse]:
    """获取打卡历史"""
    result = await db.execute(
        select(Checkin)
        .where(Checkin.user_id == user_id)
        .order_by(desc(Checkin.date), desc(Checkin.id))
        .limit(limit)
    )
    checkins = result.scalars().all()

    return [
        CheckinResponse(
            id=c.id,
            user_id=c.user_id,
            date=c.date,
            foods=c.foods,
            exercises=c.exercises,
            weight=c.weight,
            note=c.note,
        )
        for c in checkins
    ]


async def get_user_review(db: AsyncSession, user_id: int) -> ReviewResponse:
    """获取用户复盘与次日调整建议"""
    # 获取用户信息
    user = await db.get(User, user_id)
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

    # 获取最近 21 条记录，使“两周平台期”规则在每日打卡场景下可达。
    result = await db.execute(
        select(Checkin)
        .where(Checkin.user_id == user_id)
        .order_by(desc(Checkin.date), desc(Checkin.id))
        .limit(21)
    )
    checkins = result.scalars().all()

    if not checkins:
        raise ValueError("暂无打卡记录，请先完成至少一天的打卡")

    # 构建打卡历史文本
    checkin_history = []
    for c in checkins:
        entry = f"日期: {c.date}"
        if c.weight:
            entry += f" | 体重: {c.weight}kg"
        if c.foods:
            entry += f" | 饮食: {c.foods}"
        if c.exercises:
            entry += f" | 运动: {c.exercises}"
        if c.note:
            entry += f" | 备注: {c.note}"
        checkin_history.append(entry)

    # 执行复盘工作流
    review_result = await run_review_workflow(user_profile, checkin_history)

    recent_checkins = [
        CheckinResponse(
            id=c.id,
            user_id=c.user_id,
            date=c.date,
            foods=c.foods,
            exercises=c.exercises,
            weight=c.weight,
            note=c.note,
        )
        for c in checkins
    ]

    # 闭环：基于体重趋势计算热量调整草案（仅建议，确认后才写入）
    calorie_target = await resolve_calorie_target(db, user)
    adjustment = await _build_calorie_adjustment(db, user, calorie_target)

    # 训练调整草案
    workout_adj_data = review_result.get("workout_adjustment")
    workout_adjustment = WorkoutAdjustment(**workout_adj_data) if workout_adj_data else None

    return ReviewResponse(
        user_id=user_id,
        checkin_count=len(checkins),
        recent_checkins=recent_checkins,
        review_summary=review_result["review_summary"],
        next_day_advice=review_result["next_day_advice"],
        source_plan_id=calorie_target.plan.id if calorie_target.plan else None,
        source_daily_calorie_target=calorie_target.target_calories,
        source_workout_plan_json=(
            calorie_target.plan.workout_plan_json if calorie_target.plan else None
        ),
        source_checkin_id=checkins[0].id,
        calorie_adjustment=adjustment,
        workout_adjustment=workout_adjustment,
    )


async def _build_calorie_adjustment(
    db: AsyncSession,
    user: User,
    resolved: ResolvedCalorieTarget | None = None,
) -> CalorieAdjustment | None:
    """汇总当前热量目标与体重趋势，生成调整草案。"""
    resolved = resolved or await resolve_calorie_target(db, user)
    current_target = resolved.target_calories

    # 体重趋势：最近 60 次称重，按日期升序
    weight_stmt = (
        select(Checkin.date, Checkin.weight)
        .where(Checkin.user_id == user.id, Checkin.weight.isnot(None))
        .order_by(desc(Checkin.date))
        .limit(60)
    )
    rows = (await db.execute(weight_stmt)).all()
    points = sorted(
        ((row.date, float(row.weight)) for row in rows if row.weight),
        key=lambda item: item[0],
    )

    result = compute_calorie_adjustment(
        goal_type=user.goal_type or "fat_loss",
        weight_points=points,
        current_target=current_target,
    )
    return CalorieAdjustment(**result) if result else None
