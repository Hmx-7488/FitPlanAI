"""AI 动作分析 API（Vision Model 驱动，带 Mock 降级）"""
import json
import uuid
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.user import User

router = APIRouter()

UPLOAD_DIR = Path(__file__).parent.parent.parent / "data" / "uploads" / "pose"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 支持的动作列表
MOVEMENT_NAMES = {
    "squat": "深蹲",
    "deadlift": "硬拉",
    "bench_press": "卧推",
    "pull_up": "引体向上",
    "push_up": "俯卧撑",
    "lunge": "弓步蹲",
    "overhead_press": "肩推",
    "plank": "平板支撑",
}

# Mock 降级模板
MOCK_FALLBACK = {
    "squat": {"name": "深蹲", "score": 82, "issues": [
        {"type": "knee_tracking", "severity": "medium", "description": "下蹲时膝盖有轻微内扣趋势。", "suggestion": "下蹲时膝盖方向与脚尖一致，可使用弹力带辅助激活臀中肌。"},
        {"type": "depth", "severity": "low", "description": "下蹲幅度略不足，大腿未到平行地面。", "suggestion": "适当降低重心，确保髋关节低于膝关节。"},
    ], "coach_cues": ["核心收紧", "膝盖跟脚尖方向一致", "臀部向后坐", "背部保持平直"]},
    "deadlift": {"name": "硬拉", "score": 78, "issues": [
        {"type": "back_rounding", "severity": "medium", "description": "起始阶段腰椎有轻微弯曲。", "suggestion": "启动前收紧核心，肩胛后收下沉，保持脊柱中立。"},
    ], "coach_cues": ["杠铃贴身上行", "髋主导发力", "肩胛收紧", "全程脊柱中立"]},
    "bench_press": {"name": "卧推", "score": 85, "issues": [
        {"type": "shoulder_position", "severity": "low", "description": "推起时肩胛有轻微松动。", "suggestion": "全程保持肩胛后收下沉，脚踩实地面。"},
    ], "coach_cues": ["肩胛后收下沉", "双脚踩实", "杠铃下放至胸口中部", "全程控制节奏"]},
    "pull_up": {"name": "引体向上", "score": 80, "issues": [
        {"type": "range_of_motion", "severity": "medium", "description": "下放阶段手肘未完全伸展，动作幅度略不足。", "suggestion": "下放时保持控制，手臂接近伸直后再开始下一次。"},
    ], "coach_cues": ["核心收紧", "肩胛先下沉再拉", "避免身体大幅摆动"]},
    "push_up": {"name": "俯卧撑", "score": 88, "issues": [
        {"type": "hip_sag", "severity": "low", "description": "后半程有轻微塌腰趋势。", "suggestion": "收紧腹部和臀部，保持身体一条直线。"},
    ], "coach_cues": ["身体一条直线", "手肘不完全锁死", "匀速上下"]},
}
DEFAULT_MOCK = {"name": "自定义动作", "score": 75, "issues": [
    {"type": "general", "severity": "low", "description": "整体动作完成度尚可，建议注意动作节奏和呼吸配合。", "suggestion": "保持匀速，发力时呼气，还原时吸气。"},
], "coach_cues": ["核心收紧", "动作匀速", "呼吸配合"]}


def _build_risk_warnings(user, movement_key: str) -> list[str]:
    """根据用户伤病生成风险提示"""
    injuries = json.loads(user.injuries) if user.injuries else []
    warnings = []
    if not injuries:
        return warnings
    injury_text = " ".join(injuries).lower()
    if "膝盖" in injury_text or "膝" in injury_text:
        if movement_key in ("squat", "deadlift", "lunge"):
            warnings.append("⚠️ 检测到膝关节问题，建议减小动作幅度或使用护膝。")
    if "腰" in injury_text or "腰椎" in injury_text:
        if movement_key in ("deadlift", "squat"):
            warnings.append("⚠️ 检测到腰部问题，建议降低负重，保持核心收紧。")
    if "肩" in injury_text:
        if movement_key in ("bench_press", "overhead_press", "pull_up"):
            warnings.append("⚠️ 检测到肩部问题，建议减小活动范围，避免肩关节过度外展。")
    return warnings


@router.post("/analyze")
async def analyze_pose(
    user_id: int = Form(...),
    image: UploadFile = File(...),
    movement_name: str = Form("squat"),
    db: AsyncSession = Depends(get_db),
):
    """上传动作照片，Vision Model 分析动作质量"""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 保存图片
    ext = Path(image.filename).suffix or ".jpg"
    saved_name = f"{uuid.uuid4().hex}{ext}"
    saved_path = UPLOAD_DIR / saved_name
    content = await image.read()
    saved_path.write_bytes(content)

    movement_key = movement_name.lower().replace(" ", "_")
    movement_cn = MOVEMENT_NAMES.get(movement_key, movement_name)

    # 构建伤病上下文
    injuries = json.loads(user.injuries) if user.injuries else []
    injury_ctx = f"用户有以下伤病：{'、'.join(injuries)}。请特别关注这些部位的风险。" if injuries else ""

    # 尝试 Vision Model 分析
    result = None
    try:
        from app.services.vision_service import _get_vision_llm, _encode_image
        from langchain_core.messages import HumanMessage

        llm = _get_vision_llm(max_tokens=600)
        image_data = _encode_image(content)

        prompt = (
            f"这是一张训练动作照片，动作是{movement_cn}。{injury_ctx}\n"
            "请分析动作质量，输出 JSON：\n"
            '{"score":82,"movement_name":"深蹲",'
            '"issues":['
            '{"type":"knee_tracking","severity":"medium","description":"膝盖有内扣趋势","suggestion":"膝盖对齐脚尖"},'
            '{"type":"depth","severity":"low","description":"下蹲幅度不足","suggestion":"确保髋低于膝"}'
            '],'
            '"coach_cues":["核心收紧","膝盖对齐脚尖","背部平直","匀速控制"]}\n\n'
            "severity 取值：high/medium/low\n"
            "score 为 0-100 的动作评分\n"
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
        result = {
            "movement_name": parsed.get("movement_name", movement_cn),
            "score": parsed.get("score", 75),
            "issues": parsed.get("issues", []),
            "coach_cues": parsed.get("coach_cues", ["核心收紧", "动作匀速"]),
            "is_ai": True,
        }
    except Exception:
        pass

    # 降级到 Mock
    if result is None:
        template = MOCK_FALLBACK.get(movement_key, DEFAULT_MOCK)
        result = {**template, "is_ai": False}

    # 伤病风险提示
    risk_warnings = _build_risk_warnings(user, movement_key)

    return {
        "analysis_id": f"pose_{uuid.uuid4().hex[:8]}",
        "photo_url": f"/uploads/pose/{saved_name}",
        "movement_name": result["movement_name"],
        "score": result["score"],
        "issues": result["issues"],
        "coach_cues": result["coach_cues"],
        "risk_warnings": risk_warnings,
        "is_ai_analysis": result.get("is_ai", False),
    }
