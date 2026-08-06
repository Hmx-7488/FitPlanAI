import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.schemas.profile import ProfileCreate, ProfileUpdate, ProfileResponse
from app.services.profile_service import create_profile, get_profile, update_profile

router = APIRouter()


def _user_to_response(user) -> ProfileResponse:
    return ProfileResponse(
        id=user.id,
        gender=user.gender,
        age=user.age,
        height=user.height,
        weight=user.weight,
        target_weight=user.target_weight,
        target_weeks=user.target_weeks,
        body_fat_rate=user.body_fat_rate,
        activity_level=user.activity_level,
        diet_preference=user.diet_preference,
        goal_type=user.goal_type,
        forbidden_foods=json.loads(user.forbidden_foods),
        injuries=json.loads(user.injuries),
        allergies=json.loads(user.allergies),
        # 训练条件
        training_days_per_week=user.training_days_per_week,
        session_duration_minutes=user.session_duration_minutes,
        training_location=user.training_location,
        equipment=json.loads(user.equipment) if user.equipment else [],
        training_experience=user.training_experience,
        preferred_training_time=user.preferred_training_time,
        # 中国饮食习惯
        region_preference=user.region_preference,
        meal_scenario=user.meal_scenario,
        prep_time_limit_minutes=user.prep_time_limit_minutes,
    )


@router.post("/create", response_model=ProfileResponse)
async def create_user_profile(data: ProfileCreate, db: AsyncSession = Depends(get_db)):
    user = await create_profile(db, data)
    return _user_to_response(user)


@router.get("/{user_id}", response_model=ProfileResponse)
async def get_user_profile(user_id: int, db: AsyncSession = Depends(get_db)):
    user = await get_profile(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _user_to_response(user)


@router.patch("/{user_id}", response_model=ProfileResponse)
async def update_user_profile(
    user_id: int,
    data: ProfileUpdate,
    db: AsyncSession = Depends(get_db),
):
    """部分更新用户档案"""
    update_data = data.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="没有要更新的字段")
    user = await update_profile(db, user_id, update_data)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _user_to_response(user)
