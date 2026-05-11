from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.schemas.plan import PlanGenerateRequest, PlanResponse
from app.services.plan_service import generate_plan

router = APIRouter()


@router.post("/generate", response_model=PlanResponse)
async def generate_fat_loss_plan(
    request: PlanGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await generate_plan(db, request)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成计划失败: {str(e)}")
