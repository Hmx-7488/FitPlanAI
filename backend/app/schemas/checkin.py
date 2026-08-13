from datetime import date as calendar_date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CheckinCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int = Field(gt=0)
    date: str = Field(min_length=10, max_length=10)
    foods: str = Field(default="", max_length=5000)
    exercises: str = Field(default="", max_length=5000)
    weight: Optional[float] = Field(default=None, ge=20, le=300)
    note: str = Field(default="", max_length=2000)

    @field_validator("date")
    @classmethod
    def validate_iso_date(cls, value: str) -> str:
        try:
            parsed = calendar_date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("date must use YYYY-MM-DD format") from exc
        if parsed.isoformat() != value:
            raise ValueError("date must use YYYY-MM-DD format")
        return value


class CheckinResponse(BaseModel):
    id: int
    user_id: int
    date: str
    foods: str
    exercises: str
    weight: Optional[float]
    note: str
    feedback: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class CalorieAdjustment(BaseModel):
    current_target: int
    suggested_target: int
    delta_kcal: int
    weekly_change_pct: float
    reason: str
    basis: str


class WorkoutAdjustmentChange(BaseModel):
    day: str
    action: str
    old_exercise_keyword: Optional[str] = None
    detail: Optional[str] = None
    reason: str


class WorkoutAdjustment(BaseModel):
    reason: str
    changes: list[WorkoutAdjustmentChange]
    risk_notes: list[str] = Field(default_factory=list)


class ReviewResponse(BaseModel):
    user_id: int
    checkin_count: int
    recent_checkins: list[CheckinResponse]
    review_summary: str
    next_day_advice: str
    source_plan_id: int | None = None
    source_daily_calorie_target: int | None = None
    source_workout_plan_json: str | None = None
    source_checkin_id: int
    calorie_adjustment: Optional[CalorieAdjustment] = None
    workout_adjustment: Optional[WorkoutAdjustment] = None
