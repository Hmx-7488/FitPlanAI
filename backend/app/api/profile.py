import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.schemas.profile import ProfileCreate, ProfileResponse
from app.services.profile_service import create_profile, get_profile

router = APIRouter()


@router.post("/create", response_model=ProfileResponse)
async def create_user_profile(data: ProfileCreate, db: AsyncSession = Depends(get_db)):
    user = await create_profile(db, data)
    return ProfileResponse(
        id=user.id,
        gender=user.gender,
        age=user.age,
        height=user.height,
        weight=user.weight,
        target_weight=user.target_weight,
        activity_level=user.activity_level,
        diet_preference=user.diet_preference,
        forbidden_foods=json.loads(user.forbidden_foods),
    )


@router.get("/{user_id}", response_model=ProfileResponse)
async def get_user_profile(user_id: int, db: AsyncSession = Depends(get_db)):
    user = await get_profile(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return ProfileResponse(
        id=user.id,
        gender=user.gender,
        age=user.age,
        height=user.height,
        weight=user.weight,
        target_weight=user.target_weight,
        activity_level=user.activity_level,
        diet_preference=user.diet_preference,
        forbidden_foods=json.loads(user.forbidden_foods),
    )
