"""Pure helpers for body-photo quality checks and estimate fusion."""
from __future__ import annotations

import math
from typing import Any


MEASUREMENT_RANGES = {
    "waist_cm": (40.0, 200.0),
    "hip_cm": (50.0, 220.0),
    "chest_cm": (50.0, 220.0),
    "neck_cm": (20.0, 80.0),
    "body_fat_scale_pct": (3.0, 60.0),
    "measured_weight_kg": (25.0, 350.0),
}


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no", ""}:
            return False
    if value is None:
        return default
    return bool(value)


def validate_measurements(values: dict[str, Any]) -> dict[str, float]:
    cleaned: dict[str, float] = {}
    for key, bounds in MEASUREMENT_RANGES.items():
        value = values.get(key)
        if value in (None, ""):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be a number") from exc
        if not bounds[0] <= number <= bounds[1]:
            raise ValueError(f"{key} must be between {bounds[0]:g} and {bounds[1]:g}")
        cleaned[key] = round(number, 1)
    return cleaned


def navy_body_fat(
    gender: str,
    height_cm: float,
    waist_cm: float | None,
    hip_cm: float | None,
    neck_cm: float | None,
) -> float | None:
    """Return the US Navy circumference estimate when required inputs exist."""
    if not height_cm or not waist_cm or not neck_cm:
        return None
    try:
        if gender == "male":
            circumference = waist_cm - neck_cm
            if circumference <= 0:
                return None
            density = (
                1.0324
                - 0.19077 * math.log10(circumference)
                + 0.15456 * math.log10(height_cm)
            )
        else:
            if not hip_cm:
                return None
            circumference = waist_cm + hip_cm - neck_cm
            if circumference <= 0:
                return None
            density = (
                1.29579
                - 0.35004 * math.log10(circumference)
                + 0.22100 * math.log10(height_cm)
            )
        result = 495 / density - 450
    except (ValueError, ZeroDivisionError):
        return None
    lower, upper = (5.0, 45.0) if gender == "male" else (12.0, 52.0)
    return round(max(lower, min(result, upper)), 1)


def normalize_view_quality(parsed: dict[str, Any], uploaded_views: list[str]) -> dict[str, dict[str, Any]]:
    raw = parsed.get("view_quality")
    raw = raw if isinstance(raw, dict) else {}
    normalized: dict[str, dict[str, Any]] = {}
    for view in uploaded_views:
        item = raw.get(view)
        has_assessment = isinstance(item, dict)
        item = item if has_assessment else {}
        issues = item.get("issues")
        normalized_issues = [str(value) for value in issues[:4]] if isinstance(issues, list) else []
        if not has_assessment:
            normalized_issues.append("模型未返回该视角的质量检查")
        normalized[view] = {
            "usable": _as_bool(item.get("usable"), default=False) if has_assessment else False,
            "correct_view": _as_bool(item.get("correct_view"), default=False),
            "full_body_visible": _as_bool(item.get("full_body_visible"), default=False),
            "torso_visible": _as_bool(item.get("torso_visible"), default=False),
            "lighting": str(item.get("lighting", parsed.get("lighting", "unknown"))),
            "clothing": str(item.get("clothing", "unknown")),
            "occlusion": str(item.get("occlusion", "none")),
            "camera_level": str(item.get("camera_level", "unknown")),
            "issues": normalized_issues,
        }
    return normalized


def assess_photo_quality(
    parsed: dict[str, Any],
    uploaded_views: list[str],
    model_confidence: float,
) -> dict[str, Any]:
    views = normalize_view_quality(parsed, uploaded_views)
    usable_views = [
        view
        for view, quality in views.items()
        if quality["usable"]
        and quality["correct_view"]
        and quality["torso_visible"]
        and quality["lighting"].lower() not in {"poor", "bad", "dark"}
        and quality["occlusion"].lower() not in {"heavy", "severe"}
    ]
    reasons: list[str] = []
    if not _as_bool(parsed.get("is_usable"), default=False):
        reasons.append("模型判定当前照片不足以进行可靠估算")
    if not usable_views:
        reasons.append("没有检测到视角正确、躯干清晰且光线合格的照片")
    if model_confidence < 0.4:
        reasons.append("照片证据的模型置信度低于 40%")

    retake: list[str] = []
    if reasons:
        retake.extend([
            "使用贴身但不压缩身体轮廓的衣物，完整露出躯干和四肢",
            "相机与腰部大致同高，保持自然站立，不收腹或刻意摆姿势",
            "使用均匀正面光线，避免逆光、镜面畸变和身体遮挡",
        ])
    return {
        "is_usable": not reasons,
        "usable_views": usable_views,
        "views": views,
        "rejection_reasons": reasons,
        "retake_guidance": retake,
    }


def fuse_body_fat_estimate(
    *,
    gender: str,
    height_cm: float,
    vision_low: float,
    vision_high: float,
    vision_confidence: float,
    measurements: dict[str, float],
    usable_view_count: int,
) -> dict[str, Any]:
    vision_mid = (vision_low + vision_high) / 2
    vision_weight = max(0.25, min(0.65, vision_confidence * 0.7))
    sources: list[dict[str, Any]] = [{
        "key": "vision",
        "label": "照片视觉估算",
        "value": round(vision_mid, 1),
        "weight": round(vision_weight, 2),
    }]

    scale = measurements.get("body_fat_scale_pct")
    if scale is not None:
        sources.append({"key": "scale", "label": "体脂秤读数", "value": scale, "weight": 0.35})

    navy = navy_body_fat(
        gender,
        height_cm,
        measurements.get("waist_cm"),
        measurements.get("hip_cm"),
        measurements.get("neck_cm"),
    )
    if navy is not None:
        sources.append({"key": "circumference", "label": "围度公式估算", "value": navy, "weight": 0.45})

    total_weight = sum(item["weight"] for item in sources)
    center = sum(item["value"] * item["weight"] for item in sources) / total_weight
    disagreement = math.sqrt(
        sum(item["weight"] * (item["value"] - center) ** 2 for item in sources) / total_weight
    )
    vision_half_width = max(1.5, (vision_high - vision_low) / 2)
    source_bonus = 0.07 * (len(sources) - 1)
    view_bonus = 0.05 if usable_view_count >= 3 else 0.02 if usable_view_count >= 2 else 0
    confidence = vision_confidence + source_bonus + view_bonus - min(0.18, disagreement * 0.025)
    confidence = round(max(0.3, min(confidence, 0.92)), 2)

    half_width = max(1.5, min(6.0, max(vision_half_width * 0.75, disagreement + 1.2)))
    lower_bound, upper_bound = (5.0, 45.0) if gender == "male" else (12.0, 52.0)
    low = round(max(lower_bound, center - half_width), 1)
    high = round(min(upper_bound, center + half_width), 1)
    if high - low < 3:
        high = round(min(upper_bound, low + 3), 1)

    metrics: dict[str, float] = {}
    waist = measurements.get("waist_cm")
    hip = measurements.get("hip_cm")
    if waist and height_cm:
        metrics["waist_to_height_ratio"] = round(waist / height_cm, 3)
    if waist and hip:
        metrics["waist_to_hip_ratio"] = round(waist / hip, 3)

    return {
        "body_fat_estimate": round(center, 1),
        "body_fat_low": low,
        "body_fat_high": high,
        "body_fat_range": f"{low}%-{high}%",
        "confidence": confidence,
        "estimate_sources": sources,
        "tracking_metrics": metrics,
    }


def select_comparable_views(
    current_metadata: dict[str, Any],
    previous_metadata: dict[str, Any],
    current_quality: dict[str, Any],
    previous_quality: dict[str, Any],
) -> list[str]:
    comparable: list[str] = []
    for view in ("front", "side", "back"):
        current = current_metadata.get(view)
        previous = previous_metadata.get(view)
        current_view = current_quality.get("views", {}).get(view, {})
        previous_view = previous_quality.get("views", {}).get(view, {})
        if not current or not previous:
            continue
        if not current_view.get("usable") or not previous_view.get("usable"):
            continue
        if not current_view.get("correct_view", True) or not previous_view.get("correct_view", True):
            continue
        current_ratio = float(current.get("aspect_ratio", 0))
        previous_ratio = float(previous.get("aspect_ratio", 0))
        if current_ratio and previous_ratio and abs(current_ratio - previous_ratio) <= 0.12:
            comparable.append(view)
    return comparable
