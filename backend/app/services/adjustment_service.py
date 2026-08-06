"""复盘驱动的热量目标调整计算（闭环核心）。

打卡体重趋势 → 与安全变化速率对比 → 生成热量调整草案。
草案仅作为建议随复盘返回；写入计划必须经过用户确认（人在回路）。
全部为确定性规则计算，不调用 LLM，数字可解释、可复现。
"""
from datetime import datetime

# 每周安全体重变化速率（占当前体重 %）
FAT_LOSS_SLOW_PCT = -0.25   # 减脂：慢于每周 -0.25% 视为进展不足
FAT_LOSS_FAST_PCT = -1.0    # 减脂：快于每周 -1% 有过快风险
MUSCLE_GAIN_SLOW_PCT = 0.1  # 增肌：慢于每周 +0.1% 视为进展不足
MUSCLE_GAIN_FAST_PCT = 0.5  # 增肌：快于每周 +0.5% 脂肪占比偏高

MIN_SPAN_DAYS = 10          # 趋势评估最少时间跨度
MIN_POINTS = 3              # 趋势评估最少称重次数
ADJUST_STEP_KCAL = 150      # 单次调整步长
SAFE_MIN_KCAL = 1200        # 热量目标安全下限
SAFE_MAX_KCAL = 5000

_BASIS = (
    "依据：减脂安全速率为每周减重 0.25%-1% 体重，增肌为每周增重 0.1%-0.5%，"
    "超出区间说明当前热量目标与实际消耗不匹配。"
)


def _weekly_change_pct(points: list[tuple[str, float]]) -> float | None:
    """每周体重变化百分比（负值=下降）。数据不足返回 None。

    points: (date, weight) 列表，按日期升序。
    """
    if len(points) < MIN_POINTS:
        return None
    first_date = datetime.strptime(points[0][0], "%Y-%m-%d").date()
    last_date = datetime.strptime(points[-1][0], "%Y-%m-%d").date()
    span_days = (last_date - first_date).days
    if span_days < MIN_SPAN_DAYS:
        return None
    first_w, last_w = points[0][1], points[-1][1]
    if first_w <= 0 or last_w <= 0:
        return None
    weeks = span_days / 7
    return (last_w - first_w) / first_w * 100 / weeks


def compute_calorie_adjustment(
    goal_type: str,
    weight_points: list[tuple[str, float]],
    current_target: int,
) -> dict | None:
    """根据体重趋势计算热量调整草案。无需调整或数据不足返回 None。"""
    if current_target <= 0:
        return None
    rate = _weekly_change_pct(weight_points)
    if rate is None:
        return None

    delta = 0
    reason = ""
    if goal_type == "muscle_gain":
        if rate < MUSCLE_GAIN_SLOW_PCT:
            delta = ADJUST_STEP_KCAL
            reason = (
                f"近期体重每周仅变化 {rate:+.2f}%，增重偏慢，"
                "建议小幅上调热量目标以保证盈余。"
            )
        elif rate > MUSCLE_GAIN_FAST_PCT:
            delta = -ADJUST_STEP_KCAL
            reason = (
                f"近期体重每周变化 {rate:+.2f}%，增重过快，"
                "脂肪增长占比可能偏高，建议小幅下调热量目标。"
            )
    else:
        if rate > FAT_LOSS_SLOW_PCT:
            delta = -ADJUST_STEP_KCAL
            reason = (
                f"近期体重每周仅变化 {rate:+.2f}%，下降偏慢或进入平台，"
                "建议小幅下调热量目标。"
            )
        elif rate < FAT_LOSS_FAST_PCT:
            delta = ADJUST_STEP_KCAL
            reason = (
                f"近期体重每周变化 {rate:+.2f}%，下降过快，"
                "有肌肉流失和代谢下降风险，建议小幅上调热量目标。"
            )

    if delta == 0:
        return None

    suggested = max(SAFE_MIN_KCAL, min(SAFE_MAX_KCAL, current_target + delta))
    if suggested == current_target:
        return None

    return {
        "current_target": current_target,
        "suggested_target": suggested,
        "delta_kcal": suggested - current_target,
        "weekly_change_pct": round(rate, 2),
        "reason": reason,
        "basis": _BASIS,
    }
