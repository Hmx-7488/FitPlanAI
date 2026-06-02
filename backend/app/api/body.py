"""身材照片分析 API（Vision Model 驱动，自动回填体脂率）"""
import json
import uuid
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.user import User
from app.services.profile_service import update_profile

router = APIRouter()

UPLOAD_DIR = Path(__file__).parent.parent.parent / "data" / "uploads" / "body"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


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


@router.post("/analyze")
async def analyze_body_photo(
    user_id: int = Form(...),
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传身材照片，Vision Model 分析体脂率并自动回填档案"""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 保存图片
    ext = Path(image.filename).suffix or ".jpg"
    saved_name = f"{uuid.uuid4().hex}{ext}"
    saved_path = UPLOAD_DIR / saved_name
    content = await image.read()
    saved_path.write_bytes(content)

    # 尝试 Vision Model 分析
    result = None
    try:
        from app.services.vision_service import _get_vision_llm, _encode_image
        from langchain_core.messages import HumanMessage

        llm = _get_vision_llm(max_tokens=500)
        image_data = _encode_image(content)

        gender_cn = "男性" if user.gender == "male" else "女性"
        prompt = (
            f"这是一位{user.age}岁{gender_cn}的全身照片，身高{user.height}cm，体重{user.weight}kg。\n"
            "请分析：\n"
            "1. 估算体脂率范围（如 22-26）\n"
            "2. 体型特征（脂肪分布、肌肉基础）\n"
            "3. 训练重点建议（2-3 个）\n"
            "4. 营养建议（一句话）\n\n"
            "输出 JSON：\n"
            '{"body_fat_low":22,"body_fat_high":26,"shape_notes":"腰腹脂肪较明显",'
            '"training_focus":["核心训练","背部力量"],"nutrition":"保持中等热量缺口，优先蛋白质",'
            '"lighting":"good","pose_quality":"standard"}\n'
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
        low = parsed.get("body_fat_low", 20)
        high = parsed.get("body_fat_high", 28)
        body_fat_estimate = round((low + high) / 2, 1)

        result = {
            "body_fat_estimate": body_fat_estimate,
            "body_fat_range": f"{low}%-{high}%",
            "confidence": 0.75,
            "training_focus": parsed.get("training_focus", ["核心训练", "有氧训练"]),
            "nutrition_suggestion": parsed.get("nutrition", "保持中等热量缺口，优先蛋白质"),
            "shape_notes": parsed.get("shape_notes", ""),
            "lighting": parsed.get("lighting", "unknown"),
            "pose_quality": parsed.get("pose_quality", "unknown"),
            "is_ai": True,
        }
    except Exception:
        pass

    # 降级到 BMI 估算
    if result is None:
        result = _bmi_fallback(user)

    # 自动回填体脂率到档案
    if result["body_fat_estimate"]:
        await update_profile(db, user_id, {"body_fat_rate": result["body_fat_estimate"]})

    return {
        "analysis_id": f"body_{uuid.uuid4().hex[:8]}",
        "photo_url": f"/uploads/body/{saved_name}",
        "quality_check": {
            "is_usable": True,
            "lighting": result.get("lighting", "good"),
            "pose": result.get("pose_quality", "standard"),
        },
        "body_fat_estimate": {
            "estimated_range": result["body_fat_range"],
            "confidence": result["confidence"],
            "note": f"{'AI 视觉分析' if result['is_ai'] else 'BMI 粗略估算'}：{result['shape_notes']}。建议结合体脂秤、围度和体重趋势综合判断。",
        },
        "training_focus": result["training_focus"],
        "nutrition_suggestion": result["nutrition_suggestion"],
        "auto_filled": result["body_fat_estimate"] is not None,
        "is_ai_analysis": result["is_ai"],
    }
