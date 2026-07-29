"""餐食热量识别 API"""
import json
import logging
import uuid
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.core.database import get_db
from app.core.time import today_str
from app.models.user import User, MealLog, MealRecognition
from app.services.image_utils import (
    image_extension,
    validate_image,
)
from app.services.vision_service import get_vision_llm, recognize_food_items
from app.tools.calorie_tools import calc_bmr, calc_daily_calorie

router = APIRouter()
logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(__file__).parent.parent.parent / "data" / "uploads" / "meals"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MEAL_TYPES = ("breakfast", "lunch", "dinner", "snack")
MAX_IMAGE_BYTES = 10 * 1024 * 1024

_RECOGNITION_FAILED_DETAIL = "餐食识别失败，请换个角度重新拍摄或稍后重试"


def _detect_image_mime(image_bytes: bytes, filename: str | None, content_type: str | None) -> str:
    del filename, content_type
    from app.services.image_utils import detect_image_mime
    return detect_image_mime(image_bytes)


def _today() -> str:
    return today_str()


class IngredientItem(BaseModel):
    name: str
    display_name: str
    estimated_weight_g: float
    confidence: float = 1.0


class CalculateRequest(BaseModel):
    recognition_id: str
    ingredients: List[IngredientItem]
    meal_type: str = "lunch"


@router.post("/analyze")
async def analyze_meal(
    user_id: int = Form(...),
    meal_type: str = Form("lunch"),
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传餐食图片，识别菜品并估算热量"""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 保存图片
    if meal_type not in MEAL_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported meal_type: {meal_type}")

    content = await image.read()
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Image must be smaller than 10MB")
    try:
        mime_type, _, _ = validate_image(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    saved_name = f"{uuid.uuid4().hex}{image_extension(mime_type, image.filename)}"
    saved_path = UPLOAD_DIR / saved_name
    saved_path.write_bytes(content)

    # 调用 Vision Model 识别菜品（使用公共接口，统一 prompt）
    # 失败时明确报错：不写入伪造数据污染用户的饮食记录
    try:
        items = await recognize_food_items(content, mime_type=mime_type, mode="dish")
        if not items:
            raise ValueError("Vision Model 未识别到任何菜品")
    except Exception:
        logger.exception(
            "Vision Model dish recognition failed. user_id=%s saved_path=%s",
            user_id,
            saved_path,
        )
        saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail=_RECOGNITION_FAILED_DETAIL)

    # 计算本餐总营养
    meal_total = {
        "calories_kcal": sum(i.get("calories_kcal", 0) for i in items),
        "protein_g": sum(i.get("protein_g", 0) for i in items),
        "carbs_g": sum(i.get("carbs_g", 0) for i in items),
        "fat_g": sum(i.get("fat_g", 0) for i in items),
    }

    # 计算每日热量缺口
    today = _today()
    bmr = calc_bmr(
        gender=user.gender,
        weight=user.weight,
        height=user.height,
        age=user.age,
    )
    calorie_info = calc_daily_calorie(
        bmr=bmr,
        activity_level=user.activity_level or "medium",
        goal_type=user.goal_type or "fat_loss",
    )
    target_kcal = calorie_info["target_calories"]
    tdee = calorie_info["tdee"]

    # 查询今日已记录的餐食
    existing = await db.execute(
        select(MealLog).where(
            MealLog.user_id == user_id,
            MealLog.date == today,
            MealLog.meal_type != meal_type,
        )
    )
    today_meals = existing.scalars().all()
    consumed_kcal = sum(
        json.loads(m.meal_total_json).get("calories_kcal", 0) for m in today_meals
    )
    consumed_kcal += meal_total["calories_kcal"]

    remaining = max(target_kcal - consumed_kcal, 0)
    current_deficit = tdee - consumed_kcal

    # 状态判断
    if current_deficit > calorie_info["deficit"] * 1.3:
        status = "deficit_too_large"
        suggestion = "今天热量缺口偏大，建议适当补充高蛋白食物，避免代谢下降。"
    elif consumed_kcal > target_kcal * 1.1:
        status = "over_target"
        suggestion = "今天摄入已超过目标，晚餐可以轻食或减少碳水摄入。"
    elif remaining < 200:
        status = "near_target"
        suggestion = "今天的热量配额快用完了，晚餐建议选择低热量高蛋白食物。"
    else:
        status = "on_track"
        suggestion = f"今天还有约 {remaining} kcal 的配额，继续保持。"

    daily_summary = {
        "daily_target_kcal": target_kcal,
        "estimated_tdee_kcal": tdee,
        "consumed_kcal": consumed_kcal,
        "remaining_target_kcal": remaining,
        "current_deficit_kcal": current_deficit,
        "status": status,
        "suggestion": suggestion,
    }

    # 保存餐食记录
    await db.execute(
        delete(MealLog).where(
            MealLog.user_id == user_id,
            MealLog.date == today,
            MealLog.meal_type == meal_type,
        )
    )

    meal_log = MealLog(
        user_id=user_id,
        date=today,
        meal_type=meal_type,
        image_path=str(saved_path),
        items_json=json.dumps(items, ensure_ascii=False),
        meal_total_json=json.dumps(meal_total, ensure_ascii=False),
    )
    db.add(meal_log)
    await db.commit()

    # 构建追问
    dish_names = "、".join(i.get("dish_name", "") for i in items[:3])
    question = f"识别到：{dish_names}。份量是否准确？如有误请修改。"

    return {
        "meal_type": meal_type,
        "items": items,
        "meal_total": meal_total,
        "daily_summary": daily_summary,
        "question_to_user": question,
    }


@router.post("/recognize")
async def recognize_meal(
    user_id: int = Form(...),
    meal_type: str = Form("lunch"),
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传餐食图片，识别食材和估算重量"""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 保存图片
    if meal_type not in MEAL_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported meal_type: {meal_type}")

    content = await image.read()
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Image must be smaller than 10MB")
    try:
        mime_type, width, height = validate_image(content)
    except ValueError as exc:
        logger.warning("Invalid meal image: filename=%r error=%s", image.filename, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    saved_name = f"{uuid.uuid4().hex}{image_extension(mime_type, image.filename)}"
    saved_path = UPLOAD_DIR / saved_name
    logger.info(
        "Meal recognition upload received: user_id=%s filename=%r content_type=%r detected_mime=%s size_bytes=%s width=%s height=%s",
        user_id,
        image.filename,
        image.content_type,
        mime_type,
        len(content),
        width,
        height,
    )
    saved_path.write_bytes(content)
    logger.info("Meal recognition image saved: path=%s", saved_path)

    # 调用 Vision Model 识别食材（使用公共接口，统一 prompt）
    try:
        logger.info("Calling Vision Model for meal recognition: user_id=%s mime=%s", user_id, mime_type)
        ingredients = await recognize_food_items(content, mime_type=mime_type, mode="ingredient")
        logger.info(
            "Vision Model meal recognition parsed %s ingredients: %s",
            len(ingredients),
            ingredients,
        )

        # 验证解析结果
        if not isinstance(ingredients, list):
            raise ValueError("Vision Model 返回格式错误")

    except Exception:
        # 识别失败：明确报错并清理已保存的图片，不向用户展示伪造结果
        logger.exception(
            "Vision Model meal recognition failed. "
            "user_id=%s filename=%r saved_path=%s size_bytes=%s mime=%s width=%s height=%s",
            user_id,
            image.filename,
            saved_path,
            len(content),
            mime_type,
            width,
            height,
        )
        saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail=_RECOGNITION_FAILED_DETAIL)

    if not ingredients:
        logger.warning(
            "Vision Model returned no meal ingredients: user_id=%s saved_path=%s",
            user_id,
            saved_path,
        )
        saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail="未能识别到食物，请重新拍摄")

    # 生成识别记录并持久化（计算成功后删除）
    recognition_id = uuid.uuid4().hex
    db.add(MealRecognition(
        id=recognition_id,
        user_id=user_id,
        meal_type=meal_type,
        image_path=str(saved_path),
        ingredients_json=json.dumps(ingredients, ensure_ascii=False),
    ))
    await db.commit()

    return {
        "recognition_id": recognition_id,
        "ingredients": ingredients,
    }


@router.post("/calculate")
async def calculate_meal(
    request: CalculateRequest,
    db: AsyncSession = Depends(get_db),
):
    """根据用户确认的食材和重量计算营养"""
    # 读取持久化的识别结果；计算成功后删除，失败时保留以便直接重试
    cached = await db.get(MealRecognition, request.recognition_id)
    if not cached:
        raise HTTPException(status_code=404, detail="识别结果已过期，请重新识别")

    user_id = cached.user_id
    meal_type = request.meal_type or cached.meal_type or "lunch"
    if meal_type not in MEAL_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported meal_type: {meal_type}")
    image_path = cached.image_path
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 调用 Vision Model 计算营养
    try:
        llm = get_vision_llm(max_tokens=800)

        ingredients_text = "\n".join(
            f"- {i.display_name}: {i.estimated_weight_g}g"
            for i in request.ingredients
        )

        prompt = (
            f"根据以下食材和重量，计算总热量和三大营养元素：\n\n"
            f"{ingredients_text}\n\n"
            f"请输出 JSON 格式：\n"
            f'{{"calories_kcal": 数字, "protein_g": 数字, "carbs_g": 数字, "fat_g": 数字, '
            f'"items": [{{"dish_name": "食材名", "calories_kcal": 数字, "protein_g": 数字, "carbs_g": 数字, "fat_g": 数字, "estimated_portion_g": 数字}}]}}\n\n'
            f"要求：基于食材重量估算热量和营养元素，只输出 JSON。"
        )

        message = HumanMessage(content=[{"type": "text", "text": prompt}])
        response = llm.invoke([message])
        raw = response.content.strip()

        # 解析 JSON
        if "```" in raw:
            json_start = raw.find("{")
            json_end = raw.rfind("}") + 1
            raw = raw[json_start:json_end]
        nutrition = json.loads(raw)
    except Exception:
        # 营养计算失败：明确报错；识别记录保留在数据库中，用户可直接重试。
        # 不用拍脑袋的启发式数值冒充真实营养数据落库
        logger.exception(
            "Vision Model nutrition calculation failed. recognition_id=%s",
            request.recognition_id,
        )
        raise HTTPException(status_code=502, detail="营养计算失败，请点击重试")

    meal_total = {
        "calories_kcal": nutrition.get("calories_kcal", 0),
        "protein_g": nutrition.get("protein_g", 0),
        "carbs_g": nutrition.get("carbs_g", 0),
        "fat_g": nutrition.get("fat_g", 0),
    }
    items = nutrition.get("items", [])

    # 计算每日热量缺口
    today = _today()
    bmr = calc_bmr(
        gender=user.gender,
        weight=user.weight,
        height=user.height,
        age=user.age,
    )
    calorie_info = calc_daily_calorie(
        bmr=bmr,
        activity_level=user.activity_level or "medium",
        goal_type=user.goal_type or "fat_loss",
    )
    target_kcal = calorie_info["target_calories"]
    tdee = calorie_info["tdee"]

    # 查询今日已记录的餐食
    existing = await db.execute(
        select(MealLog).where(
            MealLog.user_id == user_id,
            MealLog.date == today,
            MealLog.meal_type != meal_type,
        )
    )
    today_meals = existing.scalars().all()
    consumed_kcal = sum(
        json.loads(m.meal_total_json).get("calories_kcal", 0) for m in today_meals
    )
    consumed_kcal += meal_total["calories_kcal"]

    remaining = max(target_kcal - consumed_kcal, 0)
    current_deficit = tdee - consumed_kcal

    # 状态判断
    if current_deficit > calorie_info["deficit"] * 1.3:
        status = "deficit_too_large"
        suggestion = "今天热量缺口偏大，建议适当补充高蛋白食物，避免代谢下降。"
    elif consumed_kcal > target_kcal * 1.1:
        status = "over_target"
        suggestion = "今天摄入已超过目标，晚餐可以轻食或减少碳水摄入。"
    elif remaining < 200:
        status = "near_target"
        suggestion = "今天的热量配额快用完了，晚餐建议选择低热量高蛋白食物。"
    else:
        status = "on_track"
        suggestion = f"今天还有约 {remaining} kcal 的配额，继续保持。"

    daily_summary = {
        "daily_target_kcal": target_kcal,
        "estimated_tdee_kcal": tdee,
        "consumed_kcal": consumed_kcal,
        "remaining_target_kcal": remaining,
        "current_deficit_kcal": current_deficit,
        "status": status,
        "suggestion": suggestion,
    }

    # 保存餐食记录
    await db.execute(
        delete(MealLog).where(
            MealLog.user_id == user_id,
            MealLog.date == today,
            MealLog.meal_type == meal_type,
        )
    )

    meal_log = MealLog(
        user_id=user_id,
        date=today,
        meal_type=meal_type,
        image_path=image_path,
        items_json=json.dumps(items, ensure_ascii=False),
        meal_total_json=json.dumps(meal_total, ensure_ascii=False),
    )
    db.add(meal_log)
    # 识别暂存记录使命完成，随本次事务一并删除
    await db.delete(cached)
    await db.commit()

    return {
        "meal_type": meal_type,
        "items": items,
        "meal_total": meal_total,
        "daily_summary": daily_summary,
    }


@router.get("/daily-summary/{user_id}")
async def get_daily_summary(
    user_id: int,
    date: str = None,
    db: AsyncSession = Depends(get_db),
):
    """Get one day's calories grouped by meal type."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not date:
        date = _today()

    existing = await db.execute(
        select(MealLog).where(MealLog.user_id == user_id, MealLog.date == date)
    )
    today_meals = existing.scalars().all()

    grouped = {meal_type: None for meal_type in MEAL_TYPES}
    for meal in today_meals:
        meal_total = json.loads(meal.meal_total_json) if meal.meal_total_json else {}
        items = json.loads(meal.items_json) if meal.items_json else []
        image_url = f"/uploads/meals/{Path(meal.image_path).name}" if meal.image_path else ""
        grouped[meal.meal_type] = {
            "id": meal.id,
            "meal_type": meal.meal_type,
            "image_url": image_url,
            "items": items,
            "meal_total": meal_total,
            "created_at": meal.created_at.isoformat() if meal.created_at else None,
        }

    consumed_kcal = sum(
        (meal["meal_total"].get("calories_kcal", 0) if meal else 0)
        for meal in grouped.values()
    )
    consumed_protein = sum(
        (meal["meal_total"].get("protein_g", 0) if meal else 0)
        for meal in grouped.values()
    )
    consumed_carbs = sum(
        (meal["meal_total"].get("carbs_g", 0) if meal else 0)
        for meal in grouped.values()
    )
    consumed_fat = sum(
        (meal["meal_total"].get("fat_g", 0) if meal else 0)
        for meal in grouped.values()
    )

    bmr = calc_bmr(
        gender=user.gender,
        weight=user.weight,
        height=user.height,
        age=user.age,
    )
    calorie_info = calc_daily_calorie(
        bmr=bmr,
        activity_level=user.activity_level or "medium",
        goal_type=user.goal_type or "fat_loss",
    )
    target_kcal = calorie_info["target_calories"]
    tdee = calorie_info["tdee"]
    remaining = max(target_kcal - consumed_kcal, 0)
    current_deficit = tdee - consumed_kcal
    progress_pct = round(consumed_kcal / target_kcal * 100, 1) if target_kcal > 0 else 0

    if consumed_kcal > target_kcal * 1.1:
        status = "over_target"
        suggestion = "今日摄入已超过目标，下一餐优先选择少油、高蛋白、低碳水食物。"
    elif remaining < 200:
        status = "near_target"
        suggestion = "今日热量已接近目标，后续餐食建议保持清淡。"
    else:
        status = "on_track"
        suggestion = f"今日还可摄入约 {remaining} kcal，继续按计划安排。"

    return {
        "date": date,
        "meal_count": sum(1 for meal in grouped.values() if meal),
        "daily_target_kcal": target_kcal,
        "estimated_tdee_kcal": tdee,
        "consumed_kcal": consumed_kcal,
        "remaining_target_kcal": remaining,
        "current_deficit_kcal": current_deficit,
        "progress_pct": progress_pct,
        "status": status,
        "suggestion": suggestion,
        "meals": grouped,
        "consumed": {
            "calories_kcal": consumed_kcal,
            "protein_g": consumed_protein,
            "carbs_g": consumed_carbs,
            "fat_g": consumed_fat,
        },
        "target_kcal": target_kcal,
        "tdee_kcal": tdee,
    }
