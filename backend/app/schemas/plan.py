from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class PlanGenerateRequest(BaseModel):
    user_id: int


class CalorieAdjustRequest(BaseModel):
    """用户确认后的热量目标调整（写入最新计划）"""

    user_id: int
    daily_calorie_target: int = Field(ge=800, le=5000)


class CalorieInfo(BaseModel):
    bmr: int
    tdee: int
    target_calories: int
    deficit: int
    goal_type: str = "fat_loss"
    strategy: str = "calorie_deficit"


class MacrosInfo(BaseModel):
    protein_g: int
    carbs_g: int
    fat_g: int
    fiber_g: int
    water_ml: int


class PlanResponse(BaseModel):
    status: str = "plan"
    id: int
    user_id: int
    daily_calorie_target: int
    calorie_info: CalorieInfo
    macros: MacrosInfo
    meal_plan: str
    workout_plan: str
    summary: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class NeedInfoResponse(BaseModel):
    status: str = "need_info"
    missing_fields: list[str]
    field_warnings: list[str]
    followup_questions: str
