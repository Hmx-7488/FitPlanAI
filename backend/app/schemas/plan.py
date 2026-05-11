from pydantic import BaseModel


class PlanGenerateRequest(BaseModel):
    user_id: int


class CalorieInfo(BaseModel):
    bmr: int
    tdee: int
    target_calories: int
    deficit: int


class MacrosInfo(BaseModel):
    protein_g: int
    carbs_g: int
    fat_g: int
    fiber_g: int
    water_ml: int


class PlanResponse(BaseModel):
    id: int
    user_id: int
    daily_calorie_target: int
    calorie_info: CalorieInfo
    macros: MacrosInfo
    meal_plan: str
    workout_plan: str
    summary: str

    class Config:
        from_attributes = True
