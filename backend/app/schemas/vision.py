from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


SafeName = Annotated[str, Field(min_length=1, max_length=80)]
IngredientList = Annotated[list["IngredientItem"], Field(min_length=1, max_length=30)]


class IngredientItem(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: SafeName
    display_name: Annotated[str, Field(min_length=1, max_length=60)]
    estimated_weight_g: Annotated[float, Field(gt=0, le=5000)]
    confidence: Annotated[float, Field(ge=0, le=1)]
    need_confirm: bool = True

    @field_validator("name", "display_name")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("ingredient names cannot contain control characters")
        return value


class RecognizeResponse(BaseModel):
    recognition_id: int
    ingredients: list[IngredientItem]
    question_to_user: str


class ConfirmRequest(BaseModel):
    user_id: Annotated[int, Field(gt=0)]
    recognition_id: Annotated[int, Field(gt=0)]
    confirmed_ingredients: IngredientList


class ConfirmResponse(BaseModel):
    recognition_id: int
    status: str
    confirmed_ingredients: list[IngredientItem]


class RecipeRequest(BaseModel):
    user_id: Annotated[int, Field(gt=0)]
    recognition_id: Annotated[int, Field(gt=0)]
    confirmed_ingredients: IngredientList


class RecipeImage(BaseModel):
    url: str = "/uploads/recipes/default-recipe.png"
    alt: str = "菜谱成品图"
    generation_prompt: str = ""
    status: str = "placeholder"
    model: str = ""
    error_message: str = ""
    retry_count: int = 0
    cache_hit: bool = False


class RecipeImageJobResponse(BaseModel):
    id: int
    recipe_id: int
    recipe_index: int
    status: str
    image_url: str = ""
    model: str
    error_code: str = ""
    error_message: str = ""
    retry_count: int = 0
    cache_hit: bool = False
    updated_at: Optional[datetime] = None


class SubstituteItem(BaseModel):
    missing: Annotated[str, Field(min_length=1, max_length=100)]
    alternatives: Annotated[list[str], Field(max_length=3)]


class RecipeItem(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    ingredients: Annotated[list[str], Field(max_length=30)]
    calories_est: Annotated[int, Field(ge=0, le=5000)]
    protein_est: Annotated[float, Field(ge=0, le=1000)]
    carbs_est: Annotated[float, Field(ge=0, le=2000)] = 0
    fat_est: Annotated[float, Field(ge=0, le=1000)] = 0
    steps: Annotated[str, Field(max_length=4000)]
    image: RecipeImage = Field(default_factory=RecipeImage)
    missing_ingredients: list[str] = Field(default_factory=list, max_length=30)
    substitute_ingredients: list[SubstituteItem] = Field(default_factory=list, max_length=8)
    shopping_list: list[str] = Field(default_factory=list, max_length=30)


class RecipeResponse(BaseModel):
    recipe_id: int
    user_id: int
    recognition_id: int
    food_image_url: str = ""
    recipes: list[RecipeItem]
    total_calories: int
    total_protein: float
    recipe_content: str
    created_at: Optional[datetime] = None
