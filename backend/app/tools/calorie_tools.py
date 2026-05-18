def calc_bmr(gender: str, weight: float, height: float, age: int) -> float:
    """计算基础代谢率 (Mifflin-St Jeor 公式)"""
    if gender == "male":
        return 10 * weight + 6.25 * height - 5 * age + 5
    else:
        return 10 * weight + 6.25 * height - 5 * age - 161


def calc_daily_calorie(
    bmr: float,
    activity_level: str,
    deficit_percent: float = 0.2,
    goal_type: str = "fat_loss",
) -> dict:
    """计算每日推荐热量，根据目标类型分支"""
    activity_multipliers = {
        "low": 1.2,
        "medium": 1.55,
        "high": 1.725,
        "very_high": 1.9,
    }
    multiplier = activity_multipliers.get(activity_level, 1.55)
    tdee = bmr * multiplier

    if goal_type == "muscle_gain":
        # 增肌：TDEE 增加 5%-15%
        surplus_percent = 0.10  # 默认 10% 盈余
        target_calories = tdee * (1 + surplus_percent)
        strategy = "lean_bulk"
    else:
        # 减脂：TDEE 减少 10%-25%
        target_calories = tdee * (1 - deficit_percent)
        strategy = "calorie_deficit"

    # 安全下限
    safe_min = 1200
    if target_calories < safe_min:
        target_calories = safe_min

    return {
        "bmr": round(bmr),
        "tdee": round(tdee),
        "target_calories": round(target_calories),
        "deficit": round(tdee - target_calories),
        "goal_type": goal_type,
        "strategy": strategy,
    }


def calc_macros(target_calories: float, weight: float, activity_level: str, goal_type: str = "fat_loss") -> dict:
    """计算三大营养素分配，根据目标类型分支"""
    if goal_type == "muscle_gain":
        # 增肌：蛋白质 1.8-2.4g/kg，脂肪 20%-30%，碳水优先保障训练
        if activity_level in ("high", "very_high"):
            protein_per_kg = 2.2
        else:
            protein_per_kg = 1.8
        protein_g = round(weight * protein_per_kg)
        protein_cal = protein_g * 4

        # 脂肪占总热量 25%
        fat_cal = target_calories * 0.25
        fat_g = round(fat_cal / 9)

        # 碳水：剩余热量（优先保障训练表现）
        carb_cal = target_calories - protein_cal - fat_cal
        carb_g = round(carb_cal / 4)
    else:
        # 减脂：蛋白质 1.6-2.2g/kg，脂肪不低于 20%，碳水剩余
        if activity_level in ("high", "very_high"):
            protein_per_kg = 2.0
        else:
            protein_per_kg = 1.6
        protein_g = round(weight * protein_per_kg)
        protein_cal = protein_g * 4

        # 脂肪：不低于总热量的20%
        fat_cal = target_calories * 0.25
        fat_g = round(fat_cal / 9)

        # 碳水：剩余热量
        carb_cal = target_calories - protein_cal - fat_cal
        carb_g = round(carb_cal / 4)

    return {
        "protein_g": protein_g,
        "carbs_g": max(carb_g, 50),  # 碳水最低50g
        "fat_g": fat_g,
        "fiber_g": 25,
        "water_ml": round(weight * 35),
    }


def food_calorie_lookup(food_name: str) -> str:
    """查询食材热量（从RAG检索）"""
    from app.rag.retriever import retrieve_knowledge

    results = retrieve_knowledge(f"食材热量 {food_name}", k=2)
    if results:
        return "\n".join(results)
    return f"未找到 {food_name} 的热量信息"


def exercise_calorie_lookup(exercise_name: str) -> str:
    """查询运动消耗（从RAG检索）"""
    from app.rag.retriever import retrieve_knowledge

    results = retrieve_knowledge(f"运动消耗 {exercise_name}", k=2)
    if results:
        return "\n".join(results)
    return f"未找到 {exercise_name} 的消耗信息"
