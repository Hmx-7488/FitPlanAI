"""Body-photo analysis with quality gates, measurement fusion and history."""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import BodyAnalysis, User
from app.services.body_analysis_service import (
    assess_photo_quality,
    fuse_body_fat_estimate,
    navy_body_fat,
    select_comparable_views,
    validate_measurements,
)
from app.services.image_utils import image_extension, validate_image
from app.services.profile_service import update_profile

router = APIRouter()
logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(__file__).parent.parent.parent / "data" / "uploads" / "body"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_IMAGE_BYTES = 10 * 1024 * 1024

VIEW_LABELS = {
    "front": "正面",
    "side": "侧面",
    "back": "背面",
}


def _json_load(raw: str | None, fallback: Any) -> Any:
    try:
        value = json.loads(raw or "")
        return value
    except (TypeError, json.JSONDecodeError):
        return fallback


def _extract_json_object(raw: str) -> dict:
    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end <= start:
        raise ValueError("Body analysis response does not contain a JSON object")
    data = json.loads(text[start:end])
    if not isinstance(data, dict):
        raise ValueError("Body analysis response must be a JSON object")
    return data


def _bmi_fallback(user) -> dict:
    """Compatibility fallback used only when the provider is unavailable."""
    weight = user.weight or 70
    height_m = (user.height or 170) / 100
    bmi = weight / (height_m * height_m) if height_m > 0 else 22
    if bmi < 18.5:
        estimate, range_text = 12.0, "10%-15%"
    elif bmi < 24:
        estimate, range_text = 21.0, "18%-24%"
    elif bmi < 28:
        estimate, range_text = 27.0, "25%-30%"
    else:
        estimate, range_text = 32.0, "30%-35%"
    return {
        "body_fat_estimate": estimate,
        "body_fat_range": range_text,
        "confidence": 0.35,
        "shape_notes": f"视觉服务不可用，当前仅基于 BMI {bmi:.1f} 给出低置信度参考",
        "training_focus": ["全身力量训练", "低强度有氧", "核心稳定"],
        "nutrition_suggestion": "先记录体重和腰围趋势，避免仅凭本次估算调整饮食。",
        "is_ai": False,
    }


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
        midpoint = (low + high) / 2
        low, high = midpoint - 1.5, midpoint + 1.5
    if high - low > 12:
        midpoint = (low + high) / 2
        low, high = midpoint - 6, midpoint + 6
    minimum, maximum = (5, 45) if user.gender == "male" else (12, 52)
    low = max(minimum, min(low, maximum))
    high = max(minimum, min(high, maximum))
    if high <= low:
        high = min(maximum, low + 3)
    return round(low, 1), round(high, 1)


def _model_confidence(parsed: dict, low: float, high: float) -> float:
    try:
        confidence = float(parsed.get("confidence", 0.6))
    except (TypeError, ValueError):
        confidence = 0.6
    if high - low > 8:
        confidence -= 0.08
    return round(max(0.15, min(confidence, 0.9)), 2)


async def _save_body_image(upload: UploadFile, view: str, user_id: int) -> dict:
    content = await upload.read()
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="图片必须小于 10MB")
    try:
        mime_type, width, height = validate_image(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    saved_name = f"{uuid.uuid4().hex}_{view}{image_extension(mime_type, upload.filename)}"
    saved_path = UPLOAD_DIR / saved_name
    saved_path.write_bytes(content)
    logger.info(
        "Body photo saved: user_id=%s view=%s mime=%s bytes=%s dimensions=%sx%s",
        user_id,
        view,
        mime_type,
        len(content),
        width,
        height,
    )
    return {
        "view": view,
        "filename": saved_name,
        "path": saved_path,
        "content": content,
        "mime_type": mime_type,
        "width": width,
        "height": height,
        "aspect_ratio": round(width / height, 4),
    }


def _build_analysis_prompt(user: User, saved_images: list[dict], measurements: dict[str, float]) -> str:
    height_m = (user.height or 170) / 100
    weight = measurements.get("measured_weight_kg", user.weight or 70)
    bmi = weight / (height_m * height_m) if height_m > 0 else 22
    measurement_text = json.dumps(measurements, ensure_ascii=False) if measurements else "未提供"
    views = "、".join(VIEW_LABELS[item["view"]] for item in saved_images)
    return f"""
你是一名严谨的健身体态和身体成分评估助手。任务是进行非医疗性质的区间估算。

用户资料：年龄={user.age}，性别={user.gender}，身高={user.height}cm，体重={weight}kg，BMI={bmi:.1f}。
用户手工测量：{measurement_text}。这些数字只能作为用户提供的数据使用，禁止从照片虚构围度。
上传视角：{views}。

必须先逐张检查质量。以下任一情况应将对应视角 usable 设为 false：
- 不是声明的正面/侧面/背面，躯干不完整，人物过小或严重裁切；
- 逆光、过暗、过曝、明显滤镜或镜面广角畸变；
- 宽松衣物遮挡轮廓、重度遮挡、刻意收腹或夸张摆姿；
- 无法确认是同一位成年人，或图片内容不适合身材分析。

分析约束：
1. 体脂只能输出区间，单视角或质量一般时扩大区间并降低置信度。
2. 不得诊断脊柱侧弯、骨盆前倾等疾病，只能描述可见姿态倾向并注明局限。
3. 如果没有任何可用视角，is_usable=false，不得为了完成任务而猜测体脂。
4. training_focus 给出 2-4 个可执行训练重点，nutrition 给出一句可执行建议。
5. 面向用户的文字必须使用简体中文。

只返回严格 JSON：
{{
  "is_usable": true,
  "body_fat_low": 18,
  "body_fat_high": 24,
  "confidence": 0.72,
  "shape_notes": "仅描述照片中可见轮廓和体态倾向",
  "visible_body_regions": ["正面躯干"],
  "training_focus": ["核心稳定", "下肢复合训练"],
  "nutrition": "建议内容",
  "limitations": ["照片估算不能替代专业测量"],
  "view_quality": {{
    "front": {{
      "usable": true,
      "correct_view": true,
      "full_body_visible": true,
      "torso_visible": true,
      "lighting": "good",
      "clothing": "fitted",
      "occlusion": "none",
      "camera_level": "waist",
      "issues": []
    }}
  }}
}}
""".strip()


async def _latest_completed(db: AsyncSession, user_id: int) -> BodyAnalysis | None:
    query = (
        select(BodyAnalysis)
        .where(BodyAnalysis.user_id == user_id, BodyAnalysis.status == "completed")
        .order_by(BodyAnalysis.created_at.desc())
        .limit(1)
    )
    return (await db.execute(query)).scalar_one_or_none()


def _load_previous_images(previous: BodyAnalysis, views: list[str]) -> list[dict]:
    photo_urls = _json_load(previous.photo_urls_json, {})
    loaded: list[dict] = []
    for view in views:
        url = str(photo_urls.get(view, ""))
        filename = Path(url).name
        path = UPLOAD_DIR / filename
        if not filename or not path.is_file() or path.parent != UPLOAD_DIR:
            continue
        content = path.read_bytes()
        try:
            mime_type, width, height = validate_image(content)
        except ValueError:
            continue
        loaded.append({
            "view": view,
            "content": content,
            "mime_type": mime_type,
            "width": width,
            "height": height,
        })
    return loaded


def _run_comparison(
    llm,
    current_images: list[dict],
    previous: BodyAnalysis,
    comparable_views: list[str],
    current_measurements: dict[str, float],
) -> dict:
    from app.services.vision_service import encode_image
    from langchain_core.messages import HumanMessage

    previous_images = _load_previous_images(previous, comparable_views)
    previous_measurements = _json_load(previous.measurements_json, {})
    available = [item["view"] for item in previous_images]
    if not available:
        return {
            "is_comparable": False,
            "comparable_views": [],
            "summary": "历史照片文件不可用，无法进行阶段对比。",
            "limitations": ["请保留相同角度和拍摄条件重新建立基线"],
        }
    prompt = f"""
比较同一用户两个阶段的身材照片，只比较这些同角度视图：{available}。
上次测量={json.dumps(previous_measurements, ensure_ascii=False)}；
本次测量={json.dumps(current_measurements, ensure_ascii=False)}。

要求：
1. 先判断光线、距离、镜头高度、衣物和姿态是否足够接近。
2. 只能描述可见轮廓变化，不得把光线、收腹或姿态差异解释为减脂。
3. 不得从照片推断精确减脂公斤数或医学结论。
4. 不可比时 is_comparable=false，并说明原因。
5. 只返回严格 JSON，文字使用简体中文。

结构：
{{"is_comparable":true,"confidence":0.7,"comparable_views":["front"],"summary":"阶段变化摘要",
"changes":["腰腹轮廓变化较小"],"limitations":["拍摄光线存在轻微差异"]}}
""".strip()
    content: list[dict] = [{"type": "text", "text": prompt}]
    current_by_view = {item["view"]: item for item in current_images}
    for view in available:
        previous_item = next(item for item in previous_images if item["view"] == view)
        current_item = current_by_view.get(view)
        if not current_item:
            continue
        content.extend([
            {"type": "text", "text": f"上次{VIEW_LABELS[view]}："},
            {"type": "image_url", "image_url": {
                "url": encode_image(previous_item["content"], previous_item["mime_type"]),
                "detail": "high",
            }},
            {"type": "text", "text": f"本次{VIEW_LABELS[view]}："},
            {"type": "image_url", "image_url": {
                "url": encode_image(current_item["content"], current_item["mime_type"]),
                "detail": "high",
            }},
        ])
    parsed = _extract_json_object(llm.invoke([HumanMessage(content=content)]).content)
    return {
        "is_comparable": bool(parsed.get("is_comparable", False)),
        "confidence": round(max(0, min(float(parsed.get("confidence", 0)), 0.9)), 2),
        "comparable_views": [view for view in parsed.get("comparable_views", []) if view in available],
        "summary": str(parsed.get("summary", "")),
        "changes": [str(item) for item in parsed.get("changes", [])[:5]],
        "limitations": [str(item) for item in parsed.get("limitations", [])[:4]],
        "previous_analysis_id": f"body_{previous.id}",
        "previous_created_at": previous.created_at.isoformat(),
    }


def _measurement_changes(current: dict[str, float], previous: BodyAnalysis | None) -> dict[str, float]:
    if not previous:
        return {}
    old = _json_load(previous.measurements_json, {})
    changes: dict[str, float] = {}
    for key, value in current.items():
        if key in old:
            changes[key] = round(value - float(old[key]), 1)
    return changes


def _history_item(record: BodyAnalysis) -> dict:
    result = _json_load(record.result_json, {})
    return {
        "analysis_id": f"body_{record.id}",
        "status": record.status,
        "created_at": record.created_at.isoformat(),
        "photo_urls": _json_load(record.photo_urls_json, {}),
        "measurements": _json_load(record.measurements_json, {}),
        "quality_check": _json_load(record.quality_json, {}),
        "body_fat_estimate": result.get("body_fat_estimate"),
        "comparison": result.get("comparison"),
        "confidence": record.confidence,
        "is_ai_analysis": bool(record.is_ai),
    }


@router.post("/analyze")
async def analyze_body_photo(
    user_id: int = Form(...),
    image: UploadFile | None = File(None),
    front_image: UploadFile | None = File(None),
    side_image: UploadFile | None = File(None),
    back_image: UploadFile | None = File(None),
    waist_cm: float | None = Form(None),
    hip_cm: float | None = Form(None),
    chest_cm: float | None = Form(None),
    neck_cm: float | None = Form(None),
    body_fat_scale_pct: float | None = Form(None),
    measured_weight_kg: float | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    try:
        measurements = validate_measurements({
            "waist_cm": waist_cm,
            "hip_cm": hip_cm,
            "chest_cm": chest_cm,
            "neck_cm": neck_cm,
            "body_fat_scale_pct": body_fat_scale_pct,
            "measured_weight_kg": measured_weight_kg,
        })
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    uploads = [
        (view, upload)
        for view, upload in (
            ("front", front_image),
            ("side", side_image),
            ("back", back_image),
        )
        if upload
    ]
    if image and not uploads:
        uploads.append(("front", image))
    if not uploads:
        raise HTTPException(status_code=400, detail="至少上传一张身材照片")
    saved_images = [await _save_body_image(upload, view, user_id) for view, upload in uploads[:3]]
    previous = await _latest_completed(db, user_id)

    photo_urls = {item["view"]: f"/uploads/body/{item['filename']}" for item in saved_images}
    view_metadata = {
        item["view"]: {
            "width": item["width"],
            "height": item["height"],
            "aspect_ratio": item["aspect_ratio"],
        }
        for item in saved_images
    }

    result: dict[str, Any]
    quality: dict[str, Any]
    status = "completed"
    is_ai = True
    llm = None
    try:
        from app.services.vision_service import encode_image, get_vision_llm
        from langchain_core.messages import HumanMessage

        llm = get_vision_llm(max_tokens=1400)
        content: list[dict] = [{"type": "text", "text": _build_analysis_prompt(user, saved_images, measurements)}]
        for item in saved_images:
            content.extend([
                {"type": "text", "text": f"{VIEW_LABELS[item['view']]}照片："},
                {"type": "image_url", "image_url": {
                    "url": encode_image(item["content"], item["mime_type"]),
                    "detail": "high",
                }},
            ])
        raw = llm.invoke([HumanMessage(content=content)]).content
        logger.info(
            "Body analysis response received: user_id=%s response_chars=%s",
            user_id,
            len(raw),
        )
        parsed = _extract_json_object(raw)
        low, high = _coerce_body_fat_range(parsed.get("body_fat_low"), parsed.get("body_fat_high"), user)
        confidence = _model_confidence(parsed, low, high)
        quality = assess_photo_quality(parsed, [item["view"] for item in saved_images], confidence)
        if not quality["is_usable"]:
            status = "rejected"
            result = {
                "body_fat_estimate": None,
                "training_focus": [],
                "nutrition_suggestion": "",
                "shape_notes": "",
                "limitations": [str(item) for item in parsed.get("limitations", [])[:4]],
                "confidence": min(confidence, 0.39),
            }
        else:
            fused = fuse_body_fat_estimate(
                gender=user.gender,
                height_cm=user.height,
                vision_low=low,
                vision_high=high,
                vision_confidence=confidence,
                measurements=measurements,
                usable_view_count=len(quality["usable_views"]),
            )
            result = {
                **fused,
                "body_fat_estimate": {
                    "value": fused["body_fat_estimate"],
                    "estimated_range": fused["body_fat_range"],
                    "confidence": fused["confidence"],
                    "note": str(parsed.get("shape_notes", "")),
                    "sources": fused["estimate_sources"],
                },
                "training_focus": [str(item) for item in parsed.get("training_focus", [])[:4]],
                "nutrition_suggestion": str(parsed.get("nutrition", "")),
                "shape_notes": str(parsed.get("shape_notes", "")),
                "limitations": [str(item) for item in parsed.get("limitations", [])[:4]],
                "confidence": fused["confidence"],
            }
    except Exception:
        logger.exception(
            "Vision body analysis failed: user_id=%s views=%s",
            user_id,
            [item["view"] for item in saved_images],
        )
        status = "fallback"
        is_ai = False
        fallback = _bmi_fallback(user)
        navy = navy_body_fat(
            user.gender,
            user.height,
            measurements.get("waist_cm"),
            measurements.get("hip_cm"),
            measurements.get("neck_cm"),
        )
        if navy is not None:
            lower_bound, upper_bound = (5, 45) if user.gender == "male" else (12, 52)
            fallback["body_fat_estimate"] = navy
            fallback["body_fat_range"] = (
                f"{max(lower_bound, navy - 3):.1f}%-{min(upper_bound, navy + 3):.1f}%"
            )
            fallback["confidence"] = 0.5
            fallback["shape_notes"] = "视觉服务不可用，当前为围度公式的非视觉参考值"
        quality = {
            "is_usable": False,
            "usable_views": [],
            "views": {},
            "rejection_reasons": ["视觉分析服务暂时不可用，未完成照片质量判定"],
            "retake_guidance": [],
        }
        result = {
            **fallback,
            "body_fat_estimate": {
                "value": fallback["body_fat_estimate"],
                "estimated_range": fallback["body_fat_range"],
                "confidence": fallback["confidence"],
                "note": fallback["shape_notes"],
                "sources": [],
            },
            "tracking_metrics": {},
        }

    comparison = None
    if status == "completed" and previous and llm:
        previous_metadata = _json_load(previous.view_metadata_json, {})
        previous_quality = _json_load(previous.quality_json, {})
        comparable = select_comparable_views(
            view_metadata,
            previous_metadata,
            quality,
            previous_quality,
        )
        if comparable:
            try:
                comparison = _run_comparison(llm, saved_images, previous, comparable, measurements)
            except Exception:
                logger.exception("Body history comparison failed: user_id=%s", user_id)
                comparison = {
                    "is_comparable": False,
                    "comparable_views": comparable,
                    "summary": "阶段照片对比服务暂时不可用。",
                    "limitations": ["本次基础分析已保留，可稍后重新分析"],
                }
        else:
            comparison = {
                "is_comparable": False,
                "comparable_views": [],
                "summary": "本次与上次没有满足同角度、相近画幅和合格质量的照片。",
                "limitations": ["下次请固定机位高度、距离、光线和衣物"],
            }
        comparison["measurement_changes"] = _measurement_changes(measurements, previous)
        result["comparison"] = comparison

    record = BodyAnalysis(
        user_id=user_id,
        status=status,
        photo_urls_json=json.dumps(photo_urls, ensure_ascii=False),
        view_metadata_json=json.dumps(view_metadata, ensure_ascii=False),
        measurements_json=json.dumps(measurements, ensure_ascii=False),
        quality_json=json.dumps(quality, ensure_ascii=False),
        result_json=json.dumps(result, ensure_ascii=False),
        confidence=float(result.get("confidence", 0)),
        is_ai=1 if is_ai else 0,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    auto_fill = bool(
        status == "completed"
        and result.get("body_fat_estimate")
        and result.get("confidence", 0) >= 0.65
    )
    if auto_fill:
        await update_profile(db, user_id, {
            "body_fat_rate": result["body_fat_estimate"]["value"],
        })

    body_fat = result.get("body_fat_estimate")
    if body_fat is None:
        body_fat = {
            "value": None,
            "estimated_range": "",
            "confidence": result.get("confidence", 0),
            "note": "当前照片未通过质量校验，未生成体脂区间。",
            "sources": [],
        }
    return {
        "analysis_id": f"body_{record.id}",
        "status": status,
        "created_at": record.created_at.isoformat(),
        "photo_url": next(iter(photo_urls.values())),
        "photo_urls": photo_urls,
        "measurements": measurements,
        "quality_check": quality,
        "body_fat_estimate": body_fat,
        "tracking_metrics": result.get("tracking_metrics", {}),
        "training_focus": result.get("training_focus", []),
        "nutrition_suggestion": result.get("nutrition_suggestion", ""),
        "limitations": result.get("limitations", []),
        "comparison": comparison,
        "auto_filled": auto_fill,
        "is_ai_analysis": is_ai,
    }


@router.get("/history/{user_id}")
async def get_body_analysis_history(
    user_id: int,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
):
    if not await db.get(User, user_id):
        raise HTTPException(status_code=404, detail="用户不存在")
    query = (
        select(BodyAnalysis)
        .where(BodyAnalysis.user_id == user_id)
        .order_by(BodyAnalysis.created_at.desc())
        .limit(max(1, min(limit, 30)))
    )
    records = (await db.execute(query)).scalars().all()
    return [_history_item(record) for record in records]


@router.delete("/history/{user_id}/{analysis_id}")
async def delete_body_analysis(
    user_id: int,
    analysis_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除一条身材分析记录及其照片文件（隐私删除入口）。"""
    try:
        record_id = int(analysis_id.removeprefix("body_"))
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的 analysis_id")

    record = await db.get(BodyAnalysis, record_id)
    if not record or record.user_id != user_id:
        raise HTTPException(status_code=404, detail="记录不存在")

    photo_urls = _json_load(record.photo_urls_json, {})
    await db.delete(record)
    await db.commit()

    # 清理照片文件：仅限身材上传目录内，防路径穿越
    removed_files = 0
    upload_root = UPLOAD_DIR.resolve()
    for url in photo_urls.values():
        filename = str(url).rsplit("/", 1)[-1]
        if not filename:
            continue
        candidate = (UPLOAD_DIR / filename).resolve()
        if candidate.parent == upload_root and candidate.exists():
            candidate.unlink()
            removed_files += 1

    logger.info(
        "Body analysis deleted: user_id=%s analysis_id=%s removed_files=%s",
        user_id,
        analysis_id,
        removed_files,
    )
    return {"deleted": True, "analysis_id": analysis_id, "removed_files": removed_files}
