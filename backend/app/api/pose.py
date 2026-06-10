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

# Mock 降级模板（匹配新结构）
MOCK_FALLBACK = {
    "squat": {"movement_name": "深蹲", "overall_score": 82, "risk_level": "low", "confidence": 0.6,
              "summary": "深蹲整体技术良好，膝盖追踪和下蹲深度可进一步优化。",
              "metrics": [
                  {"name": "关节轨迹", "score": 70, "description": "膝盖有轻微内扣趋势"},
                  {"name": "躯干稳定", "score": 85, "description": "脊柱保持中立"},
                  {"name": "动作幅度", "score": 75, "description": "下蹲深度略不足"},
                  {"name": "节奏控制", "score": 80, "description": "下降上升速度均匀"},
              ],
              "issues": [
                  {"title": "膝盖内扣", "severity": "medium", "description": "下蹲时膝盖有轻微内扣趋势。", "timestamp": None, "impact": "长期增加膝关节压力", "correction": "下蹲时膝盖方向与脚尖一致，可使用弹力带辅助激活臀中肌。"},
                  {"title": "下蹲深度不足", "severity": "low", "description": "下蹲幅度略不足，大腿未到平行地面。", "timestamp": None, "impact": "肌肉激活范围受限", "correction": "适当降低重心，确保髋关节低于膝关节。"},
              ],
              "corrections": [{"area": "膝盖追踪", "technique": "下蹲时膝盖对准第二脚趾方向", "drills": ["弹力带深蹲", "箱式深蹲"], "sets_reps": "3组x12次", "next_filming_tip": "侧面拍摄，关注膝盖轨迹"}],
              "good_points": ["背部保持平直", "核心稳定"],
              "coach_cues": ["核心收紧", "膝盖跟脚尖方向一致", "臀部向后坐", "背部保持平直"]},
    "deadlift": {"movement_name": "硬拉", "overall_score": 78, "risk_level": "medium", "confidence": 0.6,
                 "summary": "硬拉起始阶段腰椎有轻微弯曲，需要加强核心收紧。",
                 "metrics": [{"name": "脊柱中立", "score": 65, "description": "起始阶段腰椎有轻微弯曲"}, {"name": "髋主导", "score": 80, "description": "发力模式基本正确"}],
                 "issues": [{"title": "腰椎弯曲", "severity": "medium", "description": "起始阶段腰椎有轻微弯曲。", "timestamp": None, "impact": "腰椎间盘压力增大", "correction": "启动前收紧核心，肩胛后收下沉，保持脊柱中立。"}],
                 "corrections": [{"area": "脊柱中立", "technique": "启动前先绷紧核心，想象胸口向上提", "drills": ["罗马尼亚硬拉", "反向划船"], "sets_reps": "3组x10次", "next_filming_tip": "侧面拍摄，关注腰椎曲线"}],
                 "good_points": ["杠铃路径贴身", "髋主导发力"],
                 "coach_cues": ["杠铃贴身上行", "髋主导发力", "肩胛收紧", "全程脊柱中立"]},
    "bench_press": {"movement_name": "卧推", "overall_score": 85, "risk_level": "low", "confidence": 0.6,
                    "summary": "卧推整体技术较好，肩胛稳定性可进一步优化。",
                    "metrics": [{"name": "肩胛稳定", "score": 75, "description": "推起时肩胛有轻微松动"}, {"name": "杠铃路径", "score": 85, "description": "杠铃轨迹基本合理"}],
                    "issues": [{"title": "肩胛松动", "severity": "low", "description": "推起时肩胛有轻微松动。", "timestamp": None, "impact": "肩关节稳定性下降", "correction": "全程保持肩胛后收下沉，脚踩实地面。"}],
                    "corrections": [{"area": "肩胛控制", "technique": "全程保持肩胛后收下沉", "drills": ["地板卧推", "暂停卧推"], "sets_reps": "3组x8次", "next_filming_tip": "侧面拍摄，关注肩胛位置"}],
                    "good_points": ["双脚踩实", "杠铃下放位置合理"],
                    "coach_cues": ["肩胛后收下沉", "双脚踩实", "杠铃下放至胸口中部", "全程控制节奏"]},
    "pull_up": {"movement_name": "引体向上", "overall_score": 80, "risk_level": "low", "confidence": 0.6,
                "summary": "引体向上动作幅度略不足，下放阶段手肘未完全伸展。",
                "metrics": [{"name": "动作幅度", "score": 70, "description": "下放阶段手肘未完全伸展"}, {"name": "身体控制", "score": 85, "description": "摆动幅度较小"}],
                "issues": [{"title": "幅度不足", "severity": "medium", "description": "下放阶段手肘未完全伸展，动作幅度略不足。", "timestamp": None, "impact": "背阔肌激活不充分", "correction": "下放时保持控制，手臂接近伸直后再开始下一次。"}],
                "corrections": [{"area": "动作幅度", "technique": "下放时手臂完全伸展再发力", "drills": ["离心引体", "弹力带辅助引体"], "sets_reps": "3组x6次", "next_filming_tip": "侧面拍摄，关注手臂伸展"}],
                "good_points": ["核心收紧", "肩胛先下沉再拉"],
                "coach_cues": ["核心收紧", "肩胛先下沉再拉", "避免身体大幅摆动"]},
    "push_up": {"movement_name": "俯卧撑", "overall_score": 88, "risk_level": "low", "confidence": 0.6,
                "summary": "俯卧撑整体技术良好，后半程有轻微塌腰趋势。",
                "metrics": [{"name": "躯干稳定", "score": 80, "description": "后半程有轻微塌腰趋势"}, {"name": "动作节奏", "score": 90, "description": "上下速度均匀"}],
                "issues": [{"title": "轻微塌腰", "severity": "low", "description": "后半程有轻微塌腰趋势。", "timestamp": None, "impact": "腰椎代偿", "correction": "收紧腹部和臀部，保持身体一条直线。"}],
                "corrections": [{"area": "核心控制", "technique": "全程收紧腹部和臀部", "drills": ["平板支撑", "死虫式"], "sets_reps": "3组x30秒", "next_filming_tip": "侧面拍摄，关注腰椎位置"}],
                "good_points": ["身体一条直线", "手肘不完全锁死"],
                "coach_cues": ["身体一条直线", "手肘不完全锁死", "匀速上下"]},
}
DEFAULT_MOCK = {"movement_name": "自定义动作", "overall_score": 75, "risk_level": "low", "confidence": 0.5,
                "summary": "整体动作完成度尚可，建议注意动作节奏和呼吸配合。",
                "metrics": [],
                "issues": [{"title": "整体评估", "severity": "low", "description": "整体动作完成度尚可，建议注意动作节奏和呼吸配合。", "timestamp": None, "impact": "动作效率", "correction": "保持匀速，发力时呼气，还原时吸气。"}],
                "corrections": [], "good_points": [],
                "coach_cues": ["核心收紧", "动作匀速", "呼吸配合"]}


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


def _clamp_int(value, lo: int = 0, hi: int = 100, default: int = 75) -> int:
    try:
        return max(lo, min(hi, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def _normalize_pose_result(parsed: dict, movement_cn: str, is_video: bool) -> dict:
    overall_score = _clamp_int(parsed.get("overall_score", parsed.get("score", 75)))

    risk_level = parsed.get("risk_level", "low")
    if risk_level not in {"high", "medium", "low"}:
        risk_level = "low"

    summary = str(parsed.get("summary", ""))[:300]
    confidence = parsed.get("confidence")
    if confidence is not None:
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            confidence = None

    # metrics
    metrics = parsed.get("metrics", [])
    if not isinstance(metrics, list):
        metrics = []
    normalized_metrics = []
    for m in metrics[:8]:
        if not isinstance(m, dict):
            continue
        normalized_metrics.append({
            "name": str(m.get("name", ""))[:40],
            "score": _clamp_int(m.get("score", 0)),
            "description": str(m.get("description", ""))[:160],
        })

    # issues（增强结构）
    issues = parsed.get("issues", [])
    if not isinstance(issues, list):
        issues = []
    normalized_issues = []
    for item in issues[:8]:
        if not isinstance(item, dict):
            continue
        severity = item.get("severity", "low")
        if severity not in {"high", "medium", "low"}:
            severity = "low"
        timestamp = item.get("timestamp")
        if timestamp is not None:
            try:
                timestamp = round(float(timestamp), 1)
            except (TypeError, ValueError):
                timestamp = None
        normalized_issues.append({
            "title": str(item.get("title", item.get("type", "问题")))[:60],
            "severity": severity,
            "description": str(item.get("description", ""))[:200],
            "timestamp": timestamp,
            "impact": str(item.get("impact", ""))[:160],
            "correction": str(item.get("correction", item.get("suggestion", "")))[:200],
        })

    # corrections
    corrections = parsed.get("corrections", [])
    if not isinstance(corrections, list):
        corrections = []
    normalized_corrections = []
    for c in corrections[:6]:
        if not isinstance(c, dict):
            continue
        drills = c.get("drills", [])
        if not isinstance(drills, list):
            drills = []
        normalized_corrections.append({
            "area": str(c.get("area", ""))[:40],
            "technique": str(c.get("technique", ""))[:200],
            "drills": [str(d)[:60] for d in drills[:4] if d],
            "sets_reps": str(c.get("sets_reps", ""))[:60],
            "next_filming_tip": str(c.get("next_filming_tip", ""))[:120],
        })

    # good_points
    good_points = parsed.get("good_points", [])
    if not isinstance(good_points, list):
        good_points = []
    good_points = [str(g)[:100] for g in good_points[:6] if g]

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
        "overall_score": overall_score,
        "score": overall_score,
        "risk_level": risk_level,
        "summary": summary,
        "confidence": confidence,
        "metrics": normalized_metrics,
        "issues": normalized_issues,
        "corrections": normalized_corrections,
        "good_points": good_points,
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
        '{"overall_score":82,"movement_name":"深蹲","risk_level":"medium","confidence":0.8,'
        '"summary":"深蹲整体技术中等，膝盖内扣是主要风险点。",'
        '"rep_count_estimate":1,'
        '"metrics":[{"name":"关节轨迹","score":70,"description":"膝盖有轻微内扣"},'
        '{"name":"躯干稳定","score":85,"description":"脊柱保持中立"},'
        '{"name":"动作幅度","score":75,"description":"下蹲深度略不足"},'
        '{"name":"节奏控制","score":80,"description":"下降和上升速度均匀"}],'
        '"issues":[{"title":"膝盖内扣","severity":"medium","description":"下蹲阶段膝盖略向内扣","timestamp":2.3,"impact":"长期可能增加膝关节压力","correction":"下蹲时主动让膝盖跟随第二脚趾方向"}],'
        '"corrections":[{"area":"膝盖追踪","technique":"下蹲时膝盖对准第二脚趾","drills":["弹力带深蹲","箱式深蹲"],"sets_reps":"3组x12次","next_filming_tip":"侧面拍摄，关注膝盖轨迹"}],'
        '"good_points":["背部保持平直","核心稳定"],'
        '"phases":[{"phase":"起始","observation":"站距与脚尖方向基本稳定"}],'
        '"coach_cues":["核心收紧","膝盖跟脚尖","控制离心","保持脊柱中立"]}'
    )
    prompt = (
        f"你是力量训练动作评估教练。下面是{media_desc}，动作类型：{movement_cn}。{injury_ctx}\n"
        "请只基于可见画面分析，不要编造看不到的角度；如果画面不完整，要降低置信并说明。\n"
        "评估维度：关节轨迹、躯干/脊柱稳定、动作幅度、节奏控制、左右对称、潜在伤病风险。\n"
        "输出严格 JSON，不要 markdown，不要额外文字。字段：\n"
        "- overall_score: 0-100 整数，70以下表示有明显技术风险\n"
        "- movement_name: 中文动作名\n"
        "- risk_level: low/medium/high\n"
        "- confidence: 0-1 置信度\n"
        "- summary: 50字以内整体评价\n"
        "- rep_count_estimate: 视频中可见的重复次数，单张照片填 null\n"
        "- metrics: 数组，每项含 name(维度名), score(0-100), description\n"
        "- issues: 数组，每项含 title, severity(high|medium|low), description, timestamp(视频秒数或null), impact, correction\n"
        "- corrections: 数组，每项含 area, technique, drills(数组), sets_reps, next_filming_tip\n"
        "- good_points: 数组，做得好的方面\n"
        "- phases: 数组，按起始/下降或离心/底部/上升或向心/结束给出观察\n"
        "- coach_cues: 3-6条短口令\n"
        f"示例：{output_example}"
    )

    try:
        from app.services.vision_service import get_vision_llm, encode_image
        from langchain_core.messages import HumanMessage

        content = [{"type": "text", "text": prompt}]
        for frame_bytes, mime_type in image_payloads[:6]:
            content.append({
                "type": "image_url",
                "image_url": {"url": encode_image(frame_bytes, mime_type=mime_type), "detail": "low"},
            })

        llm = get_vision_llm(max_tokens=900)
        response = llm.invoke([HumanMessage(content=content)])
        raw = response.content.strip()
        logger.info("Vision Model raw pose %s response: %s", "video" if is_video else "image", raw)
        parsed = _extract_json_object(raw)
        result = _normalize_pose_result(parsed, movement_cn, is_video)

        # 质量校验：分数为 0 且无有效内容时视为模型失败，降级到 mock
        has_metrics = bool(result.get("metrics"))
        has_issues = bool(result.get("issues"))
        logger.info("Pose quality check: score=%s metrics=%s issues=%s", result["overall_score"], has_metrics, has_issues)
        if result["overall_score"] == 0 and not has_metrics and not has_issues:
            logger.warning("Vision Model returned empty/invalid pose analysis; falling back to mock.")
            return None

        return result
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
        "overall_score": result["overall_score"],
        "score": result["overall_score"],
        "risk_level": result.get("risk_level", "low"),
        "summary": result.get("summary", ""),
        "confidence": result.get("confidence"),
        "metrics": result.get("metrics", []),
        "issues": result["issues"],
        "corrections": result.get("corrections", []),
        "good_points": result.get("good_points", []),
        "coach_cues": result["coach_cues"],
        "phases": result.get("phases", []),
        "rep_count_estimate": result.get("rep_count_estimate"),
        "analyzed_frames": 1,
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
        "overall_score": result["overall_score"],
        "score": result["overall_score"],
        "risk_level": result.get("risk_level", "low"),
        "summary": result.get("summary", ""),
        "confidence": result.get("confidence"),
        "metrics": result.get("metrics", []),
        "issues": result["issues"],
        "corrections": result.get("corrections", []),
        "good_points": result.get("good_points", []),
        "coach_cues": result["coach_cues"],
        "phases": result.get("phases", []),
        "rep_count_estimate": result.get("rep_count_estimate"),
        "analyzed_frames": len(frame_payloads),
        "risk_warnings": risk_warnings,
        "is_ai_analysis": result.get("is_ai", False),
        "media_type": "video",
    }
