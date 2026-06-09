"""AI 动作分析 API（Vision Model 驱动，带 Mock 降级）"""
import json
import logging
import uuid
from pathlib import Path
from typing import List
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.user import User
from app.services.image_utils import image_extension, validate_image

router = APIRouter()
logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(__file__).parent.parent.parent / "data" / "uploads" / "pose"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

VIDEO_MIME_TYPES = {"video/mp4", "video/webm", "video/quicktime", "video/x-msvideo"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024

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
        raise ValueError("Pose analysis response must be a JSON object")
    return data


def _normalize_pose_result(parsed: dict, movement_cn: str, is_video: bool) -> dict:
    score = parsed.get("score", 75)
    try:
        score = int(round(float(score)))
    except (TypeError, ValueError):
        score = 75
    score = max(0, min(score, 100))

    issues = parsed.get("issues", [])
    if not isinstance(issues, list):
        issues = []
    normalized_issues = []
    for item in issues[:6]:
        if not isinstance(item, dict):
            continue
        severity = item.get("severity", "low")
        if severity not in {"high", "medium", "low"}:
            severity = "low"
        normalized_issues.append({
            "type": str(item.get("type", "general")),
            "severity": severity,
            "description": str(item.get("description", ""))[:160],
            "suggestion": str(item.get("suggestion", ""))[:180],
        })

    coach_cues = parsed.get("coach_cues", ["核心收紧", "动作匀速"])
    if not isinstance(coach_cues, list):
        coach_cues = ["核心收紧", "动作匀速"]

    phases = parsed.get("phases", [])
    if not isinstance(phases, list):
        phases = []
    normalized_phases = []
    for phase in phases[:6]:
        if not isinstance(phase, dict):
            continue
        normalized_phases.append({
            "phase": str(phase.get("phase", ""))[:40],
            "observation": str(phase.get("observation", ""))[:180],
        })

    return {
        "movement_name": parsed.get("movement_name", movement_cn),
        "score": score,
        "issues": normalized_issues,
        "coach_cues": [str(cue) for cue in coach_cues[:6]],
        "phases": normalized_phases,
        "rep_count_estimate": parsed.get("rep_count_estimate") if is_video else None,
        "is_ai": True,
    }


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


async def _analyze_pose_frames(
    image_payloads: list[tuple[bytes, str]],
    user,
    movement_key: str,
    movement_cn: str,
    is_video: bool,
) -> dict | None:
    injuries = json.loads(user.injuries) if user.injuries else []
    injury_ctx = f"用户伤病史：{'、'.join(injuries)}。请把相关关节风险纳入建议。" if injuries else "用户未填写明确伤病史。"
    media_desc = "按时间顺序排列的训练动作视频关键帧" if is_video else "训练动作照片"
    output_example = (
        '{"score":82,"movement_name":"深蹲","rep_count_estimate":1,'
        '"phases":[{"phase":"起始","observation":"站距与脚尖方向基本稳定"}],'
        '"issues":[{"type":"knee_tracking","severity":"medium","description":"下蹲阶段膝盖略向内扣","suggestion":"下蹲时主动让膝盖跟随第二脚趾方向"}],'
        '"coach_cues":["核心收紧","膝盖跟脚尖","控制离心","保持脊柱中立"]}'
    )
    prompt = (
        f"你是力量训练动作评估教练。下面是{media_desc}，动作类型：{movement_cn}。{injury_ctx}\n"
        "请只基于可见画面分析，不要编造看不到的角度；如果画面不完整，要降低置信并说明。\n"
        "评估维度：关节轨迹、躯干/脊柱稳定、动作幅度、节奏控制、左右对称、潜在伤病风险。\n"
        "输出严格 JSON，不要 markdown，不要额外文字。字段：\n"
        "- score: 0-100 整数，70以下表示有明显技术风险\n"
        "- movement_name: 中文动作名\n"
        "- rep_count_estimate: 视频中可见的重复次数，单张照片填 null\n"
        "- phases: 数组，按起始/下降或离心/底部/上升或向心/结束给出观察\n"
        "- issues: 数组，每项含 type, severity(high|medium|low), description, suggestion\n"
        "- coach_cues: 3-6条短口令\n"
        f"示例：{output_example}"
    )

    try:
        from app.services.vision_service import _get_vision_llm, _encode_image
        from langchain_core.messages import HumanMessage

        content = [{"type": "text", "text": prompt}]
        for frame_bytes, mime_type in image_payloads[:6]:
            content.append({
                "type": "image_url",
                "image_url": {"url": _encode_image(frame_bytes, mime_type=mime_type), "detail": "low"},
            })

        llm = _get_vision_llm(max_tokens=900)
        response = llm.invoke([HumanMessage(content=content)])
        raw = response.content.strip()
        logger.info("Vision Model raw pose %s response: %s", "video" if is_video else "image", raw)
        parsed = _extract_json_object(raw)
        return _normalize_pose_result(parsed, movement_cn, is_video)
    except Exception:
        logger.exception("Vision Model pose analysis failed; falling back to template. movement=%s video=%s", movement_key, is_video)
        return None


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

    movement_key = movement_name.lower().replace(" ", "_")
    movement_cn = MOVEMENT_NAMES.get(movement_key, movement_name)

    result = await _analyze_pose_frames([(content, mime_type)], user, movement_key, movement_cn, is_video=False)

    # 降级到 Mock
    if result is None:
        template = MOCK_FALLBACK.get(movement_key, DEFAULT_MOCK)
        result = {**template, "phases": [], "rep_count_estimate": None, "is_ai": False}

    # 伤病风险提示
    risk_warnings = _build_risk_warnings(user, movement_key)

    return {
        "analysis_id": f"pose_{uuid.uuid4().hex[:8]}",
        "photo_url": f"/uploads/pose/{saved_name}",
        "movement_name": result["movement_name"],
        "score": result["score"],
        "issues": result["issues"],
        "coach_cues": result["coach_cues"],
        "phases": result.get("phases", []),
        "rep_count_estimate": result.get("rep_count_estimate"),
        "risk_warnings": risk_warnings,
        "is_ai_analysis": result.get("is_ai", False),
        "media_type": "image",
    }


@router.post("/analyze-video")
async def analyze_pose_video(
    user_id: int = Form(...),
    video: UploadFile = File(...),
    frames: List[UploadFile] = File(...),
    movement_name: str = Form("squat"),
    db: AsyncSession = Depends(get_db),
):
    """上传动作视频和前端抽帧，Vision Model 按时间序列分析动作质量"""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    video_content = await video.read()
    if len(video_content) > 80 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Video must be smaller than 80MB")
    if video.content_type and video.content_type not in VIDEO_MIME_TYPES and not video.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail=f"Unsupported video type: {video.content_type}")

    video_ext = Path(video.filename or "").suffix or ".mp4"
    video_name = f"{uuid.uuid4().hex}{video_ext}"
    video_path = UPLOAD_DIR / video_name
    video_path.write_bytes(video_content)

    frame_payloads: list[tuple[bytes, str]] = []
    frame_urls = []
    for index, frame in enumerate(frames[:6]):
        frame_bytes = await frame.read()
        if len(frame_bytes) > MAX_IMAGE_BYTES:
            logger.warning("Skipping oversized video frame: filename=%r", frame.filename)
            continue
        try:
            mime_type, _, _ = validate_image(frame_bytes)
        except ValueError as exc:
            logger.warning("Skipping invalid video frame: filename=%r error=%s", frame.filename, exc)
            continue
        frame_name = f"{Path(video_name).stem}_frame_{index}{image_extension(mime_type, frame.filename)}"
        (UPLOAD_DIR / frame_name).write_bytes(frame_bytes)
        frame_urls.append(f"/uploads/pose/{frame_name}")
        frame_payloads.append((frame_bytes, mime_type))

    if len(frame_payloads) < 2:
        raise HTTPException(status_code=400, detail="At least 2 valid video frames are required")

    movement_key = movement_name.lower().replace(" ", "_")
    movement_cn = MOVEMENT_NAMES.get(movement_key, movement_name)
    result = await _analyze_pose_frames(frame_payloads, user, movement_key, movement_cn, is_video=True)

    if result is None:
        template = MOCK_FALLBACK.get(movement_key, DEFAULT_MOCK)
        result = {**template, "phases": [], "rep_count_estimate": None, "is_ai": False}

    risk_warnings = _build_risk_warnings(user, movement_key)

    return {
        "analysis_id": f"pose_{uuid.uuid4().hex[:8]}",
        "video_url": f"/uploads/pose/{video_name}",
        "frame_urls": frame_urls,
        "movement_name": result["movement_name"],
        "score": result["score"],
        "issues": result["issues"],
        "coach_cues": result["coach_cues"],
        "phases": result.get("phases", []),
        "rep_count_estimate": result.get("rep_count_estimate"),
        "risk_warnings": risk_warnings,
        "is_ai_analysis": result.get("is_ai", False),
        "media_type": "video",
    }
