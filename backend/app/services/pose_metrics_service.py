"""Deterministic pose metrics computed from MediaPipe landmarks."""
from __future__ import annotations

import math
from statistics import mean, pstdev
from typing import Any


LANDMARKS = {
    "left_shoulder": 11,
    "right_shoulder": 12,
    "left_elbow": 13,
    "right_elbow": 14,
    "left_wrist": 15,
    "right_wrist": 16,
    "left_hip": 23,
    "right_hip": 24,
    "left_knee": 25,
    "right_knee": 26,
    "left_ankle": 27,
    "right_ankle": 28,
    "left_heel": 29,
    "right_heel": 30,
    "left_foot": 31,
    "right_foot": 32,
}

ANGLE_JOINTS = {
    "left_knee": ("left_hip", "left_knee", "left_ankle"),
    "right_knee": ("right_hip", "right_knee", "right_ankle"),
    "left_hip": ("left_shoulder", "left_hip", "left_knee"),
    "right_hip": ("right_shoulder", "right_hip", "right_knee"),
    "left_elbow": ("left_shoulder", "left_elbow", "left_wrist"),
    "right_elbow": ("right_shoulder", "right_elbow", "right_wrist"),
    "left_shoulder": ("left_elbow", "left_shoulder", "left_hip"),
    "right_shoulder": ("right_elbow", "right_shoulder", "right_hip"),
}

MOVEMENT_PRIMARY_JOINTS = {
    "squat": ("left_knee", "right_knee", "left_hip", "right_hip"),
    "deadlift": ("left_hip", "right_hip", "left_knee", "right_knee"),
    "lunge": ("left_knee", "right_knee", "left_hip", "right_hip"),
    "bench_press": ("left_elbow", "right_elbow", "left_shoulder", "right_shoulder"),
    "push_up": ("left_elbow", "right_elbow", "left_shoulder", "right_shoulder"),
    "pull_up": ("left_elbow", "right_elbow", "left_shoulder", "right_shoulder"),
    "overhead_press": ("left_elbow", "right_elbow", "left_shoulder", "right_shoulder"),
}


def _point(frame: dict[str, Any], name: str) -> dict[str, float] | None:
    landmarks = frame.get("landmarks")
    if not isinstance(landmarks, list):
        return None
    index = LANDMARKS[name]
    if index >= len(landmarks) or not isinstance(landmarks[index], dict):
        return None
    point = landmarks[index]
    try:
        return {
            "x": float(point["x"]),
            "y": float(point["y"]),
            "z": float(point.get("z", 0)),
            "visibility": float(point.get("visibility", 0)),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _angle(a: dict[str, float], b: dict[str, float], c: dict[str, float]) -> float | None:
    if min(a["visibility"], b["visibility"], c["visibility"]) < 0.45:
        return None
    ba = (a["x"] - b["x"], a["y"] - b["y"], a["z"] - b["z"])
    bc = (c["x"] - b["x"], c["y"] - b["y"], c["z"] - b["z"])
    denominator = math.sqrt(sum(v * v for v in ba)) * math.sqrt(sum(v * v for v in bc))
    if denominator <= 1e-8:
        return None
    cosine = max(-1.0, min(1.0, sum(x * y for x, y in zip(ba, bc)) / denominator))
    return math.degrees(math.acos(cosine))


def _frame_angles(frame: dict[str, Any]) -> dict[str, float]:
    values: dict[str, float] = {}
    for joint, names in ANGLE_JOINTS.items():
        points = [_point(frame, name) for name in names]
        if any(point is None for point in points):
            continue
        angle = _angle(points[0], points[1], points[2])  # type: ignore[arg-type]
        if angle is not None:
            values[joint] = round(angle, 1)
    return values


def _series_stats(values: list[float]) -> dict[str, float]:
    return {
        "min": round(min(values), 1),
        "max": round(max(values), 1),
        "range": round(max(values) - min(values), 1),
        "mean": round(mean(values), 1),
    }


def _visibility_quality(frames: list[dict[str, Any]]) -> dict[str, Any]:
    required = list(LANDMARKS)
    frame_scores: list[float] = []
    edge_frames = 0
    for frame in frames:
        points = [point for name in required if (point := _point(frame, name))]
        if not points:
            frame_scores.append(0)
            continue
        visible = [point for point in points if point["visibility"] >= 0.5]
        frame_scores.append(len(visible) / len(required))
        if visible:
            xs = [point["x"] for point in visible]
            ys = [point["y"] for point in visible]
            if min(xs) < 0.02 or max(xs) > 0.98 or min(ys) < 0.02 or max(ys) > 0.98:
                edge_frames += 1
    average_visibility = mean(frame_scores) if frame_scores else 0
    usable_ratio = sum(score >= 0.7 for score in frame_scores) / len(frame_scores) if frame_scores else 0
    issues: list[str] = []
    if average_visibility < 0.65:
        issues.append("关键关节存在较多遮挡或未入镜")
    if edge_frames > len(frames) * 0.3:
        issues.append("人物过于贴近画面边缘，可能发生裁切")
    if len(frames) < 6:
        issues.append("有效关键点帧较少，动态指标稳定性有限")
    confidence = max(0.0, min(0.95, average_visibility * 0.7 + usable_ratio * 0.3))
    return {
        "is_usable": average_visibility >= 0.55 and usable_ratio >= 0.4,
        "average_visibility": round(average_visibility, 3),
        "usable_frame_ratio": round(usable_ratio, 3),
        "edge_frame_ratio": round(edge_frames / len(frames), 3) if frames else 0,
        "issues": issues,
        "confidence": round(confidence, 2),
    }


def _trajectory_metrics(frames: list[dict[str, Any]]) -> dict[str, Any]:
    trajectory: list[tuple[float, float, float]] = []
    for index, frame in enumerate(frames):
        left = _point(frame, "left_hip")
        right = _point(frame, "right_hip")
        if not left or not right or min(left["visibility"], right["visibility"]) < 0.45:
            continue
        timestamp = float(frame.get("timestamp_ms", index * 100)) / 1000
        trajectory.append((timestamp, (left["x"] + right["x"]) / 2, (left["y"] + right["y"]) / 2))
    velocities: list[float] = []
    vertical: list[float] = []
    for previous, current in zip(trajectory, trajectory[1:]):
        dt = current[0] - previous[0]
        if dt <= 0:
            continue
        velocities.append(math.hypot(current[1] - previous[1], current[2] - previous[2]) / dt)
        vertical.append((current[2] - previous[2]) / dt)
    accelerations = [
        abs(current - previous)
        for previous, current in zip(velocities, velocities[1:])
    ]
    smoothness_score = 100
    if accelerations:
        smoothness_score = round(max(0, 100 - mean(accelerations) * 180))
    speed_cv = pstdev(velocities) / mean(velocities) if len(velocities) > 1 and mean(velocities) else 0
    speed_score = round(max(0, 100 - speed_cv * 70))

    direction_changes = 0
    previous_sign = 0
    for velocity in vertical:
        sign = 1 if velocity > 0.025 else -1 if velocity < -0.025 else 0
        if sign and previous_sign and sign != previous_sign:
            direction_changes += 1
        if sign:
            previous_sign = sign
    return {
        "smoothness_score": smoothness_score,
        "speed_control_score": speed_score,
        "mean_normalized_speed": round(mean(velocities), 3) if velocities else 0,
        "rep_count_estimate": max(0, direction_changes // 2),
    }


def compute_pose_metrics(payload: dict[str, Any], movement_key: str) -> dict[str, Any]:
    frames = payload.get("frames")
    frames = frames if isinstance(frames, list) else []
    frames = [frame for frame in frames[:120] if isinstance(frame, dict)]
    quality = _visibility_quality(frames)
    angle_frames = [_frame_angles(frame) for frame in frames]
    primary = MOVEMENT_PRIMARY_JOINTS.get(movement_key, tuple(ANGLE_JOINTS))

    joint_angles: dict[str, dict[str, float]] = {}
    for joint in primary:
        values = [angles[joint] for angles in angle_frames if joint in angles]
        if len(values) >= max(2, len(frames) // 3):
            joint_angles[joint] = _series_stats(values)

    symmetry_differences: list[float] = []
    for left_name, right_name in (
        ("left_knee", "right_knee"),
        ("left_hip", "right_hip"),
        ("left_elbow", "right_elbow"),
        ("left_shoulder", "right_shoulder"),
    ):
        if left_name not in primary and right_name not in primary:
            continue
        for angles in angle_frames:
            if left_name in angles and right_name in angles:
                symmetry_differences.append(abs(angles[left_name] - angles[right_name]))
    symmetry_difference = mean(symmetry_differences) if symmetry_differences else None
    symmetry_score = (
        round(max(0, 100 - symmetry_difference * 3))
        if symmetry_difference is not None
        else None
    )
    trajectory = _trajectory_metrics(frames)

    metrics: list[dict[str, Any]] = []
    ranges = [item["range"] for item in joint_angles.values()]
    if ranges:
        range_score = round(max(0, min(100, mean(ranges) * 1.4)))
        metrics.append({
            "name": "关节活动范围",
            "score": range_score,
            "description": f"主要关节平均角度变化 {mean(ranges):.1f}°",
            "source": "keypoints",
        })
    if symmetry_score is not None:
        metrics.append({
            "name": "左右对称性",
            "score": symmetry_score,
            "description": f"左右关节平均角度差 {symmetry_difference:.1f}°",
            "source": "keypoints",
        })
    metrics.extend([
        {
            "name": "轨迹平滑度",
            "score": trajectory["smoothness_score"],
            "description": "根据髋部中心轨迹的帧间变化计算",
            "source": "keypoints",
        },
        {
            "name": "速度控制",
            "score": trajectory["speed_control_score"],
            "description": f"归一化平均速度 {trajectory['mean_normalized_speed']}",
            "source": "keypoints",
        },
    ])

    return {
        "available": bool(frames and joint_angles),
        "model": str(payload.get("model", "mediapipe_pose_landmarker_lite")),
        "sampled_frames": len(frames),
        "duration_ms": int(payload.get("duration_ms", 0) or 0),
        "quality": quality,
        "joint_angles": joint_angles,
        "symmetry_difference_deg": round(symmetry_difference, 1) if symmetry_difference is not None else None,
        "trajectory": trajectory,
        "rep_count_estimate": trajectory["rep_count_estimate"],
        "metrics": metrics,
    }
