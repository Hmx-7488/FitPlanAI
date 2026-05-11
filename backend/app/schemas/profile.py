from pydantic import BaseModel
from typing import Optional


class ProfileCreate(BaseModel):
    gender: str  # male / female
    age: int
    height: float  # cm
    weight: float  # kg
    target_weight: float  # kg
    activity_level: str = "medium"  # low / medium / high / very_high
    diet_preference: str = "balanced"  # balanced / high_protein / low_carb / vegetarian
    forbidden_foods: list[str] = []


class ProfileResponse(BaseModel):
    id: int
    gender: str
    age: int
    height: float
    weight: float
    target_weight: float
    activity_level: str
    diet_preference: str
    forbidden_foods: list[str]

    class Config:
        from_attributes = True
