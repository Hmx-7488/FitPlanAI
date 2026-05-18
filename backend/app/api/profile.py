import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.schemas.profile import ProfileCreate, ProfileResponse
from app.services.profile_service import create_profile, get_profile

router = APIRouter()


def _user_to_response(user) -> ProfileResponse:
    return ProfileResponse(
        id=user.id,
        gender=user.gender,
        age=user.age,
        height=user.height,
        weight=user.weight,
        target_weight=user.target_weight,
        body_fat_rate=user.body_fat_rate,
        activity_level=user.activity_level,
        diet_preference=user.diet_preference,
        goal_type=user.goal_type,
        forbidden_foods=json.loads(user.forbidden_foods),
        injuries=json.loads(user.injuries),
        allergies=json.loads(user.allergies),
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
