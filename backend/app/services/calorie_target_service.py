import json
import math
from dataclasses import dataclass

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Plan, User
from app.tools.calorie_tools import calc_bmr, calc_daily_calorie


@dataclass(frozen=True)
class ResolvedCalorieTarget:
    plan: Plan | None
    target_calories: int
    tdee: int
    deficit: int
    calorie_info: dict


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return round(number)


def _profile_calorie_info(user: User) -> dict:
    bmr = calc_bmr(
        gender=user.gender,
        weight=user.weight,
        height=user.height,
        age=user.age,
    )
    return calc_daily_calorie(
        bmr=bmr,
        activity_level=user.activity_level or "medium",
        goal_type=user.goal_type or "fat_loss",
    )


async def resolve_calorie_target(
    db: AsyncSession,
    user: User,
) -> ResolvedCalorieTarget:
    """Resolve one authoritative calorie target for all read and write paths."""
    stmt = (
        select(Plan)
        .where(Plan.user_id == user.id)
        .order_by(desc(Plan.created_at), desc(Plan.id))
        .limit(1)
    )
    plan = (await db.execute(stmt)).scalar_one_or_none()
    fallback = _profile_calorie_info(user)
    if not plan:
        target = int(fallback["target_calories"])
        tdee = int(fallback["tdee"])
        return ResolvedCalorieTarget(
            plan=None,
            target_calories=target,
            tdee=tdee,
            deficit=tdee - target,
            calorie_info={**fallback, "target_calories": target, "deficit": tdee - target},
        )

    try:
        stored = json.loads(plan.calorie_info_json) if plan.calorie_info_json else {}
    except (TypeError, json.JSONDecodeError):
        stored = {}
    if not isinstance(stored, dict):
        stored = {}

    target = int(plan.daily_calorie_target)
    tdee = _positive_int(stored.get("tdee")) or int(fallback["tdee"])
    info = {
        **fallback,
        **stored,
        "target_calories": target,
        "tdee": tdee,
        "deficit": tdee - target,
    }
    return ResolvedCalorieTarget(
        plan=plan,
        target_calories=target,
        tdee=tdee,
        deficit=tdee - target,
        calorie_info=info,
    )
