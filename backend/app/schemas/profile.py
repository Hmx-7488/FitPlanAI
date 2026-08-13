from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


Gender = Literal["male", "female"]
ActivityLevel = Literal["low", "medium", "high", "very_high"]
DietPreference = Literal["balanced", "high_protein", "low_carb", "vegetarian"]
GoalType = Literal["fat_loss", "muscle_gain"]
TrainingLocation = Literal["gym", "home", "outdoor"]
TrainingExperience = Literal["beginner", "intermediate", "advanced"]
TrainingTime = Literal["morning", "afternoon", "evening"]
RegionPreference = Literal[
    "south_china", "north_china", "sichuan", "cantonese", "balanced"
]
MealScenario = Literal[
    "home_cooking", "takeout", "canteen", "convenience_store"
]
ProfileListItem = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]


class ProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gender: Gender
    age: int = Field(ge=10, le=100)
    height: float = Field(ge=100, le=250)
    weight: float = Field(ge=30, le=200)
    target_weight: float = Field(ge=30, le=200)
    target_weeks: Optional[int] = Field(default=None, ge=1, le=104)
    body_fat_rate: Optional[float] = Field(default=None, ge=3, le=60)
    activity_level: ActivityLevel = "medium"
    diet_preference: DietPreference = "balanced"
    goal_type: GoalType = "fat_loss"
    forbidden_foods: list[ProfileListItem] = Field(default_factory=list, max_length=50)
    injuries: list[ProfileListItem] = Field(default_factory=list, max_length=50)
    allergies: list[ProfileListItem] = Field(default_factory=list, max_length=50)
    training_days_per_week: int = Field(default=3, ge=1, le=7)
    session_duration_minutes: int = Field(default=60, ge=10, le=300)
    training_location: TrainingLocation = "gym"
    equipment: list[ProfileListItem] = Field(default_factory=list, max_length=50)
    training_experience: TrainingExperience = "beginner"
    preferred_training_time: TrainingTime = "morning"
    region_preference: RegionPreference = "balanced"
    meal_scenario: MealScenario = "home_cooking"
    prep_time_limit_minutes: int = Field(default=30, ge=5, le=300)


class ProfileUpdate(BaseModel):
    """Partial profile update; only nullable fields may be explicitly cleared."""

    model_config = ConfigDict(extra="forbid")

    gender: Gender | None = None
    age: Annotated[int, Field(ge=10, le=100)] | None = None
    height: Annotated[float, Field(ge=100, le=250)] | None = None
    weight: Annotated[float, Field(ge=30, le=200)] | None = None
    target_weight: Annotated[float, Field(ge=30, le=200)] | None = None
    target_weeks: Annotated[int, Field(ge=1, le=104)] | None = None
    body_fat_rate: Annotated[float, Field(ge=3, le=60)] | None = None
    activity_level: ActivityLevel | None = None
    diet_preference: DietPreference | None = None
    goal_type: GoalType | None = None
    forbidden_foods: Annotated[list[ProfileListItem], Field(max_length=50)] | None = None
    injuries: Annotated[list[ProfileListItem], Field(max_length=50)] | None = None
    allergies: Annotated[list[ProfileListItem], Field(max_length=50)] | None = None
    training_days_per_week: Annotated[int, Field(ge=1, le=7)] | None = None
    session_duration_minutes: Annotated[int, Field(ge=10, le=300)] | None = None
    training_location: TrainingLocation | None = None
    equipment: Annotated[list[ProfileListItem], Field(max_length=50)] | None = None
    training_experience: TrainingExperience | None = None
    preferred_training_time: TrainingTime | None = None
    region_preference: RegionPreference | None = None
    meal_scenario: MealScenario | None = None
    prep_time_limit_minutes: Annotated[int, Field(ge=5, le=300)] | None = None

    @model_validator(mode="after")
    def reject_null_for_required_columns(self):
        nullable = {"target_weeks", "body_fat_rate"}
        invalid = sorted(
            name
            for name in self.model_fields_set
            if name not in nullable and getattr(self, name) is None
        )
        if invalid:
            raise ValueError(f"fields cannot be null: {', '.join(invalid)}")
        return self


class ProfileResponse(BaseModel):
    id: int
    gender: str
    age: int
    height: float
    weight: float
    target_weight: float
    target_weeks: Optional[int]
    body_fat_rate: Optional[float]
    activity_level: str
    diet_preference: str
    goal_type: str
    forbidden_foods: list[str]
    injuries: list[str]
    allergies: list[str]
    training_days_per_week: int
    session_duration_minutes: int
    training_location: str
    equipment: list[str]
    training_experience: str
    preferred_training_time: str
    region_preference: str
    meal_scenario: str
    prep_time_limit_minutes: int

    model_config = ConfigDict(from_attributes=True)
