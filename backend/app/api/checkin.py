from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.schemas.checkin import CheckinCreate, CheckinResponse, ReviewResponse
from app.services.checkin_service import (
    create_checkin,
    get_checkin_history,
    get_user_review,
)

router = APIRouter()


@router.post("/create", response_model=CheckinResponse)
async def create_user_checkin(
    data: CheckinCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建/更新每日打卡"""
    try:
        return await create_checkin(db, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"打卡失败: {str(e)}")


@router.get("/history/{user_id}", response_model=list[CheckinResponse])
async def get_checkin_history_list(
    user_id: int,
    limit: int = Query(default=7, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
):
    """获取打卡历史"""
    return await get_checkin_history(db, user_id, limit)


@router.get("/review/{user_id}", response_model=ReviewResponse)
async def get_user_review_summary(
    user_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取复盘与次日调整建议"""
    try:
        return await get_user_review(db, user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"复盘失败: {str(e)}")
