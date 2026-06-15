"""食材识别与菜谱生成 API"""

import json
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.schemas.vision import (
    ConfirmRequest, ConfirmResponse,
    RecipeImageJobResponse, RecipeRequest, RecipeResponse, RecognizeResponse,
)
from app.models.user import IngredientRecognition, Recipe
from app.services.recipe_image_service import (
    apply_job_to_recipe_image,
    get_recipe_image_jobs,
    import_legacy_recipe_image_jobs,
    process_recipe_image_job,
    process_recipe_image_jobs,
    queue_recipe_image_retry,
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
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """基于确认的食材生成轻食菜谱"""
    try:
        response = await generate_recipes(db, request)
        background_tasks.add_task(process_recipe_image_jobs, response.recipe_id)
        return response
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成菜谱失败: {str(e)}")


@router.get("/recipes/latest/{user_id}")
async def get_latest_recipe(user_id: int, db: AsyncSession = Depends(get_db)):
    """获取用户最新的菜谱（含解析后的 recipes 列表）"""
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
    image_jobs = await import_legacy_recipe_image_jobs(
        db,
        recipe.id,
        recipes_list,
        recipe_images,
    )
    jobs_by_index = {job.recipe_index: job for job in image_jobs}
    for index, recipe_item in enumerate(recipes_list):
        if index in jobs_by_index:
            apply_job_to_recipe_image(recipe_item.image, jobs_by_index[index])
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


def _job_response(job) -> RecipeImageJobResponse:
    return RecipeImageJobResponse(
        id=job.id,
        recipe_id=job.recipe_id,
        recipe_index=job.recipe_index,
        status=job.status,
        image_url=job.image_url,
        model=job.model,
        error_code=job.error_code,
        error_message=job.error_message,
        retry_count=job.retry_count,
        cache_hit=bool(job.cache_hit),
        updated_at=job.updated_at,
    )


@router.get(
    "/recipes/{recipe_id}/images",
    response_model=list[RecipeImageJobResponse],
)
async def get_recipe_images(
    recipe_id: int,
    user_id: int = Query(gt=0),
    db: AsyncSession = Depends(get_db),
):
    recipe = await db.get(Recipe, recipe_id)
    if recipe is None or recipe.user_id != user_id:
        raise HTTPException(status_code=404, detail="菜谱不存在")
    return [_job_response(job) for job in await get_recipe_image_jobs(db, recipe_id)]


@router.post(
    "/recipes/{recipe_id}/images/{recipe_index}/retry",
    response_model=RecipeImageJobResponse,
)
async def retry_recipe_image(
    recipe_id: int,
    recipe_index: int,
    background_tasks: BackgroundTasks,
    user_id: int = Query(gt=0),
    db: AsyncSession = Depends(get_db),
):
    recipe = await db.get(Recipe, recipe_id)
    if recipe is None or recipe.user_id != user_id:
        raise HTTPException(status_code=404, detail="菜谱不存在")
    job = await queue_recipe_image_retry(db, recipe_id, recipe_index)
    if job is None:
        raise HTTPException(status_code=404, detail="图片任务不存在")
    if job.status == "queued":
        background_tasks.add_task(process_recipe_image_job, job.id)
    return _job_response(job)
