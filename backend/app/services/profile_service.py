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
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def get_profile(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()
