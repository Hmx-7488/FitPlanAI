import json
import logging
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.schemas.profile import ProfileCreate, ProfileUpdate, ProfileResponse
from app.services.image_utils import image_extension, validate_image
from app.services.profile_service import create_profile, get_profile, update_profile

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 10 * 1024 * 1024


def _user_to_response(user) -> ProfileResponse:
    return ProfileResponse(
        id=user.id,
        gender=user.gender,
        age=user.age,
        height=user.height,
        weight=user.weight,
        target_weight=user.target_weight,
        body_fat_rate=user.body_fat_rate,
        activity_level=user.activity_level,
        diet_preference=user.diet_preference,
        goal_type=user.goal_type,
        forbidden_foods=json.loads(user.forbidden_foods),
        injuries=json.loads(user.injuries),
        allergies=json.loads(user.allergies),
        # 训练条件
        training_days_per_week=user.training_days_per_week,
        session_duration_minutes=user.session_duration_minutes,
        training_location=user.training_location,
        equipment=json.loads(user.equipment) if user.equipment else [],
        training_experience=user.training_experience,
        preferred_training_time=user.preferred_training_time,
        # 中国饮食习惯
        region_preference=user.region_preference,
        meal_scenario=user.meal_scenario,
        prep_time_limit_minutes=user.prep_time_limit_minutes,
    )


@router.post("/create", response_model=ProfileResponse)
async def create_user_profile(data: ProfileCreate, db: AsyncSession = Depends(get_db)):
    user = await create_profile(db, data)
    return _user_to_response(user)


@router.get("/{user_id}", response_model=ProfileResponse)
async def get_user_profile(user_id: int, db: AsyncSession = Depends(get_db)):
    user = await get_profile(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _user_to_response(user)


@router.patch("/{user_id}", response_model=ProfileResponse)
async def update_user_profile(
    user_id: int,
    data: ProfileUpdate,
    db: AsyncSession = Depends(get_db),
):
    """部分更新用户档案"""
    update_data = data.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="没有要更新的字段")
    user = await update_profile(db, user_id, update_data)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _user_to_response(user)


@router.post("/{user_id}/estimate-body-fat")
async def estimate_body_fat_from_photo(
    user_id: int,
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传身材照片，AI 估算体脂率并回填档案"""
    user = await get_profile(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 校验并保存图片：按真实内容判断类型，不信任文件名后缀
    content = await image.read()
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="图片不能超过 10MB")
    try:
        mime_type, _, _ = validate_image(content)
    except ValueError as exc:
        logger.warning("Invalid body photo: filename=%r error=%s", image.filename, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    upload_dir = Path(__file__).parent.parent.parent / "data" / "uploads" / "body"
    upload_dir.mkdir(parents=True, exist_ok=True)
    ext = image_extension(mime_type, image.filename)
    saved_name = f"{uuid.uuid4().hex}{ext}"
    saved_path = upload_dir / saved_name
    saved_path.write_bytes(content)

    # 调用 Vision Model 分析身材
    body_fat_estimate = None
    training_focus = []
    nutrition_suggestion = ""
    note = ""
    body_fat_range = ""
    is_fallback = False

    try:
        from app.services.vision_service import get_vision_llm, encode_image
        from langchain_core.messages import HumanMessage

        llm = get_vision_llm(max_tokens=400)
        image_data = encode_image(content, mime_type=mime_type)

        gender_cn = "男性" if user.gender == "male" else "女性"
        prompt = (
            f"这是一位{user.age}岁{gender_cn}的全身照片，身高{user.height}cm，体重{user.weight}kg。\n"
            "请分析：\n"
            "1. 估算体脂率范围（如 22-26）\n"
            "2. 体型特征（脂肪分布、肌肉基础）\n"
            "3. 训练重点建议（2-3 个）\n"
            "4. 营养建议（一句话）\n\n"
            "输出 JSON：\n"
            '{"body_fat_low":22,"body_fat_high":26,"shape_notes":"腰腹脂肪较明显","'
            'training_focus":["核心训练","背部力量"],"nutrition":"保持中等热量缺口，优先蛋白质"}\n'
            "只输出 JSON。"
        )

        message = HumanMessage(content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_data, "detail": "low"}},
        ])

        response = llm.invoke([message])
        raw = response.content.strip()

        if "```" in raw:
            json_start = raw.find("{")
            json_end = raw.rfind("}") + 1
            raw = raw[json_start:json_end]

        parsed = json.loads(raw)
        low = float(parsed.get("body_fat_low", 20))
        high = float(parsed.get("body_fat_high", 28))
        if low > high:
            low, high = high, low
        body_fat_estimate = round((low + high) / 2, 1)
        body_fat_range = f"{low:.0f}%-{high:.0f}%"
        training_focus = parsed.get("training_focus", [])
        nutrition_suggestion = parsed.get("nutrition", "")
        shape_notes = parsed.get("shape_notes", "")
        note = f"AI 估算体脂率 {body_fat_range}（{shape_notes}），仅供参考"

    except Exception:
        # 降级：基于 BMI 粗略估算。降级结果不回填档案，避免把粗估
        # 数值当成真实测量值参与后续计划计算。
        logger.exception(
            "Body-fat vision analysis failed; using BMI fallback. user_id=%s", user_id
        )
        is_fallback = True
        height_m = (user.height or 170) / 100
        bmi = user.weight / (height_m * height_m) if height_m > 0 else 22
        if bmi < 18.5:
            body_fat_estimate = 12.0
        elif bmi < 24:
            body_fat_estimate = 21.0
        elif bmi < 28:
            body_fat_estimate = 27.0
        else:
            body_fat_estimate = 32.0
        body_fat_range = f"{body_fat_estimate - 3:.0f}%-{body_fat_estimate + 3:.0f}%"
        training_focus = ["核心训练", "有氧训练", "全身力量"]
        nutrition_suggestion = "保持中等热量缺口，优先保证蛋白质摄入。"
        note = f"基于 BMI {bmi:.1f} 粗略估算，不会写入档案，建议结合体脂秤使用"

    # 仅 AI 真实分析成功时才自动回填体脂率到档案
    if body_fat_estimate and not is_fallback:
        await update_profile(db, user_id, {"body_fat_rate": body_fat_estimate})

    return {
        "photo_url": f"/uploads/body/{saved_name}",
        "body_fat_estimate": body_fat_estimate,
        "body_fat_range": body_fat_range,
        "training_focus": training_focus,
        "nutrition_suggestion": nutrition_suggestion,
        "note": note,
        "auto_filled": body_fat_estimate is not None and not is_fallback,
    }
