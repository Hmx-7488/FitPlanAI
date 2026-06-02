import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.user import User
from app.schemas.profile import ProfileCreate, ProfileResponse


async def create_profile(db: AsyncSession, data: ProfileCreate) -> User:
    user = User(
        gender=data.gender,
        age=data.age,
        height=data.height,
        weight=data.weight,
        target_weight=data.target_weight,
        body_fat_rate=data.body_fat_rate,
        activity_level=data.activity_level,
        diet_preference=data.diet_preference,
        goal_type=data.goal_type,
        forbidden_foods=json.dumps(data.forbidden_foods, ensure_ascii=False),
        injuries=json.dumps(data.injuries, ensure_ascii=False),
        allergies=json.dumps(data.allergies, ensure_ascii=False),
        # 训练条件
        training_days_per_week=data.training_days_per_week,
        session_duration_minutes=data.session_duration_minutes,
        training_location=data.training_location,
        equipment=json.dumps(data.equipment, ensure_ascii=False),
        training_experience=data.training_experience,
        preferred_training_time=data.preferred_training_time,
        # 中国饮食习惯
        region_preference=data.region_preference,
        meal_scenario=data.meal_scenario,
        prep_time_limit_minutes=data.prep_time_limit_minutes,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def get_profile(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def update_profile(db: AsyncSession, user_id: int, data: dict) -> User | None:
    """部分更新用户档案，只更新传入的非 None 字段"""
    user = await get_profile(db, user_id)
    if not user:
        return None

    list_fields = {"forbidden_foods", "injuries", "allergies", "equipment"}
    for key, value in data.items():
        if value is not None:
            if key in list_fields:
                setattr(user, key, json.dumps(value, ensure_ascii=False))
            else:
                setattr(user, key, value)

    await db.commit()
    await db.refresh(user)
    return user
