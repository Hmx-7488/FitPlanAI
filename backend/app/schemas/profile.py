from pydantic import BaseModel
from typing import Optional


class ProfileCreate(BaseModel):
    gender: str  # male / female
    age: int
    height: float  # cm
    weight: float  # kg
    target_weight: float  # kg
    body_fat_rate: Optional[float] = None  # 体脂率，选填
    activity_level: str = "medium"  # low / medium / high / very_high
    diet_preference: str = "balanced"  # balanced / high_protein / low_carb / vegetarian
    goal_type: str = "fat_loss"  # fat_loss / muscle_gain
    forbidden_foods: list[str] = []
    injuries: list[str] = []  # 伤病，如 knee_pain, back_pain
    allergies: list[str] = []  # 过敏，如 shrimp, milk
    # 训练条件
    training_days_per_week: int = 3  # 每周训练天数
    session_duration_minutes: int = 60  # 每次训练时长(分钟)
    training_location: str = "gym"  # gym / home / outdoor
    equipment: list[str] = []  # 可用器械列表
    training_experience: str = "beginner"  # beginner / intermediate / advanced
    preferred_training_time: str = "morning"  # morning / afternoon / evening
    # 中国饮食习惯
    region_preference: str = "balanced"  # south_china / north_china / sichuan / cantonese / balanced
    meal_scenario: str = "home_cooking"  # home_cooking / takeout / canteen / convenience_store
    prep_time_limit_minutes: int = 30  # 备餐时间限制(分钟)


class ProfileUpdate(BaseModel):
    """部分更新（所有字段可选）"""
    gender: str | None = None
    age: int | None = None
    height: float | None = None
    weight: float | None = None
    target_weight: float | None = None
    body_fat_rate: float | None = None
    activity_level: str | None = None
    diet_preference: str | None = None
    goal_type: str | None = None
    forbidden_foods: list[str] | None = None
    injuries: list[str] | None = None
    allergies: list[str] | None = None
    training_days_per_week: int | None = None
    session_duration_minutes: int | None = None
    training_location: str | None = None
    equipment: list[str] | None = None
    training_experience: str | None = None
    preferred_training_time: str | None = None
    region_preference: str | None = None
    meal_scenario: str | None = None
    prep_time_limit_minutes: int | None = None


class ProfileResponse(BaseModel):
    id: int
    gender: str
    age: int
    height: float
    weight: float
    target_weight: float
    body_fat_rate: Optional[float]
    activity_level: str
    diet_preference: str
    goal_type: str
    forbidden_foods: list[str]
    injuries: list[str]
    allergies: list[str]
    # 训练条件
    training_days_per_week: int
    session_duration_minutes: int
    training_location: str
    equipment: list[str]
    training_experience: str
    preferred_training_time: str
    # 中国饮食习惯
    region_preference: str
    meal_scenario: str
    prep_time_limit_minutes: int

    class Config:
        from_attributes = True
