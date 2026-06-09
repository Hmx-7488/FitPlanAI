"""食材识别与菜谱生成 API"""

import json
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.schemas.vision import (
    ConfirmRequest, ConfirmResponse,
    RecipeImage, RecipeRequest, RecipeResponse, RecognizeResponse,
)
from app.services.vision_service import (
    recognize_ingredients, confirm_ingredients, generate_recipes,
)
from app.services.image_utils import validate_image

router = APIRouter()


@router.post("/recognize", response_model=RecognizeResponse)
async def upload_and_recognize(
    user_id: int = Form(...),
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传食材图片并识别"""
    image_bytes = await image.read()
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片大小不能超过 10MB")
    try:
        mime_type, _, _ = validate_image(image_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        result = await recognize_ingredients(
            db,
            user_id,
            image_bytes,
            image.filename or "photo.jpg",
            mime_type=mime_type,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"识别失败: {str(e)}")


@router.post("/confirm", response_model=ConfirmResponse)
async def confirm_user_ingredients(
    request: ConfirmRequest,
    db: AsyncSession = Depends(get_db),
):
    """用户确认/修改食材重量"""
    try:
        return await confirm_ingredients(db, request)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"确认失败: {str(e)}")


@router.post("/recipes", response_model=RecipeResponse)
async def generate_user_recipes(
    request: RecipeRequest,
    db: AsyncSession = Depends(get_db),
):
    """基于确认的食材生成轻食菜谱"""
    try:
        return await generate_recipes(db, request)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成菜谱失败: {str(e)}")


@router.get("/recipes/latest/{user_id}")
async def get_latest_recipe(user_id: int, db: AsyncSession = Depends(get_db)):
    """获取用户最新的菜谱（含解析后的 recipes 列表）"""
    from app.models.user import IngredientRecognition, Recipe
    from app.services.vision_service import _parse_recipes
    stmt = select(Recipe).where(Recipe.user_id == user_id).order_by(desc(Recipe.created_at)).limit(1)
    result = await db.execute(stmt)
    recipe = result.scalar_one_or_none()
    if not recipe:
        return None

    recognition = await db.get(IngredientRecognition, recipe.recognition_id)
    food_image_url = f"/uploads/{Path(recognition.image_path).name}" if recognition and recognition.image_path else ""
    nutrition = json.loads(recipe.nutrition_json) if recipe.nutrition_json else {}

    # 从 recipe_content 重新解析出结构化菜谱
    recipes_list = _parse_recipes(recipe.recipe_content, [])
    recipe_images = nutrition.get("recipe_images", [])
    for index, recipe_item in enumerate(recipes_list):
        if index < len(recipe_images):
            recipe_item.image = RecipeImage.model_validate(recipe_images[index])
    recipes_dicts = [r.model_dump() for r in recipes_list]

    return {
        "recipe_id": recipe.id,
        "user_id": recipe.user_id,
        "recognition_id": recipe.recognition_id,
        "food_image_url": food_image_url,
        "recipe_content": recipe.recipe_content,
        "recipes": recipes_dicts,
        "total_calories": nutrition.get("total_calories", 0),
        "total_protein": nutrition.get("total_protein", 0),
        "created_at": recipe.created_at.isoformat() if recipe.created_at else None,
    }
