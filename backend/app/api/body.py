"""身材照片分析 API（Vision Model 驱动，自动回填体脂率）"""
import json
import logging
import uuid
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.user import User
from app.services.profile_service import update_profile
from app.services.image_utils import image_extension, validate_image

router = APIRouter()
logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(__file__).parent.parent.parent / "data" / "uploads" / "body"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_IMAGE_BYTES = 10 * 1024 * 1024

VIEW_LABELS = {
    "front": "front view",
    "side": "side view",
    "back": "back view",
}


def _bmi_fallback(user) -> dict:
    """BMI 粗略估算降级方案"""
    weight = user.weight or 70
    height_m = (user.height or 170) / 100
    bmi = weight / (height_m * height_m) if height_m > 0 else 22
    if bmi < 18.5:
        body_fat_estimate, body_fat_range = 12.0, "10%-15%"
    elif bmi < 24:
        body_fat_estimate, body_fat_range = 21.0, "18%-24%"
    elif bmi < 28:
        body_fat_estimate, body_fat_range = 27.0, "25%-30%"
    else:
        body_fat_estimate, body_fat_range = 32.0, "30%-35%"

    goal_type = user.goal_type or "fat_loss"
    if goal_type == "muscle_gain":
        training_focus = ["背部训练", "胸部训练", "腿部力量"]
        nutrition_suggestion = "保持轻度热量盈余，优先保证蛋白质摄入和训练日碳水。"
    else:
        training_focus = ["核心训练", "有氧训练", "全身力量"]
        nutrition_suggestion = "保持中等热量缺口，优先保证蛋白质摄入，控制油脂和精制糖。"

    return {
        "body_fat_estimate": body_fat_estimate,
        "body_fat_range": body_fat_range,
        "confidence": 0.55,
        "training_focus": training_focus,
        "nutrition_suggestion": nutrition_suggestion,
        "shape_notes": f"基于 BMI {bmi:.1f} 粗略估算",
        "is_ai": False,
    }


def _extract_json_object(raw: str) -> dict:
    text = raw.strip()
    if "```" in text:
        json_start = text.find("{")
        json_end = text.rfind("}") + 1
        text = text[json_start:json_end]
    else:
        json_start = text.find("{")
        json_end = text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            text = text[json_start:json_end]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Body analysis response must be a JSON object")
    return data


def _coerce_body_fat_range(low, high, user) -> tuple[float, float]:
    try:
        low = float(low)
        high = float(high)
    except (TypeError, ValueError):
        fallback = _bmi_fallback(user)
        estimate = fallback["body_fat_estimate"]
        return estimate - 3, estimate + 3

    if low > high:
        low, high = high, low
    if high - low < 3:
        mid = (low + high) / 2
        low, high = mid - 1.5, mid + 1.5
    if high - low > 12:
        mid = (low + high) / 2
        low, high = mid - 6, mid + 6

    gender_min, gender_max = (5, 45) if user.gender == "male" else (12, 52)
    low = max(gender_min, min(low, gender_max))
    high = max(gender_min, min(high, gender_max))
    if high <= low:
        high = min(gender_max, low + 3)
    return round(low, 1), round(high, 1)


def _adjust_confidence(parsed: dict, low: float, high: float) -> float:
    try:
        confidence = float(parsed.get("confidence", 0.65))
    except (TypeError, ValueError):
        confidence = 0.65
    lighting = str(parsed.get("lighting", "unknown")).lower()
    pose_quality = str(parsed.get("pose_quality", "unknown")).lower()
    usable = bool(parsed.get("is_usable", True))

    if not usable:
        confidence = min(confidence, 0.35)
    if lighting in {"poor", "bad", "dark"}:
        confidence -= 0.15
    if pose_quality in {"poor", "partial", "covered", "bad"}:
        confidence -= 0.18
    if high - low > 8:
        confidence -= 0.08
    return round(max(0.2, min(confidence, 0.9)), 2)


async def _save_body_image(upload: UploadFile, view: str, user_id: int) -> dict:
    content = await upload.read()
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Image must be smaller than 10MB")
    try:
        mime_type, width, height = validate_image(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    saved_name = f"{uuid.uuid4().hex}_{view}{image_extension(mime_type, upload.filename)}"
    saved_path = UPLOAD_DIR / saved_name
    logger.info(
        "Body photo upload received: user_id=%s view=%s filename=%r content_type=%r detected_mime=%s size_bytes=%s width=%s height=%s",
        user_id,
        view,
        upload.filename,
        upload.content_type,
        mime_type,
        len(content),
        width,
        height,
    )
    saved_path.write_bytes(content)
    return {
        "view": view,
        "filename": saved_name,
        "path": saved_path,
        "content": content,
        "mime_type": mime_type,
        "width": width,
        "height": height,
    }


@router.post("/analyze")
async def analyze_body_photo(
    user_id: int = Form(...),
    image: UploadFile | None = File(None),
    front_image: UploadFile | None = File(None),
    side_image: UploadFile | None = File(None),
    back_image: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
):
    """上传身材照片，Vision Model 分析体脂率并自动回填档案"""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    uploads: list[tuple[str, UploadFile]] = []
    if front_image:
        uploads.append(("front", front_image))
    if side_image:
        uploads.append(("side", side_image))
    if back_image:
        uploads.append(("back", back_image))
    if image and not uploads:
        uploads.append(("front", image))
    if not uploads:
        raise HTTPException(status_code=400, detail="At least one body photo is required")

    saved_images = []
    for view, upload in uploads[:3]:
        saved_images.append(await _save_body_image(upload, view, user_id))

    primary_image = saved_images[0]
    # 尝试 Vision Model 分析
    result = None
    try:
        from app.services.vision_service import _get_vision_llm, _encode_image
        from langchain_core.messages import HumanMessage

        llm = _get_vision_llm(max_tokens=900)

        gender_label = "male" if user.gender == "male" else "female"
        height_m = (user.height or 170) / 100
        bmi = (user.weight or 70) / (height_m * height_m) if height_m > 0 else 22
        uploaded_views = ", ".join(VIEW_LABELS.get(item["view"], item["view"]) for item in saved_images)
        prompt = (
            "你是一名严谨的健身体态与身体成分评估师。只能依据照片中可见信息估算体脂，不得给出医学诊断。\n"
            f"用户数据：年龄={user.age}，性别={gender_label}，身高={user.height}cm，体重={user.weight}kg，BMI={bmi:.1f}。\n"
            f"已上传视角：{uploaded_views}。必须综合使用全部照片：正面观察腰围和四肢，侧面观察腹部和体态，背面观察背部脂肪及肩臀轮廓。\n"
            "先判断每个视角的图像质量，包括全身或躯干是否完整、衣物是否宽松、光线、拍摄角度和遮挡。\n"
            "估算规则：\n"
            "1. 综合 BMI、性别、腰腹脂肪、四肢线条、肩背胸臀腿肌肉基础。\n"
            "2. 只有单视角、衣物宽松、角度不标准或光线差时，扩大估算区间并降低置信度。\n"
            "3. 正常区间至少相差3个百分点；不确定时使用6-10个百分点，多张清晰照片可适当缩小但不得过度精确。\n"
            "4. training_focus 提供2-4个具体训练重点，nutrition 提供一句可执行营养建议。\n"
            "5. 所有面向用户的文本值必须使用简体中文。\n"
            "只返回严格 JSON，不要 Markdown 或额外文字。结构：\n"
            '{"is_usable":true,"body_fat_low":18,"body_fat_high":23,"confidence":0.78,'
            '"shape_notes":"正面和侧面可见轻度腰腹脂肪，背面肩部线条中等",'
            '"visible_body_regions":["正面躯干","侧面躯干","背部"],"fat_distribution":"腰腹为主",'
            '"muscle_base":"中等","training_focus":["核心抗伸展","背部力量","下肢复合训练"],'
            '"nutrition":"保持适度热量缺口，蛋白质按目标体重每公斤1.6-2.0克摄入。",'
            '"lighting":"good","pose_quality":"standard","limitations":["照片估算存在误差，建议结合腰围和体重趋势"]}'
        )

        message_content = [{"type": "text", "text": prompt}]
        for item in saved_images:
            message_content.append({"type": "text", "text": f"{VIEW_LABELS.get(item["view"], item["view"])}:"})
            message_content.append({
                "type": "image_url",
                "image_url": {"url": _encode_image(item["content"], mime_type=item["mime_type"]), "detail": "high"},
            })
        message = HumanMessage(content=message_content)

        response = llm.invoke([message])
        raw = response.content.strip()
        logger.info("Vision Model raw body analysis response: %s", raw)

        parsed = _extract_json_object(raw)
        low, high = _coerce_body_fat_range(parsed.get("body_fat_low"), parsed.get("body_fat_high"), user)
        body_fat_estimate = round((low + high) / 2, 1)
        confidence = _adjust_confidence(parsed, low, high)

        training_focus = parsed.get("training_focus", ["core training", "cardio training"])
        if not isinstance(training_focus, list):
            training_focus = ["core training", "cardio training"]

        result = {
            "body_fat_estimate": body_fat_estimate,
            "body_fat_range": f"{low}%-{high}%",
            "confidence": confidence,
            "training_focus": [str(item) for item in training_focus[:4]],
            "nutrition_suggestion": parsed.get("nutrition", "保持适度热量缺口并优先保证蛋白质摄入。"),
            "shape_notes": parsed.get("shape_notes", ""),
            "lighting": parsed.get("lighting", "unknown"),
            "pose_quality": parsed.get("pose_quality", "unknown"),
            "is_usable": bool(parsed.get("is_usable", True)),
            "visible_body_regions": parsed.get("visible_body_regions", []),
            "limitations": parsed.get("limitations", []),
            "is_ai": True,
        }
    except Exception:
        logger.exception(
            "Vision Model body analysis failed; falling back to BMI. user_id=%s views=%s",
            user_id,
            [item["view"] for item in saved_images],
        )

    # 降级到 BMI 估算
    if result is None:
        result = _bmi_fallback(user)

    auto_fill = bool(result.get("body_fat_estimate") is not None and result.get("is_usable", True) and result.get("confidence", 0) >= 0.45)
    if auto_fill:
        await update_profile(db, user_id, {"body_fat_rate": result["body_fat_estimate"]})

    analysis_source = "AI 视觉估算" if result["is_ai"] else "BMI 降级估算"
    limitations = result.get("limitations") or []
    if isinstance(limitations, list) and limitations:
        limitation_text = " 局限：" + "；".join(str(item) for item in limitations[:3])
    else:
        limitation_text = " 建议结合体脂秤、腰围和体重趋势综合判断。"

    return {
        "analysis_id": f"body_{uuid.uuid4().hex[:8]}",
        "photo_url": f"/uploads/body/{primary_image['filename']}",
        "photo_urls": {
            item["view"]: f"/uploads/body/{item['filename']}"
            for item in saved_images
        },
        "quality_check": {
            "is_usable": result.get("is_usable", True),
            "lighting": result.get("lighting", "good"),
            "pose": result.get("pose_quality", "standard"),
            "visible_body_regions": result.get("visible_body_regions", []),
        },
        "body_fat_estimate": {
            "estimated_range": result["body_fat_range"],
            "confidence": result["confidence"],
            "note": f"{analysis_source}：{result.get('shape_notes', '')}。{limitation_text}",
        },
        "training_focus": result["training_focus"],
        "nutrition_suggestion": result["nutrition_suggestion"],
        "auto_filled": auto_fill,
        "is_ai_analysis": result["is_ai"],
    }
