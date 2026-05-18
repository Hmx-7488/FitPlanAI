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

    class Config:
        from_attributes = True
