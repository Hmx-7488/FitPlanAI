"""餐食热量识别 API"""
import json
import uuid
from pathlib import Path
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.user import User, MealLog
from app.tools.calorie_tools import calc_bmr, calc_daily_calorie

router = APIRouter()

UPLOAD_DIR = Path(__file__).parent.parent.parent / "data" / "uploads" / "meals"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 临时存储识别结果（生产环境应使用 Redis 或数据库）
recognition_cache = {}


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
    ext = Path(image.filename).suffix or ".jpg"
    saved_name = f"{uuid.uuid4().hex}{ext}"
    saved_path = UPLOAD_DIR / saved_name
    content = await image.read()
    saved_path.write_bytes(content)

    # 调用 Vision Model 识别菜品
    try:
        from app.services.vision_service import _get_vision_llm, _encode_image
        from langchain_core.messages import HumanMessage

        llm = _get_vision_llm(max_tokens=600)
        image_data = _encode_image(content)

        prompt = (
            "请识别图片中的食物/菜品。对于每个菜品，输出 JSON 数组：\n"
            '[{"dish_name":"番茄炒蛋","estimated_portion_g":220,'
            '"calories_kcal":260,"protein_g":14,"carbs_g":12,"fat_g":18,"confidence":0.82}]\n\n'
            "要求：estimated_portion_g 为估算份量克数，calories_kcal 为估算热量，"
            "protein_g/carbs_g/fat_g 为蛋白质/碳水/脂肪克数，confidence 为置信度 0-1。"
            "只输出 JSON 数组。"
        )

        message = HumanMessage(content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_data, "detail": "low"}},
        ])

        response = llm.invoke([message])
        raw = response.content.strip()

        # 解析 JSON
        if "```" in raw:
            json_start = raw.find("[")
            json_end = raw.rfind("]") + 1
            raw = raw[json_start:json_end]
        items = json.loads(raw)
    except Exception:
        # 降级到 mock
        items = [
            {
                "dish_name": "家常菜",
                "estimated_portion_g": 200,
                "calories_kcal": 350,
                "protein_g": 20,
                "carbs_g": 30,
                "fat_g": 15,
                "confidence": 0.5,
            }
        ]

    # 计算本餐总营养
    meal_total = {
        "calories_kcal": sum(i.get("calories_kcal", 0) for i in items),
        "protein_g": sum(i.get("protein_g", 0) for i in items),
        "carbs_g": sum(i.get("carbs_g", 0) for i in items),
        "fat_g": sum(i.get("fat_g", 0) for i in items),
    }

    # 计算每日热量缺口
    today = datetime.utcnow().strftime("%Y-%m-%d")
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
        select(MealLog).where(MealLog.user_id == user_id, MealLog.date == today)
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
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传餐食图片，识别食材和估算重量"""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 保存图片
    ext = Path(image.filename).suffix or ".jpg"
    saved_name = f"{uuid.uuid4().hex}{ext}"
    saved_path = UPLOAD_DIR / saved_name
    content = await image.read()
    saved_path.write_bytes(content)

    # 调用 Vision Model 识别食材
    try:
        from app.services.vision_service import _get_vision_llm, _encode_image
        from langchain_core.messages import HumanMessage

        llm = _get_vision_llm(max_tokens=600)
        image_data = _encode_image(content)

        prompt = (
            "请识别图片中的食物/食材。对于每个食材，输出 JSON 数组：\n"
            '[{"name":"egg","display_name":"鸡蛋","estimated_weight_g":100,"confidence":0.9},'
            '{"name":"tomato","display_name":"番茄","estimated_weight_g":150,"confidence":0.85}]\n\n'
            "要求：\n"
            "- name: 食材英文名（小写）\n"
            "- display_name: 食材中文名\n"
            "- estimated_weight_g: 估算重量（克）\n"
            "- confidence: 置信度 0-1\n"
            "只输出 JSON 数组，不要其他文字。"
        )

        message = HumanMessage(content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_data, "detail": "low"}},
        ])

        response = llm.invoke([message])
        raw = response.content.strip()

        # 解析 JSON
        if "```" in raw:
            json_start = raw.find("[")
            json_end = raw.rfind("]") + 1
            raw = raw[json_start:json_end]
        ingredients = json.loads(raw)
    except Exception:
        # 降级到 mock
        ingredients = [
            {
                "name": "unknown",
                "display_name": "家常菜",
                "estimated_weight_g": 200,
                "confidence": 0.5,
            }
        ]

    # 生成识别 ID 并缓存结果
    recognition_id = uuid.uuid4().hex
    recognition_cache[recognition_id] = {
        "user_id": user_id,
        "image_path": str(saved_path),
        "ingredients": ingredients,
        "created_at": datetime.utcnow().isoformat(),
    }

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
    # 获取缓存的识别结果
    cached = recognition_cache.get(request.recognition_id)
    if not cached:
        raise HTTPException(status_code=404, detail="识别结果已过期，请重新识别")

    user_id = cached["user_id"]
    image_path = cached["image_path"]
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 调用 Vision Model 计算营养
    try:
        from app.services.vision_service import _get_vision_llm
        from langchain_core.messages import HumanMessage

        llm = _get_vision_llm(max_tokens=800)

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
        # 降级：简单估算
        total_weight = sum(i.estimated_weight_g for i in request.ingredients)
        nutrition = {
            "calories_kcal": int(total_weight * 1.5),
            "protein_g": round(total_weight * 0.15, 1),
            "carbs_g": round(total_weight * 0.2, 1),
            "fat_g": round(total_weight * 0.08, 1),
            "items": [
                {
                    "dish_name": i.display_name,
                    "calories_kcal": int(i.estimated_weight_g * 1.5),
                    "protein_g": round(i.estimated_weight_g * 0.15, 1),
                    "carbs_g": round(i.estimated_weight_g * 0.2, 1),
                    "fat_g": round(i.estimated_weight_g * 0.08, 1),
                    "estimated_portion_g": i.estimated_weight_g,
                }
                for i in request.ingredients
            ],
        }

    meal_total = {
        "calories_kcal": nutrition.get("calories_kcal", 0),
        "protein_g": nutrition.get("protein_g", 0),
        "carbs_g": nutrition.get("carbs_g", 0),
        "fat_g": nutrition.get("fat_g", 0),
    }
    items = nutrition.get("items", [])

    # 计算每日热量缺口
    today = datetime.utcnow().strftime("%Y-%m-%d")
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
        select(MealLog).where(MealLog.user_id == user_id, MealLog.date == today)
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
    meal_log = MealLog(
        user_id=user_id,
        date=today,
        meal_type=request.meal_type,
        image_path=image_path,
        items_json=json.dumps(items, ensure_ascii=False),
        meal_total_json=json.dumps(meal_total, ensure_ascii=False),
    )
    db.add(meal_log)
    await db.commit()

    # 清理缓存
    del recognition_cache[request.recognition_id]

    return {
        "meal_type": request.meal_type,
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
    """获取某日的热量汇总"""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if not date:
        date = datetime.utcnow().strftime("%Y-%m-%d")

    existing = await db.execute(
        select(MealLog).where(MealLog.user_id == user_id, MealLog.date == date)
    )
    today_meals = existing.scalars().all()

    consumed_kcal = sum(
        json.loads(m.meal_total_json).get("calories_kcal", 0) for m in today_meals
    )
    consumed_protein = sum(
        json.loads(m.meal_total_json).get("protein_g", 0) for m in today_meals
    )
    consumed_carbs = sum(
        json.loads(m.meal_total_json).get("carbs_g", 0) for m in today_meals
    )
    consumed_fat = sum(
        json.loads(m.meal_total_json).get("fat_g", 0) for m in today_meals
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

    return {
        "date": date,
        "meal_count": len(today_meals),
        "consumed": {
            "calories_kcal": consumed_kcal,
            "protein_g": consumed_protein,
            "carbs_g": consumed_carbs,
            "fat_g": consumed_fat,
        },
        "target_kcal": target_kcal,
        "tdee_kcal": tdee,
        "remaining_target_kcal": max(target_kcal - consumed_kcal, 0),
        "current_deficit_kcal": tdee - consumed_kcal,
    }
