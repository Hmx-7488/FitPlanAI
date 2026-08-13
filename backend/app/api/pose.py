"""AI 动作分析 API（Vision Model 驱动，带 Mock 降级）"""
import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import List
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.user import PoseAnalysisRecord, User
from app.services.image_utils import detect_video_type, image_extension, validate_image
from app.services.pose_metrics_service import compute_pose_metrics

router = APIRouter()
logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(__file__).parent.parent.parent / "data" / "uploads" / "pose"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
QUARANTINE_DIR = UPLOAD_DIR.parent.parent / ".media_deletion_quarantine" / "pose"

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 80 * 1024 * 1024


def _unlink_media_file(path: Path) -> None:
    path.unlink(missing_ok=True)


def _move_media_file(source: Path, target: Path) -> None:
    source.replace(target)


def _stage_media_deletion(paths: list[Path]) -> tuple[Path, list[tuple[Path, Path]]]:
    operation_dir = QUARANTINE_DIR / "pending" / uuid.uuid4().hex
    operation_dir.mkdir(parents=True, exist_ok=False)
    staged: list[tuple[Path, Path]] = []
    try:
        for source in paths:
            if not source.exists():
                continue
            target = operation_dir / source.name
            _move_media_file(source, target)
            staged.append((source, target))
    except OSError:
        for source, target in reversed(staged):
            try:
                _move_media_file(target, source)
            except OSError:
                logger.critical("Failed to restore staged pose media file=%s", source.name)
        try:
            operation_dir.rmdir()
        except OSError:
            pass
        raise
    return operation_dir, staged


def _restore_staged_media(staged: list[tuple[Path, Path]]) -> None:
    for source, target in reversed(staged):
        if target.exists():
            _move_media_file(target, source)


def _promote_staged_media(
    operation_dir: Path,
    staged: list[tuple[Path, Path]],
) -> tuple[Path, list[tuple[Path, Path]]]:
    committed_root = QUARANTINE_DIR / "committed"
    committed_root.mkdir(parents=True, exist_ok=True)
    committed_dir = committed_root / operation_dir.name
    _move_media_file(operation_dir, committed_dir)
    return committed_dir, [
        (source, committed_dir / target.name) for source, target in staged
    ]


def _cleanup_staged_media(
    operation_dir: Path,
    staged: list[tuple[Path, Path]],
) -> bool:
    pending = False
    for _, target in staged:
        try:
            _unlink_media_file(target)
        except OSError:
            pending = True
            logger.exception("Quarantined pose media cleanup failed file=%s", target.name)
    if not pending:
        try:
            operation_dir.rmdir()
        except OSError:
            pass
    return pending


def cleanup_pose_deletion_quarantine() -> int:
    """Retry removal of media already detached from committed deleted records."""
    committed_root = QUARANTINE_DIR / "committed"
    if not committed_root.exists():
        return 0
    removed = 0
    for operation_dir in committed_root.iterdir():
        if not operation_dir.is_dir():
            continue
        for target in operation_dir.iterdir():
            if target.is_file():
                try:
                    _unlink_media_file(target)
                    removed += 1
                except OSError:
                    logger.warning("Pose quarantine cleanup will retry file=%s", target.name)
        try:
            operation_dir.rmdir()
        except OSError:
            pass
    return removed

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


def _user_injuries(user) -> list[str]:
    try:
        value = json.loads(user.injuries) if user.injuries else []
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item)[:100] for item in value[:20]] if isinstance(value, list) else []


def _build_risk_warnings(user, movement_key: str) -> list[str]:
    """根据用户伤病生成风险提示"""
    injuries = _user_injuries(user)
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
    quantitative: dict | None = None,
) -> dict | None:
    injuries = _user_injuries(user)
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
        f"MediaPipe 关键点量化结果：{json.dumps(quantitative or {}, ensure_ascii=False)}\n"
        "关键点结果中的角度、轨迹、速度、对称性和重复次数是计算值，不得被视觉猜测覆盖；你的任务是解释计算结果并补充可见动作语义。\n"
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
        response = await asyncio.to_thread(llm.invoke, [HumanMessage(content=content)])
        raw = response.content.strip()
        logger.info(
            "Vision pose response received: media=%s chars=%s",
            "video" if is_video else "image",
            len(raw),
        )
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


def _keypoint_only_result(quantitative: dict, movement_cn: str) -> dict:
    metrics = quantitative.get("metrics", [])
    scores = [item["score"] for item in metrics if isinstance(item, dict) and "score" in item]
    score = _clamp_int(sum(scores) / len(scores) if scores else 0, default=0)
    quality = quantitative.get("quality", {})
    return {
        "movement_name": movement_cn,
        "overall_score": score,
        "score": score,
        "risk_level": "medium" if score < 65 else "low",
        "confidence": quality.get("confidence", 0),
        "summary": "Vision Model 暂时不可用，当前结果仅由 MediaPipe 关键点几何数据计算。",
        "metrics": metrics,
        "issues": [],
        "corrections": [],
        "good_points": [],
        "coach_cues": ["保持全身入镜", "动作匀速", "下一次使用相同机位复测"],
        "phases": [],
        "rep_count_estimate": quantitative.get("rep_count_estimate"),
        "is_ai": False,
    }


def _merge_quantitative_result(result: dict, quantitative: dict) -> dict:
    computed_metrics = quantitative.get("metrics", [])
    computed_names = {item.get("name") for item in computed_metrics if isinstance(item, dict)}
    semantic_metrics = [
        item for item in result.get("metrics", [])
        if item.get("name") not in computed_names
    ]
    result["metrics"] = computed_metrics + semantic_metrics[:3]
    result["rep_count_estimate"] = quantitative.get("rep_count_estimate")
    result["confidence"] = min(
        float(result.get("confidence") or 0.6),
        float(quantitative.get("quality", {}).get("confidence", 0.6)),
    )
    return result


def _parse_pose_data(raw: str | None, movement_key: str) -> dict | None:
    if not raw:
        return None
    if len(raw) > 2_000_000:
        raise HTTPException(status_code=413, detail="关键点数据过大")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="关键点数据格式无效") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="关键点数据必须是 JSON 对象")
    return compute_pose_metrics(payload, movement_key)


def _remove_pose_files(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.exception("Failed to roll back pose media file: %s", path.name)


async def _persist_pose_media(
    db: AsyncSession,
    user_id: int,
    media_urls: list[str],
) -> str:
    record_id = uuid.uuid4().hex
    db.add(PoseAnalysisRecord(
        id=record_id,
        user_id=user_id,
        media_paths_json=json.dumps(media_urls, ensure_ascii=False),
    ))
    await db.commit()
    return f"pose_{record_id}"


async def _persist_pose_media_or_rollback(
    db: AsyncSession,
    user_id: int,
    media_urls: list[str],
    saved_paths: list[Path],
) -> str:
    try:
        return await _persist_pose_media(db, user_id, media_urls)
    except Exception:
        await db.rollback()
        _remove_pose_files(saved_paths)
        raise


@router.post("/analyze")
async def analyze_pose(
    user_id: int = Form(...),
    image: UploadFile = File(...),
    movement_name: str = Form("squat"),
    pose_data: str | None = Form(None),
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
    movement_key = movement_name.lower().replace(" ", "_")
    movement_cn = MOVEMENT_NAMES.get(movement_key, movement_name)
    quantitative = _parse_pose_data(pose_data, movement_key)

    saved_name = f"{uuid.uuid4().hex}{image_extension(mime_type)}"
    saved_path = UPLOAD_DIR / saved_name
    try:
        saved_path.write_bytes(content)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="动作图片保存失败") from exc
    photo_url = f"/uploads/pose/{saved_name}"

    if quantitative and not quantitative["quality"]["is_usable"]:
        analysis_id = await _persist_pose_media_or_rollback(
            db, user_id, [photo_url], [saved_path]
        )
        return {
            "analysis_id": analysis_id,
            "photo_url": photo_url,
            "movement_name": movement_cn,
            "overall_score": 0,
            "score": 0,
            "risk_level": "medium",
            "summary": "照片未通过关键点质量校验，请确保全身关节清晰入镜后重试。",
            "confidence": quantitative["quality"]["confidence"],
            "metrics": [],
            "issues": [],
            "corrections": [],
            "good_points": [],
            "coach_cues": [],
            "phases": [],
            "rep_count_estimate": None,
            "analyzed_frames": quantitative["sampled_frames"],
            "risk_warnings": [],
            "is_ai_analysis": False,
            "is_quantitative_analysis": False,
            "analysis_source": "rejected",
            "analysis_status": "rejected",
            "pose_quality": quantitative["quality"],
            "joint_angles": {},
            "media_type": "image",
        }

    result = await _analyze_pose_frames(
        [(content, mime_type)],
        user,
        movement_key,
        movement_cn,
        is_video=False,
        quantitative=quantitative,
    )

    analysis_source = "hybrid" if quantitative and quantitative.get("available") else "vision_only"
    if result is None:
        if quantitative and quantitative.get("available"):
            result = _keypoint_only_result(quantitative, movement_cn)
            analysis_source = "keypoint_only"
        else:
            template = MOCK_FALLBACK.get(movement_key, DEFAULT_MOCK)
            result = {**template, "phases": [], "rep_count_estimate": None, "is_ai": False}
            analysis_source = "template"
    elif quantitative and quantitative.get("available"):
        result = _merge_quantitative_result(result, quantitative)

    # 伤病风险提示
    risk_warnings = _build_risk_warnings(user, movement_key)

    analysis_id = await _persist_pose_media_or_rollback(
        db, user_id, [photo_url], [saved_path]
    )
    return {
        "analysis_id": analysis_id,
        "photo_url": photo_url,
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
        "is_quantitative_analysis": bool(quantitative and quantitative.get("available")),
        "analysis_source": analysis_source,
        "analysis_status": "completed" if analysis_source != "template" else "fallback",
        "pose_quality": quantitative.get("quality") if quantitative else None,
        "joint_angles": quantitative.get("joint_angles", {}) if quantitative else {},
        "media_type": "image",
    }


@router.post("/analyze-video")
async def analyze_pose_video(
    user_id: int = Form(...),
    video: UploadFile = File(...),
    frames: List[UploadFile] = File(...),
    movement_name: str = Form("squat"),
    pose_data: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """上传动作视频和前端抽帧，Vision Model 按时间序列分析动作质量"""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    video_content = await video.read()
    if len(video_content) > MAX_VIDEO_BYTES:
        raise HTTPException(status_code=400, detail="Video must be smaller than 80MB")
    try:
        _, video_ext = detect_video_type(video_content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    video_name = f"{uuid.uuid4().hex}{video_ext}"
    video_path = UPLOAD_DIR / video_name

    frame_payloads: list[tuple[bytes, str]] = []
    frame_names: list[str] = []
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
        frame_name = f"{Path(video_name).stem}_frame_{index}{image_extension(mime_type)}"
        frame_names.append(frame_name)
        frame_payloads.append((frame_bytes, mime_type))

    if len(frame_payloads) < 2:
        raise HTTPException(status_code=400, detail="At least 2 valid video frames are required")

    movement_key = movement_name.lower().replace(" ", "_")
    movement_cn = MOVEMENT_NAMES.get(movement_key, movement_name)
    quantitative = _parse_pose_data(pose_data, movement_key)

    saved_paths = [video_path, *(UPLOAD_DIR / name for name in frame_names)]
    try:
        video_path.write_bytes(video_content)
        for saved_path, (frame_bytes, _) in zip(saved_paths[1:], frame_payloads):
            saved_path.write_bytes(frame_bytes)
    except OSError as exc:
        _remove_pose_files(saved_paths)
        raise HTTPException(status_code=500, detail="动作视频保存失败") from exc
    video_url = f"/uploads/pose/{video_name}"
    frame_urls = [f"/uploads/pose/{name}" for name in frame_names]

    if quantitative and not quantitative["quality"]["is_usable"]:
        analysis_id = await _persist_pose_media_or_rollback(
            db, user_id, [video_url, *frame_urls], saved_paths
        )
        return {
            "analysis_id": analysis_id,
            "video_url": video_url,
            "frame_urls": frame_urls,
            "movement_name": movement_cn,
            "overall_score": 0,
            "score": 0,
            "risk_level": "medium",
            "summary": "视频关键点覆盖不足，无法稳定计算关节角度和轨迹。请按拍摄提示重试。",
            "confidence": quantitative["quality"]["confidence"],
            "metrics": [],
            "issues": [],
            "corrections": [],
            "good_points": [],
            "coach_cues": [],
            "phases": [],
            "rep_count_estimate": None,
            "analyzed_frames": quantitative["sampled_frames"],
            "risk_warnings": [],
            "is_ai_analysis": False,
            "is_quantitative_analysis": False,
            "analysis_source": "rejected",
            "analysis_status": "rejected",
            "pose_quality": quantitative["quality"],
            "joint_angles": {},
            "media_type": "video",
        }

    result = await _analyze_pose_frames(
        frame_payloads,
        user,
        movement_key,
        movement_cn,
        is_video=True,
        quantitative=quantitative,
    )

    analysis_source = "hybrid" if quantitative and quantitative.get("available") else "vision_only"
    if result is None:
        if quantitative and quantitative.get("available"):
            result = _keypoint_only_result(quantitative, movement_cn)
            analysis_source = "keypoint_only"
        else:
            template = MOCK_FALLBACK.get(movement_key, DEFAULT_MOCK)
            result = {**template, "phases": [], "rep_count_estimate": None, "is_ai": False}
            analysis_source = "template"
    elif quantitative and quantitative.get("available"):
        result = _merge_quantitative_result(result, quantitative)

    risk_warnings = _build_risk_warnings(user, movement_key)

    analysis_id = await _persist_pose_media_or_rollback(
        db, user_id, [video_url, *frame_urls], saved_paths
    )
    return {
        "analysis_id": analysis_id,
        "video_url": video_url,
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
        "analyzed_frames": quantitative.get("sampled_frames", len(frame_payloads)) if quantitative else len(frame_payloads),
        "risk_warnings": risk_warnings,
        "is_ai_analysis": result.get("is_ai", False),
        "is_quantitative_analysis": bool(quantitative and quantitative.get("available")),
        "analysis_source": analysis_source,
        "analysis_status": "completed" if analysis_source != "template" else "fallback",
        "pose_quality": quantitative.get("quality") if quantitative else None,
        "joint_angles": quantitative.get("joint_angles", {}) if quantitative else {},
        "media_type": "video",
    }


@router.delete("/history/{user_id}/{analysis_id}")
async def delete_pose_analysis(
    user_id: int,
    analysis_id: str,
    db: AsyncSession = Depends(get_db),
):
    record_id = analysis_id.removeprefix("pose_")
    if len(record_id) != 32 or any(char not in "0123456789abcdef" for char in record_id):
        raise HTTPException(status_code=400, detail="无效的 analysis_id")
    record = await db.get(PoseAnalysisRecord, record_id)
    if record is None or record.user_id != user_id:
        raise HTTPException(status_code=404, detail="记录不存在")
    try:
        media_urls = json.loads(record.media_paths_json or "[]")
    except (TypeError, json.JSONDecodeError):
        media_urls = []
    upload_root = UPLOAD_DIR.resolve()
    media_paths: list[Path] = []
    for value in media_urls if isinstance(media_urls, list) else []:
        url = str(value)
        if not url.startswith("/uploads/pose/"):
            logger.error("Rejected unsafe pose media path in record=%s", record_id)
            raise HTTPException(status_code=409, detail="媒体记录路径无效，无法安全删除")
        candidate = (UPLOAD_DIR / Path(url).name).resolve()
        if candidate.parent != upload_root:
            raise HTTPException(status_code=409, detail="媒体记录路径无效，无法安全删除")
        media_paths.append(candidate)
    media_paths = list(dict.fromkeys(media_paths))
    try:
        operation_dir, staged = _stage_media_deletion(media_paths)
    except OSError:
        logger.exception(
            "Pose media staging failed: user_id=%s record_id=%s",
            user_id,
            record_id,
        )
        raise HTTPException(status_code=503, detail="媒体文件暂时无法删除，请稍后重试")
    try:
        await db.delete(record)
        await db.commit()
    except Exception:
        await db.rollback()
        try:
            _restore_staged_media(staged)
            operation_dir.rmdir()
        except OSError:
            logger.critical(
                "Pose delete rollback could not restore media user_id=%s record_id=%s",
                user_id,
                record_id,
            )
        raise
    try:
        operation_dir, staged = _promote_staged_media(operation_dir, staged)
    except OSError:
        logger.critical(
            "Pose deletion committed but quarantine promotion failed: "
            "user_id=%s record_id=%s",
            user_id,
            record_id,
        )
    cleanup_pending = _cleanup_staged_media(operation_dir, staged)
    return {
        "deleted": True,
        "analysis_id": analysis_id,
        "removed_files": len(staged),
        "cleanup_pending": cleanup_pending,
    }
