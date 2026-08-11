from pydantic import BaseModel
from typing import Optional


class CheckinCreate(BaseModel):
    user_id: int
    date: str  # YYYY-MM-DD
    foods: str = ""  # 当天饮食记录（自由文本）
    exercises: str = ""  # 当天运动记录（自由文本）
    weight: Optional[float] = None  # 当天体重
    note: str = ""  # 备注（感受、状态等）


class CheckinResponse(BaseModel):
    id: int
    user_id: int
    date: str
    foods: str
    exercises: str
    weight: Optional[float]
    note: str
    feedback: Optional[str] = None  # AI 复盘反馈

    class Config:
        from_attributes = True


class CalorieAdjustment(BaseModel):
    """热量目标调整草案（仅建议，需用户确认后才写入计划）"""

    current_target: int
    suggested_target: int
    delta_kcal: int
    weekly_change_pct: float  # 每周体重变化百分比
    reason: str
    basis: str  # 调整依据说明


class WorkoutAdjustmentChange(BaseModel):
    """训练调整单条变更"""
    day: str  # "all" 或具体天数 "1"/"2"/...
    action: str  # replace/reduce_volume/increase_cardio/increase_volume
    old_exercise_keyword: Optional[str] = None  # replace 时的旧动作关键词
    detail: Optional[str] = None  # 具体调整说明
    reason: str


class WorkoutAdjustment(BaseModel):
    """训练计划调整草案（仅建议，需用户确认后才写入计划）"""
    reason: str
    changes: list[WorkoutAdjustmentChange]
    risk_notes: list[str] = []


class ReviewResponse(BaseModel):
    user_id: int
    checkin_count: int
    recent_checkins: list[CheckinResponse]
    review_summary: str  # AI 复盘总结
    next_day_advice: str  # 次日调整建议
    calorie_adjustment: Optional[CalorieAdjustment] = None  # 热量调整草案
    workout_adjustment: Optional[WorkoutAdjustment] = None  # 训练调整草案
