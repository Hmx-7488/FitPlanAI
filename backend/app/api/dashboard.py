"""Dashboard 聚合 API — 首页数据汇总"""
import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.time import today_str
from app.models.user import User, Plan, Checkin, MealLog
from app.tools.calorie_tools import calc_bmr, calc_daily_calorie

router = APIRouter()


def _compute_streak(checkin_dates: list[str], today: str) -> int:
    """计算连续打卡天数。

    规则：
    - 今天已打卡：从今天往前连续计数；
    - 今天尚未打卡：从昨天往前计数（今天还有机会打卡，不清零）；
    - 最近一次打卡早于昨天：连续已中断，返回 0。
    """
    dates = sorted({d for d in checkin_dates if d}, reverse=True)
    if not dates:
        return 0

    today_date = datetime.strptime(today, "%Y-%m-%d").date()
    latest = datetime.strptime(dates[0], "%Y-%m-%d").date()
    if latest < today_date - timedelta(days=1):
        return 0

    streak = 0
    expected = latest
    for d_str in dates:
        d = datetime.strptime(d_str, "%Y-%m-%d").date()
        if d == expected:
            streak += 1
            expected -= timedelta(days=1)
        elif d < expected:
            break
    return streak


@router.get("/{user_id}")
async def get_dashboard(user_id: int, db: AsyncSession = Depends(get_db)):
    """获取首页 Dashboard 聚合数据"""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    today = today_str()

    # 1. 用户基础信息
    profile_summary = {
        "id": user.id,
        "gender": user.gender,
        "age": user.age,
        "height": user.height,
        "weight": user.weight,
        "target_weight": user.target_weight,
        "goal_type": user.goal_type or "fat_loss",
        "body_fat_rate": user.body_fat_rate,
    }

    # 2. 最新计划
    plan_stmt = (
        select(Plan)
        .where(Plan.user_id == user_id)
        .order_by(desc(Plan.created_at))
        .limit(1)
    )
    plan_result = await db.execute(plan_stmt)
    plan = plan_result.scalar_one_or_none()

    latest_plan = None
    if plan:
        macros = json.loads(plan.macros_json) if plan.macros_json else {}
        latest_plan = {
            "id": plan.id,
            "daily_calorie_target": plan.daily_calorie_target,
            "protein_g": macros.get("protein_g", 0),
            "carbs_g": macros.get("carbs_g", 0),
            "fat_g": macros.get("fat_g", 0),
            "summary": plan.summary[:200] if plan.summary else "",
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
        }

    # 3. 今日热量汇总
    bmr = calc_bmr(
        gender=user.gender,
        weight=user.weight,
        height=user.height,
        age=user.age,
    )
    calorie_info = calc_daily_calorie(
        bmr=bmr,
        activity_level=user.activity_level or "medium",
        goal_type=user.goal_type or "fat_loss",
    )
    target_kcal = calorie_info["target_calories"]

    meal_stmt = select(MealLog).where(
        MealLog.user_id == user_id, MealLog.date == today
    )
    meal_result = await db.execute(meal_stmt)
    today_meals = meal_result.scalars().all()

    consumed_kcal = 0
    consumed_protein = 0.0
    consumed_carbs = 0.0
    consumed_fat = 0.0
    for m in today_meals:
        total = json.loads(m.meal_total_json) if m.meal_total_json else {}
        consumed_kcal += total.get("calories_kcal", 0)
        consumed_protein += total.get("protein_g", 0)
        consumed_carbs += total.get("carbs_g", 0)
        consumed_fat += total.get("fat_g", 0)

    meal_summary = {
        "date": today,
        "target_kcal": target_kcal,
        "consumed_kcal": consumed_kcal,
        "remaining_kcal": max(target_kcal - consumed_kcal, 0),
        "progress_pct": round(consumed_kcal / target_kcal * 100, 1) if target_kcal > 0 else 0,
        "meal_count": len(today_meals),
        "consumed_protein": round(consumed_protein, 1),
        "consumed_carbs": round(consumed_carbs, 1),
        "consumed_fat": round(consumed_fat, 1),
    }

    # 4. 最近打卡
    checkin_stmt = (
        select(Checkin)
        .where(Checkin.user_id == user_id)
        .order_by(desc(Checkin.date))
        .limit(7)
    )
    checkin_result = await db.execute(checkin_stmt)
    recent_checkins = checkin_result.scalars().all()

    # 连续打卡天数（独立查询，不受最近 7 条限制）
    streak_stmt = (
        select(Checkin.date)
        .where(Checkin.user_id == user_id)
        .order_by(desc(Checkin.date))
        .limit(365)
    )
    streak_dates = list((await db.execute(streak_stmt)).scalars().all())
    streak = _compute_streak(streak_dates, today)

    # 累计打卡天数（真实总数，而非最近 7 天的条数）
    total_stmt = select(func.count(Checkin.id)).where(Checkin.user_id == user_id)
    total_days = (await db.execute(total_stmt)).scalar() or 0

    latest_weight = recent_checkins[0].weight if recent_checkins and recent_checkins[0].weight else user.weight

    checkin_summary = {
        "streak": streak,
        "total_days": total_days,
        "latest_weight": latest_weight,
        "weight_change": round(latest_weight - user.weight, 1) if latest_weight else 0,
        "today_checked": any(c.date == today for c in recent_checkins),
    }

    return {
        "profile": profile_summary,
        "latest_plan": latest_plan,
        "meal_summary": meal_summary,
        "checkin_summary": checkin_summary,
    }
