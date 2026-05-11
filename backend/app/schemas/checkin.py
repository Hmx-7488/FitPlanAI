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


class ReviewResponse(BaseModel):
    user_id: int
    checkin_count: int
    recent_checkins: list[CheckinResponse]
    review_summary: str  # AI 复盘总结
    next_day_advice: str  # 次日调整建议
