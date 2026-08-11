from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PlanGenerateRequest(BaseModel):
    user_id: int


class CalorieAdjustRequest(BaseModel):
    """用户确认后的热量目标调整（写入最新计划）"""

    user_id: int
    daily_calorie_target: int = Field(ge=800, le=5000)


class WorkoutExercise(BaseModel):
    """用户确认写入的单个训练动作。"""

    model_config = ConfigDict(extra="forbid")

    exercise_id: str = Field(min_length=1, max_length=64)
    sets: int = Field(ge=1, le=20)
    reps: str | int = ""
    rest_seconds: int | None = Field(default=None, ge=0, le=900)
    flagged_for_replacement: str | None = Field(
        default=None,
        alias="_flagged_for_replacement",
        max_length=300,
    )

    @field_validator("reps")
    @classmethod
    def validate_reps(cls, value: str | int) -> str | int:
        if isinstance(value, bool):
            raise ValueError("reps must be text or a positive integer")
        if isinstance(value, int):
            if not 1 <= value <= 1000:
                raise ValueError("reps integer is out of range")
            return value
        normalized = value.strip()
        if not normalized or len(normalized) > 40:
            raise ValueError("reps text is invalid")
        return normalized


class WorkoutCardio(BaseModel):
    """训练日中的可选有氧安排。"""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, max_length=100)
    duration_minutes: int = Field(ge=1, le=300)
    intensity: str | None = Field(default=None, max_length=100)


class WorkoutDay(BaseModel):
    """结构化周计划中的一天。"""

    model_config = ConfigDict(extra="forbid")

    day: int = Field(ge=1, le=7)
    theme: str = Field(min_length=1, max_length=100)
    duration_minutes: int | None = Field(default=None, ge=1, le=300)
    exercises: list[WorkoutExercise] = Field(default_factory=list, max_length=12)
    cardio: WorkoutCardio | None = None

    @model_validator(mode="after")
    def validate_rest_day(self):
        if self.theme.lower() in {"rest", "休息"} and (self.exercises or self.cardio):
            raise ValueError("rest day cannot contain exercises or cardio")
        if self.theme.lower() not in {"rest", "休息"} and not (self.exercises or self.cardio):
            raise ValueError("training day must contain exercises or cardio")
        return self


class WorkoutExcludedExercise(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=300)


class WorkoutPlanData(BaseModel):
    """允许确认写入的结构化训练计划边界。"""

    model_config = ConfigDict(extra="forbid")

    weekly_plan: list[WorkoutDay] = Field(min_length=1, max_length=7)
    excluded: list[WorkoutExcludedExercise] = Field(default_factory=list, max_length=100)
    warmup: list[str] = Field(default_factory=list, max_length=30)
    notes: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_weekly_plan(self):
        days = [day.day for day in self.weekly_plan]
        if len(days) != len(set(days)):
            raise ValueError("weekly_plan contains duplicate days")
        if all(day.theme.lower() in {"rest", "休息"} for day in self.weekly_plan):
            raise ValueError("workout plan cannot contain only rest days")
        return self


class WorkoutAdjustRequest(BaseModel):
    """用户确认训练调整草案后的写入请求。"""

    user_id: int
    plan_id: int
    base_workout_plan_json: str = Field(max_length=100_000)
    adjusted_workout_plan_json: str = Field(min_length=2, max_length=100_000)


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
    meal_plan_json: Optional[str] = None  # 结构化饮食计划
    workout_plan: str
    workout_plan_json: Optional[str] = None  # 结构化训练计划
    supplements_json: Optional[str] = None  # 补剂推荐 JSON
    summary: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class NeedInfoResponse(BaseModel):
    status: str = "need_info"
    missing_fields: list[str]
    field_warnings: list[str]
    followup_questions: str
