import json
from typing import TypedDict, Any
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from app.core.config import get_settings
from app.tools.calorie_tools import calc_bmr, calc_daily_calorie, calc_macros
from app.core.database import async_session
from app.rag.retriever import get_retriever
from app.rag.models import GoalType, KnowledgeCategory, SearchQuery

settings = get_settings()


class AgentState(TypedDict):
    user_profile: dict
    profile_status: str            # "complete" or "incomplete"
    missing_fields: list[str]      # 缺失的字段列表
    field_warnings: list[str]      # 数据异常警告
    followup_questions: str        # 追问内容
    goal_type: str                 # "fat_loss" or "muscle_gain"
    bmr: float
    calorie_info: dict
    macros: dict
    food_knowledge: str
    exercise_knowledge: str
    diet_knowledge: str
    risk_knowledge: str            # 风险规则知识
    knowledge_citations: list[dict]  # RAG 引用来源
    meal_plan: str
    workout_plan: str
    risk_warnings: list[str]       # 风险校验结果
    workout_plan_json: str         # 结构化训练计划 JSON
    exercise_candidates: list[dict]  # 候选动作池
    summary: str


class ReviewState(TypedDict):
    user_profile: dict
    checkin_history: list[str]
    related_knowledge: str
    review_summary: str
    next_day_advice: str


def get_llm(max_tokens: int = 1500):
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        openai_api_key=settings.LLM_API_KEY,
        openai_api_base=settings.LLM_BASE_URL,
        temperature=0.7,
        request_timeout=120,
        max_retries=2,
        max_tokens=max_tokens,
    )


def parse_user_profile(state: AgentState) -> dict:
    """解析用户信息"""
    profile = state["user_profile"]
    return {"user_profile": profile}


def check_profile(state: AgentState) -> dict:
    """检查用户档案完整性，识别缺失字段和异常数据"""
    profile = state["user_profile"]
    missing = []
    warnings = []

    # 必填字段检查
    if not profile.get("gender"):
        missing.append("性别")
    if not profile.get("age") or profile["age"] <= 0:
        missing.append("年龄")
    if not profile.get("height") or profile["height"] <= 0:
        missing.append("身高")
    if not profile.get("weight") or profile["weight"] <= 0:
        missing.append("体重")
    if not profile.get("target_weight") or profile["target_weight"] <= 0:
        missing.append("目标体重")

    # 数据合理性检查
    age = profile.get("age", 0)
    if age > 0 and (age < 10 or age > 100):
        warnings.append(f"年龄 {age} 岁，请确认是否正确")

    weight = profile.get("weight", 0)
    target = profile.get("target_weight", 0)
    if weight > 0 and target > 0:
        diff = abs(weight - target)
        if diff < 1:
            warnings.append("当前体重与目标体重几乎相同，无需减重")
        elif diff > 30:
            warnings.append(f"需要减重 {diff:.1f}kg，建议分阶段设定目标")

    if weight > 0 and weight < 40:
        warnings.append(f"体重 {weight}kg 偏低，请确认")
    if weight > 200:
        warnings.append(f"体重 {weight}kg 偏高，请确认")

    # 选填但建议补充的字段（加入 warnings 而非 missing，不阻塞计划生成）
    if profile.get("body_fat_rate") is None:
        warnings.append("体脂率未填写，计划将基于 BMI 估算，补充后更精准")
    if not profile.get("activity_level"):
        missing.append("活动水平")
    if not profile.get("diet_preference"):
        missing.append("饮食偏好")

    status = "complete" if not missing else "incomplete"
    return {
        "profile_status": status,
        "missing_fields": missing,
        "field_warnings": warnings,
    }


def ask_followup(state: AgentState) -> dict:
    """生成追问问题，引导用户补充信息"""
    llm = get_llm(max_tokens=300)
    missing = state["missing_fields"]
    warnings = state["field_warnings"]
    profile = state["user_profile"]

    parts = []
    if missing:
        parts.append(f"还需要你补充以下信息：\n" + "\n".join(f"- {f}" for f in missing))
    if warnings:
        parts.append(f"以下数据需要你确认：\n" + "\n".join(f"- {w}" for w in warnings))

    raw_text = "\n\n".join(parts)

    prompt = f"""你是减脂教练。用户建档信息不完整，请用友好自然的语气引导用户补充。
以下是要补充/确认的内容：

{raw_text}

要求：
1. 语气像朋友提醒，不要太正式
2. 如果有数据异常，先说明原因再请用户确认
3. 把必填项放在前面，选填项放后面
4. 控制在100字以内"""

    response = llm.invoke([HumanMessage(content=prompt)])
    return {"followup_questions": response.content}


def retrieve_knowledge_node(state: AgentState) -> dict:
    """RAG 混合检索 — 每个业务域独立检索当前任务所需知识"""
    profile = state["user_profile"]
    goal = profile.get("goal_type", "fat_loss")
    goal_enum = GoalType.muscle_gain if goal == "muscle_gain" else GoalType.fat_loss
    injuries = profile.get("injuries", [])

    retriever = get_retriever()

    # 1) 饮食/食材知识 → nutrition_planning + chinese_meals
    food_sq = SearchQuery(
        query=f"食材热量 蛋白质 {profile.get('diet_preference', '')}",
        goal_type=goal_enum,
        injuries=injuries,
        categories=[KnowledgeCategory.nutrition_planning, KnowledgeCategory.chinese_meals],
        top_k=3,
    )
    food_result = retriever.search(food_sq)
    food_knowledge = "\n".join(d.content for d in food_result.documents)

    # 2) 运动知识 → exercise_technique + training_principles
    exercise_sq = SearchQuery(
        query=f"运动训练 动作技术 {profile.get('activity_level', '')}",
        goal_type=goal_enum,
        injuries=injuries,
        categories=[KnowledgeCategory.exercise_technique, KnowledgeCategory.training_principles],
        top_k=3,
    )
    exercise_result = retriever.search(exercise_sq)
    exercise_knowledge = "\n".join(d.content for d in exercise_result.documents)

    # 3) 核心原则知识 → fat_loss_standards 或 muscle_gain_standards
    diet_cats = (
        [KnowledgeCategory.muscle_gain_standards]
        if goal == "muscle_gain"
        else [KnowledgeCategory.fat_loss_standards]
    )
    diet_query_text = "增肌热量盈余 蛋白质摄入" if goal == "muscle_gain" else "减脂热量缺口 高蛋白"
    diet_sq = SearchQuery(
        query=diet_query_text,
        goal_type=goal_enum,
        categories=diet_cats,
        top_k=3,
    )
    diet_result = retriever.search(diet_sq)
    diet_knowledge = "\n".join(d.content for d in diet_result.documents)

    # 4) 风险知识 → risk_rules，结合伤病和过敏
    risk_parts = ["健康风险 规则"]
    if injuries:
        risk_parts.append(" ".join(injuries) + " 伤病 禁忌动作")
    if profile.get("allergies"):
        risk_parts.append(" ".join(profile["allergies"]) + " 过敏 替代")
    risk_sq = SearchQuery(
        query=" ".join(risk_parts),
        injuries=injuries,
        categories=[KnowledgeCategory.risk_rules],
        top_k=4,
    )
    risk_result = retriever.search(risk_sq)
    risk_knowledge = "\n".join(d.content for d in risk_result.documents)

    # 收集引用来源（去重）
    seen_ids = set()
    citations = []
    for result in [food_result, exercise_result, diet_result, risk_result]:
        for d in result.documents:
            if d.chunk_id not in seen_ids:
                seen_ids.add(d.chunk_id)
                citations.append({
                    "chunk_id": d.chunk_id,
                    "title": d.title,
                    "category": d.category,
                    "source_name": d.source_name,
                    "source_url": d.source_url,
                    "evidence_level": d.evidence_level,
                    "score": d.score,
                })

    return {
        "food_knowledge": food_knowledge[:600],
        "exercise_knowledge": exercise_knowledge[:600],
        "diet_knowledge": diet_knowledge[:400],
        "risk_knowledge": risk_knowledge[:600],
        "knowledge_citations": citations,
    }


def calc_calorie_node(state: AgentState) -> dict:
    """计算热量目标，根据目标类型分支"""
    profile = state["user_profile"]
    goal_type = profile.get("goal_type", "fat_loss")

    bmr = calc_bmr(
        gender=profile["gender"],
        weight=profile["weight"],
        height=profile["height"],
        age=profile["age"],
    )

    calorie_info = calc_daily_calorie(
        bmr=bmr,
        activity_level=profile.get("activity_level", "medium"),
        goal_type=goal_type,
    )

    macros = calc_macros(
        target_calories=calorie_info["target_calories"],
        weight=profile["weight"],
        activity_level=profile.get("activity_level", "medium"),
        goal_type=goal_type,
    )

    return {
        "goal_type": goal_type,
        "bmr": bmr,
        "calorie_info": calorie_info,
        "macros": macros,
    }


def generate_meal_plan(state: AgentState) -> dict:
    """Generate structured meal plan from food candidates with nutrition verification.

    LLM arranges meals using real per-100g nutrition data from the food database.
    Backend verifies portion_g * per_100g / 100 against daily macro targets.
    """
    llm = get_llm(max_tokens=2000)
    profile = state["user_profile"]
    macros = state["macros"]
    calorie_info = state["calorie_info"]
    goal_type = state.get("goal_type", "fat_loss")
    food_candidates = state.get("food_candidates", [])

    forbidden = ", ".join(profile.get("forbidden_foods", [])) or "none"
    preference = profile.get("diet_preference", "balanced")
    scenario_map = {
        "home_cooking": "home cooking",
        "takeout": "takeout/delivery",
        "canteen": "canteen/cafeteria",
        "convenience_store": "convenience store",
    }
    scenario = scenario_map.get(profile.get("meal_scenario", "home_cooking"), "home cooking")
    prep_time = profile.get("prep_time_limit_minutes", 30)

    # Build candidate pool text with per-100g nutrition
    pool_lines = []
    for f in food_candidates:
        pool_lines.append(
            f"[{f['id']}] {f['name']} ({f['category']}) "
            f"per100g: {f['calories_kcal']}kcal P{f['protein_g']}g C{f['carbs_g']}g F{f['fat_g']}g "
            f"default_portion: {f['default_portion_g']}g ({f['default_portion_name']})"
        )
    pool_text = "\n".join(pool_lines) if pool_lines else "(empty pool, recommend basic foods)"

    target_p = macros.get("protein_g", 150)
    target_c = macros.get("carbs_g", 180)
    target_f = macros.get("fat_g", 55)
    target_kcal = calorie_info.get("target_calories", 1850)

    if goal_type == "muscle_gain":
        goal_desc = "muscle gain: ensure protein and training-day carbs, add snacks between meals"
    else:
        goal_desc = "fat loss: high protein for muscle retention, control oil and sugar, high fiber"

    prompt = f"""You are a nutritionist. Using the candidate food pool (with per-100g nutrition data), create a 1-day meal plan with exact gram portions that matches the user daily macro targets.

User: {profile.get('gender','')}, {profile.get('age','')}yo, {profile.get('weight','')}kg -> target {profile.get('target_weight','')}kg
Goal: {goal_type}
Diet preference: {preference}
Forbidden/allergies: {forbidden}
Scenario: {scenario}, prep time limit: {prep_time}min

Daily targets (MUST match within +/-15%):
- Calories: {target_kcal} kcal
- Protein: {target_p}g
- Carbs: {target_c}g
- Fat: {target_f}g

Strategy: {goal_desc}

Candidate food pool (select food_id from this list, use per-100g data to calculate portions):
{pool_text}

Output strict JSON only (no markdown, no extra text):
{{
  "meals": [
    {{
      "meal_type": "breakfast",
      "items": [
        {{"food_id": 20, "name": "oats", "portion_g": 40, "calories": 151, "protein_g": 5.2, "carbs_g": 26.8, "fat_g": 2.7}}
      ],
      "meal_total": {{"calories": 300, "protein_g": 20, "carbs_g": 35, "fat_g": 8}}
    }},
    {{
      "meal_type": "lunch",
      "items": [],
      "meal_total": {{"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}}
    }},
    {{
      "meal_type": "dinner",
      "items": [],
      "meal_total": {{"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}}
    }}
  ],
  "daily_total": {{"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}},
  "target_match": {{"protein_pct": 0, "carbs_pct": 0, "fat_pct": 0, "calories_pct": 0}},
  "snack_suggestion": "optional snack if needed",
  "tips": ["tip1", "tip2"]
}}

Rules:
1. Select food_id ONLY from the candidate pool
2. For each item, calculate nutrition = per_100g_value * portion_g / 100
3. Each meal should have 2-4 items
4. Sum all meals to get daily_total
5. target_match = daily_total / target * 100 for each macro
6. Aim for target_match between 85-115 for each macro
7. If pool is empty, recommend basic foods with food_id 0
8. Include a snack if user goal is muscle_gain or if calorie target is high
"""

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        raw = response.content.strip()
        json_start = raw.find("{")
        json_end = raw.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            raw = raw[json_start:json_end]
        plan_data = json.loads(raw)

        # Backend verification: recalculate nutrition from food data
        valid_foods = {f["id"]: f for f in food_candidates}
        for meal in plan_data.get("meals", []):
            for item in meal.get("items", []):
                fid = item.get("food_id")
                portion = item.get("portion_g", 0)
                if fid in valid_foods and portion > 0:
                    food = valid_foods[fid]
                    item["calories"] = round(food["calories_kcal"] * portion / 100, 1)
                    item["protein_g"] = round(food["protein_g"] * portion / 100, 1)
                    item["carbs_g"] = round(food["carbs_g"] * portion / 100, 1)
                    item["fat_g"] = round(food["fat_g"] * portion / 100, 1)
                    item["is_from_database"] = True
                else:
                    item["is_from_database"] = False

            # Recalculate meal totals
            mt = {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}
            for item in meal.get("items", []):
                mt["calories"] += item.get("calories", 0)
                mt["protein_g"] += item.get("protein_g", 0)
                mt["carbs_g"] += item.get("carbs_g", 0)
                mt["fat_g"] += item.get("fat_g", 0)
            meal["meal_total"] = {k: round(v, 1) for k, v in mt.items()}

        # Recalculate daily total
        dt = {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}
        for meal in plan_data.get("meals", []):
            mt = meal.get("meal_total", {})
            dt["calories"] += mt.get("calories", 0)
            dt["protein_g"] += mt.get("protein_g", 0)
            dt["carbs_g"] += mt.get("carbs_g", 0)
            dt["fat_g"] += mt.get("fat_g", 0)
        plan_data["daily_total"] = {k: round(v, 1) for k, v in dt.items()}

        # Recalculate target match
        tm = {}
        tm["protein_pct"] = round(dt["protein_g"] / target_p * 100, 1) if target_p else 0
        tm["carbs_pct"] = round(dt["carbs_g"] / target_c * 100, 1) if target_c else 0
        tm["fat_pct"] = round(dt["fat_g"] / target_f * 100, 1) if target_f else 0
        tm["calories_pct"] = round(dt["calories"] / target_kcal * 100, 1) if target_kcal else 0
        plan_data["target_match"] = tm

    except Exception:
        plan_data = {
            "meals": [],
            "daily_total": {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0},
            "target_match": {},
            "snack_suggestion": "",
            "tips": ["meal plan generation error, please retry"],
        }

    meal_plan_json = json.dumps(plan_data, ensure_ascii=False)

    # Generate text fallback
    text_lines = []
    for meal in plan_data.get("meals", []):
        items_text = ", ".join(
            f"{i.get('name','?')} {i.get('portion_g',0)}g" for i in meal.get("items", [])
        )
        mt = meal.get("meal_total", {})
        text_lines.append(
            f"**{meal.get('meal_type','')}** {items_text} "
            f"({mt.get('calories',0)}kcal P{mt.get('protein_g',0)}g C{mt.get('carbs_g',0)}g F{mt.get('fat_g',0)}g)"
        )
    dt = plan_data.get("daily_total", {})
    tm = plan_data.get("target_match", {})
    text_lines.append(
        f"\n**Daily Total**: {dt.get('calories',0)}kcal "
        f"P{dt.get('protein_g',0)}g C{dt.get('carbs_g',0)}g F{dt.get('fat_g',0)}g"
    )
    text_lines.append(
        f"**Target Match**: Protein {tm.get('protein_pct',0)}% "
        f"Carbs {tm.get('carbs_pct',0)}% Fat {tm.get('fat_pct',0)}%"
    )
    meal_plan_text = "\n".join(text_lines) if text_lines else "meal plan generation failed"

    return {
        "meal_plan": meal_plan_text,
        "meal_plan_json": meal_plan_json,
    }



def generate_workout_plan(state: AgentState) -> dict:
    """Generate structured workout plan from exercise candidates.

    LLM filters unsafe exercises for user injuries and编排 weekly plan.
    Outputs workout_plan_json (structured) + workout_plan (text fallback).
    """
    llm = get_llm(max_tokens=2000)
    profile = state["user_profile"]
    calorie_info = state["calorie_info"]
    goal_type = state.get("goal_type", "fat_loss")
    candidates = state.get("exercise_candidates", [])

    training_days = profile.get("training_days_per_week", 3)
    session_duration = profile.get("session_duration_minutes", 60)
    location = profile.get("training_location", "gym")
    experience = profile.get("training_experience", "beginner")
    injuries = profile.get("injuries", [])
    injuries_text = ", ".join(injuries) if injuries else "none"

    pool_lines = []
    for ex in candidates:
        pool_lines.append(
            f"[{ex['id']}] {ex['name']} "
            f"(body_part:{ex['body_part']}, equipment:{ex['equipment']}, target:{ex.get('target', '')})"
        )
    pool_text = "\n".join(pool_lines) if pool_lines else "(empty pool, recommend basic exercises)"

    if goal_type == "muscle_gain":
        goal_desc = "muscle gain: hypertrophy focus, split by chest/back/legs/shoulders/arms, 12-20 sets per muscle group per week, progressive overload, cardio 1-2x 20-30min"
    else:
        goal_desc = "fat loss: strength for muscle retention (moderate) + cardio for expenditure (3-4x 30-40min), control total volume"

    prompt = f"""You are a fitness coach. From the candidate exercise pool, exclude unsafe exercises for the user injuries, then arrange a weekly training plan.

User: {profile.get('gender','')}, {profile.get('age','')}yo, {profile.get('weight','')}kg -> target {profile.get('target_weight','')}kg
Goal: {goal_type}
Training: {training_days} days/week, {session_duration} min/session, location={location}, experience={experience}
Injuries: {injuries_text}
Daily calorie target: {calorie_info.get('target_calories', 0)} kcal

Strategy: {goal_desc}

Candidate exercise pool (only select exercise_id from this list):
{pool_text}

Output strict JSON only (no markdown, no extra text):
{{
  "excluded": [
    {{"exercise_id": "0043", "reason": "knee injury, squat increases knee load"}}
  ],
  "weekly_plan": [
    {{
      "day": 1,
      "theme": "chest+triceps",
      "duration_minutes": {session_duration},
      "exercises": [
        {{"exercise_id": "0025", "sets": 4, "reps": "8-12", "rest_seconds": 75}}
      ],
      "cardio": {{"type": "elliptical", "duration_minutes": 20, "intensity": "low-moderate"}}
    }}
  ],
  "warmup": ["5min dynamic warmup", "joint mobility"],
  "notes": ["control tempo", "ensure rest between sets"]
}}

Rules:
1. Only select exercise_id from the candidate pool, do not invent exercises or IDs
2. Exclude all exercises unsafe for user injuries, explain each reason
3. 4-6 exercises per day, fit within {session_duration} minutes
4. {training_days} training days, rest days have theme "rest"
5. If pool is empty, recommend 4-5 basic exercises with exercise_id "manual"
"""

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        raw = response.content.strip()
        json_start = raw.find("{{")
        json_end = raw.rfind("}}") + 2
        if json_start >= 0 and json_end > json_start:
            raw = raw[json_start:json_end]
        plan_data = json.loads(raw)
    except Exception:
        plan_data = {
            "excluded": [],
            "weekly_plan": [],
            "warmup": [],
            "notes": ["plan generation error, please retry"],
        }

    valid_ids = {ex["id"] for ex in candidates}
    for day in plan_data.get("weekly_plan", []):
        day["exercises"] = [
            ex for ex in day.get("exercises", [])
            if ex.get("exercise_id") in valid_ids or ex.get("exercise_id") == "manual"
        ]

    workout_plan_json = json.dumps(plan_data, ensure_ascii=False)

    text_lines = []
    for day in plan_data.get("weekly_plan", []):
        day_label = f"Day {day['day']}"
        if day.get("theme") == "rest":
            text_lines.append(f"**{day_label}** rest")
            continue
        ex_names = []
        for ex in day.get("exercises", []):
            ex_info = next((c for c in candidates if c["id"] == ex["exercise_id"]), None)
            name = ex_info["name"] if ex_info else ex.get("exercise_id", "?")
            ex_names.append(f"{name} {ex.get('sets','')}x{ex.get('reps','')}")
        cardio = day.get("cardio")
        cardio_text = f" / cardio: {cardio['type']} {cardio['duration_minutes']}min" if cardio else ""
        text_lines.append(f"**{day_label}** {day.get('theme','')}: {' / '.join(ex_names)}{cardio_text}")

    if plan_data.get("excluded"):
        text_lines.append("\nExcluded (injury safety):")
        for ex in plan_data["excluded"]:
            text_lines.append(f"- {ex['exercise_id']}: {ex['reason']}")

    workout_plan_text = "\n".join(text_lines) if text_lines else "plan generation failed, please retry"

    return {
        "workout_plan": workout_plan_text,
        "workout_plan_json": workout_plan_json,
    }


def risk_guardrail(state: AgentState) -> dict:
    """风险校验：检查生成的计划是否符合用户健康约束"""
    profile = state["user_profile"]
    calorie_info = state["calorie_info"]
    meal_plan = state["meal_plan"]
    workout_plan = state["workout_plan"]
    risk_knowledge = state["risk_knowledge"]
    goal_type = state.get("goal_type", "fat_loss")

    warnings = []

    # 1. 热量安全检查
    target = calorie_info.get("target_calories", 0)
    if goal_type == "fat_loss":
        if target < 1200:
            warnings.append(f"⚠️ 热量目标 {target}kcal 过低，女性不应低于 1200kcal，可能导致代谢下降")
        if target < 1500 and profile.get("gender") == "male":
            warnings.append(f"⚠️ 热量目标 {target}kcal 过低，男性不应低于 1500kcal")
    # 增肌不做低热量检查，但检查盈余是否过大
    if goal_type == "muscle_gain":
        tdee = calorie_info.get("tdee", 0)
        if tdee > 0 and target > tdee * 1.2:
            warnings.append(f"⚠️ 热量盈余偏大，建议控制在 TDEE 的 5%-15%，避免脂肪增长过快")

    # 2. 伤病禁忌检查
    injuries = profile.get("injuries", [])
    if injuries:
        injury_text = " ".join(injuries).lower()
        if "膝盖" in injury_text or "膝" in injury_text:
            warnings.append("⚠️ 检测到膝关节问题，运动计划应避免深蹲大重量、跳跃、跑步等高冲击动作")
        if "腰" in injury_text or "腰椎" in injury_text:
            warnings.append("⚠️ 检测到腰部问题，运动计划应避免硬拉大重量、仰卧起坐等弯腰负重动作")
        if "肩" in injury_text or "肩袖" in injury_text:
            warnings.append("⚠️ 检测到肩关节问题，运动计划应避免引体向上、过头推举等动作")

    # 3. 过敏食材检查
    allergies = profile.get("allergies", [])
    forbidden = profile.get("forbidden_foods", [])
    if allergies or forbidden:
        exclude_items = allergies + forbidden
        exclude_text = "、".join(exclude_items)
        # 用 LLM 检查饮食计划中是否包含过敏/忌口食材
        llm = get_llm(max_tokens=200)
        check_prompt = f"""检查以下饮食计划中是否包含用户不能吃的食材。

不能吃：{exclude_text}
饮食计划：{meal_plan[:600]}

如果包含，请列出具体的食材和对应菜品。如果没有问题，回复"无问题"。
简洁，50字以内。"""
        try:
            response = llm.invoke([HumanMessage(content=check_prompt)])
            if "无问题" not in response.content:
                warnings.append(f"⚠️ 饮食计划中可能包含过敏/忌口食材：{response.content}")
        except Exception:
            pass  # LLM 调用失败不阻塞

    # 4. 减重速度检查
    weight = profile.get("weight", 0)
    target_weight = profile.get("target_weight", 0)
    deficit = calorie_info.get("deficit", 0)
    if weight > 0 and target_weight > 0 and deficit > 0:
        # 每周减重 ≈ 热量缺口 * 7 / 7700（每kg脂肪约7700kcal）
        weekly_loss = deficit * 7 / 7700
        if weekly_loss > 1.0:
            warnings.append(f"⚠️ 预计每周减重 {weekly_loss:.1f}kg，超过安全范围（0.3-0.7kg），建议缩小热量缺口")

    # 5. 用 LLM 做最终风险审查（结合 RAG 知识）
    if risk_knowledge and (injuries or target < 1400):
        llm = get_llm(max_tokens=200)
        audit_prompt = f"""你是健康风险审查员。根据以下信息，判断计划是否存在健康风险。

用户：{profile.get('gender')}，{profile.get('age')}岁，{weight}kg
伤病：{", ".join(injuries) if injuries else "无"}
热量目标：{target}kcal
风险知识：{risk_knowledge[:400]}

如果存在风险，列出1-2条关键提醒。如果没有明显风险，回复"无额外风险"。
简洁，50字以内。"""
        try:
            response = llm.invoke([HumanMessage(content=audit_prompt)])
            if "无额外风险" not in response.content and response.content.strip():
                warnings.append(f"⚠️ {response.content.strip()}")
        except Exception:
            pass

    return {"risk_warnings": warnings}


def summarize_plan(state: AgentState) -> dict:
    """汇总输出（融合风险校验结果，根据目标类型分支）"""
    llm = get_llm(max_tokens=600)
    profile = state["user_profile"]
    calorie_info = state["calorie_info"]
    macros = state["macros"]
    risk_warnings = state.get("risk_warnings", [])
    goal_type = state.get("goal_type", "fat_loss")

    risk_section = ""
    if risk_warnings:
        risk_section = "\n风险校验发现的问题：\n" + "\n".join(risk_warnings)

    if goal_type == "muscle_gain":
        prompt = f"""你是健身教练。用户目标：{profile['weight']}kg→{profile['target_weight']}kg（增肌）。
每日：{calorie_info['target_calories']}kcal（盈余{abs(calorie_info['deficit'])}kcal），蛋白{macros['protein_g']}g，碳水{macros['carbs_g']}g，脂肪{macros['fat_g']}g。
{risk_section}

给出：1) 3条增肌核心执行建议 2) 风险提醒（2条，如有校验问题请融入）3) 预期增重速度 4) 一句鼓励。
不超过250字，简洁直接。"""
    else:
        prompt = f"""你是减脂教练。用户目标：{profile['weight']}kg→{profile['target_weight']}kg（减脂）。
每日：{calorie_info['target_calories']}kcal（缺口{calorie_info['deficit']}kcal），蛋白{macros['protein_g']}g，碳水{macros['carbs_g']}g，脂肪{macros['fat_g']}g。
{risk_section}

给出：1) 3条核心执行建议 2) 风险提醒（2条，如有校验问题请融入）3) 预期减重速度 4) 一句鼓励。
不超过250字，简洁直接。"""

    response = llm.invoke([HumanMessage(content=prompt)])
    return {"summary": response.content}


def _route_after_check(state: AgentState) -> str:
    """条件路由：档案完整则继续生成，否则走追问"""
    if state["profile_status"] == "complete":
        return "retrieve_knowledge"
    return "ask_followup"


def build_graph():
    """构建LangGraph工作流（含条件分支 + 风险校验）"""
    workflow = StateGraph(AgentState)

    workflow.add_node("parse_user_profile", parse_user_profile)
    workflow.add_node("check_profile", check_profile)
    workflow.add_node("ask_followup", ask_followup)
    workflow.add_node("retrieve_knowledge", retrieve_knowledge_node)
    workflow.add_node("calc_calorie", calc_calorie_node)
    workflow.add_node("generate_meal_plan", generate_meal_plan)
    workflow.add_node("generate_workout_plan", generate_workout_plan)
    workflow.add_node("risk_guardrail", risk_guardrail)
    workflow.add_node("summarize_plan", summarize_plan)

    workflow.set_entry_point("parse_user_profile")
    workflow.add_edge("parse_user_profile", "check_profile")
    workflow.add_conditional_edges(
        "check_profile",
        _route_after_check,
        {
            "retrieve_knowledge": "retrieve_knowledge",
            "ask_followup": "ask_followup",
        },
    )
    workflow.add_edge("ask_followup", END)
    workflow.add_edge("retrieve_knowledge", "calc_calorie")
    workflow.add_edge("calc_calorie", "generate_meal_plan")
    workflow.add_edge("generate_meal_plan", "generate_workout_plan")
    workflow.add_edge("generate_workout_plan", "risk_guardrail")
    workflow.add_edge("risk_guardrail", "summarize_plan")
    workflow.add_edge("summarize_plan", END)

    return workflow.compile()



async def _query_exercise_candidates(user_profile: dict) -> list[dict]:
    """Query exercise database for candidate pool based on user equipment, location, experience."""
    from app.models.user import Exercise
    from sqlalchemy import select

    equipment = user_profile.get("equipment", [])
    location = user_profile.get("training_location", "gym")
    experience = user_profile.get("training_experience", "beginner")

    # Infer default equipment if empty
    if not equipment:
        if location == "home":
            equipment = ["body weight", "dumbbell", "band"]
        elif location == "outdoor":
            equipment = ["body weight"]
        else:
            equipment = ["barbell", "dumbbell", "cable", "body weight", "leverage machine"]

    # Difficulty filter by experience
    if experience == "beginner":
        allowed_difficulty = ["beginner", "intermediate"]
    elif experience == "intermediate":
        allowed_difficulty = ["beginner", "intermediate", "advanced"]
    else:
        allowed_difficulty = ["beginner", "intermediate", "advanced"]

    async with async_session() as session:
        stmt = (
            select(Exercise)
            .where(Exercise.equipment.in_(equipment))
            .where(Exercise.difficulty.in_(allowed_difficulty))
            .order_by(Exercise.body_part, Exercise.id)
        )
        result = await session.execute(stmt)
        exercises = result.scalars().all()

    # Limit per body_part for diversity (max 8 per part)
    by_part: dict[str, list] = {}
    for ex in exercises:
        bp = ex.body_part
        if bp not in by_part:
            by_part[bp] = []
        if len(by_part[bp]) < 8:
            by_part[bp].append({
                "id": ex.id,
                "name": ex.name,
                "body_part": ex.body_part,
                "equipment": ex.equipment,
                "target": ex.target or "",
                "difficulty": ex.difficulty,
            })

    all_candidates = []
    for items in by_part.values():
        all_candidates.extend(items)
    return all_candidates




async def _query_food_candidates(user_profile: dict, macros: dict) -> list[dict]:
    """Query food database for candidate pool based on diet preference and allergies."""
    from app.models.user import Food
    from sqlalchemy import select, or_

    forbidden = user_profile.get("forbidden_foods", [])
    allergies = user_profile.get("allergies", [])
    exclude_keywords = forbidden + allergies

    async with async_session() as session:
        stmt = select(Food).order_by(Food.category, Food.id)
        result = await session.execute(stmt)
        foods = result.scalars().all()

    candidates = []
    for food in foods:
        # Filter out forbidden/allergy foods by name and aliases
        food_text = food.name_zh + " " + (food.aliases or "")
        if any(kw.lower() in food_text.lower() for kw in exclude_keywords if kw):
            continue
        candidates.append({
            "id": food.id,
            "name": food.name_zh,
            "category": food.category,
            "calories_kcal": food.calories_kcal,
            "protein_g": food.protein_g,
            "carbs_g": food.carbs_g,
            "fat_g": food.fat_g,
            "fiber_g": food.fiber_g,
            "default_portion_g": food.default_portion_g,
            "default_portion_name": food.default_portion_name,
        })
    return candidates


async def run_workflow(user_profile: dict) -> dict:
    """执行完整工作流。返回 dict 必含 status 字段：
    - status="plan"：计划生成成功
    - status="need_info"：需要用户补充信息
    """
    # Query exercise candidates before running graph
    exercise_candidates = await _query_exercise_candidates(user_profile)

    # Query food candidates (needs macros, so calculate first)
    from app.tools.calorie_tools import calc_bmr, calc_daily_calorie, calc_macros
    bmr = calc_bmr(
        gender=user_profile.get("gender", "male"),
        weight=user_profile.get("weight", 70),
        height=user_profile.get("height", 170),
        age=user_profile.get("age", 30),
    )
    calorie_info = calc_daily_calorie(
        bmr=bmr,
        activity_level=user_profile.get("activity_level", "medium"),
        goal_type=user_profile.get("goal_type", "fat_loss"),
    )
    macros = calc_macros(
        calorie_info["target_calories"],
        user_profile.get("weight", 70),
        user_profile.get("activity_level", "medium"),
        user_profile.get("goal_type", "fat_loss"),
    )
    food_candidates = await _query_food_candidates(user_profile, macros)

    graph = build_graph()

    initial_state: AgentState = {
        "user_profile": user_profile,
        "profile_status": "",
        "missing_fields": [],
        "field_warnings": [],
        "followup_questions": "",
        "goal_type": user_profile.get("goal_type", "fat_loss"),
        "bmr": 0,
        "calorie_info": {},
        "macros": {},
        "food_knowledge": "",
        "exercise_knowledge": "",
        "diet_knowledge": "",
        "risk_knowledge": "",
        "knowledge_citations": [],
        "meal_plan": "",
        "meal_plan_json": "",
        "workout_plan": "",
        "workout_plan_json": "",
        "exercise_candidates": exercise_candidates,
        "food_candidates": food_candidates,
        "risk_warnings": [],
        "summary": "",
    }

    result = await graph.ainvoke(initial_state)

    # 档案不完整，返回追问信息
    if result["profile_status"] == "incomplete":
        return {
            "status": "need_info",
            "missing_fields": result["missing_fields"],
            "field_warnings": result["field_warnings"],
            "followup_questions": result["followup_questions"],
        }

    # 计划生成成功
    return {
        "status": "plan",
        "calorie_info": result["calorie_info"],
        "macros": result["macros"],
        "meal_plan": result["meal_plan"],
        "meal_plan": result["meal_plan"],
        "meal_plan_json": result.get("meal_plan_json", ""),
        "workout_plan": result["workout_plan"],
        "workout_plan_json": result.get("workout_plan_json", ""),
        "summary": result["summary"],
        "knowledge_citations": result.get("knowledge_citations", []),
        "risk_warnings": result.get("risk_warnings", []),
    }


# ========== 第二版：复盘工作流 ==========


def review_retrieve_knowledge(state: ReviewState) -> dict:
    """复盘节点：检索相关知识（混合检索）"""
    history_text = "\n".join(state["checkin_history"])
    goal = state["user_profile"].get("goal_type", "fat_loss")
    goal_enum = GoalType.muscle_gain if goal == "muscle_gain" else GoalType.fat_loss
    injuries = state["user_profile"].get("injuries", [])

    if goal == "muscle_gain":
        query_text = f"增肌饮食调整 蛋白质摄入 力量训练恢复 {history_text[:200]}"
        cats = [KnowledgeCategory.muscle_gain_standards, KnowledgeCategory.training_principles]
    else:
        query_text = f"减脂饮食调整 平台期 运动恢复 {history_text[:200]}"
        cats = [KnowledgeCategory.fat_loss_standards, KnowledgeCategory.nutrition_planning]

    sq = SearchQuery(
        query=query_text,
        goal_type=goal_enum,
        injuries=injuries,
        categories=cats,
        top_k=4,
    )
    result = get_retriever().search(sq)
    knowledge = "\n".join(d.content for d in result.documents)

    return {"related_knowledge": knowledge}


def review_analyze_checkins(state: ReviewState) -> dict:
    """复盘节点：分析打卡记录并生成复盘总结，根据目标类型分支"""
    llm = get_llm(max_tokens=800)
    profile = state["user_profile"]
    history_text = "\n".join(state["checkin_history"])
    knowledge = state["related_knowledge"]
    checkin_count = len(state["checkin_history"])
    goal_type = profile.get("goal_type", "fat_loss")

    # 提取打卡中的体重数据
    weights = []
    for line in state["checkin_history"]:
        if "体重" in line:
            import re
            nums = re.findall(r"[\d.]+", line.split("体重")[-1][:20])
            if nums:
                weights.append(float(nums[0]))
    weight_info = ""
    if weights:
        weight_info = f"打卡体重记录：{', '.join(str(w) for w in weights)}kg"

    if goal_type == "muscle_gain":
        role = "增肌教练"
        focus_rules = """减脂/增肌关注点（增肌模式）：
- 体重增长速度是否合理（每周0.25-0.5kg）
- 热量盈余是否充足
- 蛋白质摄入是否达标（1.8-2.4g/kg）
- 力量训练执行情况和恢复状态
- 避免只关注体重，也要关注力量进步"""
    else:
        role = "减脂教练"
        focus_rules = """减脂/增肌关注点（减脂模式）：
- 体重下降速度是否合理（每周0.5-1kg）
- 热量缺口是否适当
- 饮食执行率
- 围度和体脂变化趋势"""

    prompt = f"""你是{role}。分析以下打卡记录。

【重要规则】
- 只能基于下方"打卡记录"中的实际数据分析，不要编造任何数据
- 打卡天数：{checkin_count} 天（数据量有限时请如实说明）
- 用户初始体重：{profile['weight']}kg，目标：{profile['target_weight']}kg
- {weight_info}
- 如果只有少量打卡记录，不要总结"体重趋势"，只分析已有数据
- 不要编造减重/增重成果，只说实际打卡中体现的内容
- {focus_rules}

打卡记录：
{history_text[:800]}

参考知识：{knowledge[:400]}

请分析：
1) 饮食执行情况（基于打卡中的饮食记录）
2) 运动执行情况（基于打卡中的运动记录）
3) 数据充足时才分析体重趋势，否则跳过
4) 做得好的地方
5) 需改进的地方
简洁，150-250字。"""

    response = llm.invoke([HumanMessage(content=prompt)])
    return {"review_summary": response.content}


def review_next_day_advice(state: ReviewState) -> dict:
    """复盘节点：生成次日调整建议，根据目标类型分支"""
    llm = get_llm(max_tokens=600)
    profile = state["user_profile"]
    checkin_count = len(state["checkin_history"])
    goal_type = profile.get("goal_type", "fat_loss")

    if goal_type == "muscle_gain":
        role = "增肌教练"
        advice_focus = """增肌调整重点：
1) 蛋白质摄入是否需要调整
2) 训练强度和容量是否合理
3) 碳水摄入是否保障训练表现
4) 恢复和睡眠情况"""
    else:
        role = "减脂教练"
        advice_focus = """减脂调整重点：
1) 热量缺口是否需要调整
2) 碳水是否需要调整
3) 有氧是否需要调整
4) 是否需要降低训练强度"""

    prompt = f"""你是{role}。用户目标{profile['weight']}kg→{profile['target_weight']}kg。
已打卡{checkin_count}天。

复盘摘要：
{state['review_summary'][:400]}

【重要规则】
- 建议必须基于复盘摘要中的实际数据，不要编造减重/增重成果
- 不要写"你已减掉/增加了Xkg"等未经验证的结论
- 如果打卡天数少，建议侧重于"建立习惯"而非"调整策略"
- 鼓励语要贴合实际（如"坚持打卡本身就是进步"），不要夸大

{advice_focus}

给出明日建议：1) 饮食调整 2) 运动建议 3) 注意事项 4) 鼓励
150-200字，直接可执行。"""

    response = llm.invoke([HumanMessage(content=prompt)])
    return {"next_day_advice": response.content}


def build_review_graph():
    """构建复盘工作流"""
    workflow = StateGraph(ReviewState)

    workflow.add_node("retrieve_knowledge", review_retrieve_knowledge)
    workflow.add_node("analyze_checkins", review_analyze_checkins)
    workflow.add_node("next_day_advice", review_next_day_advice)

    workflow.set_entry_point("retrieve_knowledge")
    workflow.add_edge("retrieve_knowledge", "analyze_checkins")
    workflow.add_edge("analyze_checkins", "next_day_advice")
    workflow.add_edge("next_day_advice", END)

    return workflow.compile()


async def run_review_workflow(
    user_profile: dict, checkin_history: list[str]
) -> dict:
    """执行复盘工作流"""
    graph = build_review_graph()

    initial_state: ReviewState = {
        "user_profile": user_profile,
        "checkin_history": checkin_history,
        "related_knowledge": "",
        "review_summary": "",
        "next_day_advice": "",
    }

    result = await graph.ainvoke(initial_state)

    return {
        "review_summary": result["review_summary"],
        "next_day_advice": result["next_day_advice"],
    }
