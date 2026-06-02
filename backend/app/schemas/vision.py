from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class IngredientItem(BaseModel):
    name: str                # 英文标识，如 chicken_breast
    display_name: str        # 中文名，如 鸡胸肉
    estimated_weight_g: float  # 估算重量(g)
    confidence: float        # 置信度 0-1
    need_confirm: bool = True  # 是否需要用户确认


class RecognizeResponse(BaseModel):
    recognition_id: int
    ingredients: list[IngredientItem]
    question_to_user: str    # 追问文案，如"请确认鸡胸肉是否约150g"


class ConfirmRequest(BaseModel):
    recognition_id: int
    confirmed_ingredients: list[IngredientItem]  # 用户确认/修改后的食材列表


class ConfirmResponse(BaseModel):
    recognition_id: int
    status: str  # "confirmed"
    confirmed_ingredients: list[IngredientItem]


class RecipeRequest(BaseModel):
    user_id: int
    recognition_id: int
    confirmed_ingredients: list[IngredientItem]


class RecipeImage(BaseModel):
    """菜谱图片信息"""
    url: str = "/uploads/recipes/default-recipe.png"  # 默认占位图
    alt: str = "菜谱成品图"
    generation_prompt: str = ""  # 图片生成提示词


class SubstituteItem(BaseModel):
    """替代食材"""
    missing: str
    alternatives: list[str]


class RecipeItem(BaseModel):
    name: str                # 菜名
    ingredients: list[str]   # 所用食材
    calories_est: int        # 估算热量
    protein_est: float       # 估算蛋白质(g)
    carbs_est: float = 0     # 估算碳水(g)
    fat_est: float = 0       # 估算脂肪(g)
    steps: str               # 做法简述
    image: RecipeImage = RecipeImage()  # 菜谱图片
    missing_ingredients: list[str] = []  # 缺少的食材
    substitute_ingredients: list[SubstituteItem] = []  # 替代食材建议
    shopping_list: list[str] = []  # 购物清单


class RecipeResponse(BaseModel):
    recipe_id: int
    user_id: int
    recognition_id: int
    recipes: list[RecipeItem]
    total_calories: int
    total_protein: float
    recipe_content: str      # 完整菜谱文本
    created_at: Optional[datetime] = None
