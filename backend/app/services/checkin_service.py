import json
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.models.user import Checkin, User
from app.schemas.checkin import CheckinCreate, CheckinResponse, ReviewResponse
from app.graph.workflow import run_review_workflow


async def create_checkin(db: AsyncSession, data: CheckinCreate) -> CheckinResponse:
    """创建每日打卡"""
    # 验证用户存在
    user = await db.get(User, data.user_id)
    if not user:
        raise ValueError("用户不存在")

    # 检查是否已有当天打卡（允许覆盖）
    existing = await db.execute(
        select(Checkin).where(
            Checkin.user_id == data.user_id,
            Checkin.date == data.date,
        )
    )
    checkin = existing.scalar_one_or_none()

    if checkin:
        # 更新已有打卡
        checkin.foods = data.foods
        checkin.exercises = data.exercises
        checkin.weight = data.weight
        checkin.note = data.note
    else:
        # 新建打卡
        checkin = Checkin(
            user_id=data.user_id,
            date=data.date,
            foods=data.foods,
            exercises=data.exercises,
            weight=data.weight,
            note=data.note,
        )
        db.add(checkin)

    await db.commit()
    await db.refresh(checkin)

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
        .order_by(desc(Checkin.date))
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
        "activity_level": user.activity_level,
        "diet_preference": user.diet_preference,
        "forbidden_foods": json.loads(user.forbidden_foods),
    }

    # 获取最近打卡记录
    result = await db.execute(
        select(Checkin)
        .where(Checkin.user_id == user_id)
        .order_by(desc(Checkin.date))
        .limit(7)
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

    return ReviewResponse(
        user_id=user_id,
        checkin_count=len(checkins),
        recent_checkins=recent_checkins,
        review_summary=review_result["review_summary"],
        next_day_advice=review_result["next_day_advice"],
    )
