import json
import re
from datetime import date
from typing import TypedDict, Any
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from app.core.config import get_settings
from app.core.restrictions import canonical_injury_tags
from app.schemas.plan import WorkoutPlanData
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
    meal_plan_json: str            # 结构化饮食计划 JSON
    workout_plan: str
    risk_warnings: list[str]       # 风险校验结果
    workout_plan_json: str         # 结构化训练计划 JSON
    exercise_candidates: list[dict]  # 候选动作池
    food_candidates: list[dict]    # 候选食物池
    supplements_json: str          # 补剂推荐 JSON
    summary: str


class ReviewState(TypedDict):
    user_profile: dict
    checkin_history: list[str]
    related_knowledge: str
    review_summary: str
    next_day_advice: str
    workout_adjustment: dict | None   # 训练调整草案


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
        diet_preference=profile.get("diet_preference", "balanced"),
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
        return "react_agent"
    return "ask_followup"


# ========== ReAct Agent 工具 ==========


@tool
def calc_calorie_tool(
    gender: str,
    weight: float,
    height: float,
    age: int,
    activity_level: str,
    goal_type: str,
    diet_preference: str = "balanced",
) -> dict:
    """计算 BMR、TDEE、目标热量和三大营养素。返回包含 bmr/tdee/target_calories/deficit 和 macros 的字典。"""
    bmr = calc_bmr(gender=gender, weight=weight, height=height, age=age)
    calorie_info = calc_daily_calorie(
        bmr=bmr, activity_level=activity_level, goal_type=goal_type,
    )
    macros = calc_macros(
        calorie_info["target_calories"],
        weight,
        activity_level,
        goal_type,
        diet_preference,
    )
    return {"calorie_info": calorie_info, "macros": macros}


@tool
def search_exercises_tool(
    body_part: str,
    equipment: str,
    difficulty: str,
) -> list[dict]:
    """按部位、器械、难度搜索动作库。body_part 如 chest/back/upper legs；equipment 如 barbell/dumbbell/body weight；difficulty 如 beginner/intermediate。返回动作列表，每个含 id/name/body_part/equipment/target/difficulty。"""
    from app.models.user import Exercise
    from sqlalchemy import create_engine, select as sync_select
    from sqlalchemy.orm import Session as SyncSession
    from app.core.config import get_settings as _get_settings

    # 用同步引擎查询（tool 函数是同步的，不能用 async session）
    sync_url = _get_settings().DATABASE_URL.replace("+aiosqlite", "")
    sync_engine = create_engine(sync_url)

    with SyncSession(sync_engine) as session:
        stmt = sync_select(Exercise)
        if body_part:
            stmt = stmt.where(Exercise.body_part == body_part)
        if equipment:
            stmt = stmt.where(Exercise.equipment == equipment)
        if difficulty:
            stmt = stmt.where(Exercise.difficulty == difficulty)
        stmt = stmt.order_by(Exercise.body_part, Exercise.id).limit(20)
        result = session.execute(stmt)
        exercises = result.scalars().all()

    sync_engine.dispose()

    return [
        {
            "id": ex.id,
            "name": ex.name,
            "body_part": ex.body_part,
            "equipment": ex.equipment,
            "target": ex.target or "",
            "difficulty": ex.difficulty,
        }
        for ex in exercises
    ]


@tool
def search_foods_tool(
    category: str,
    diet_tags: str,
) -> list[dict]:
    """按分类和饮食标签搜索食物库。category 如 protein/carb/vegetable/fruit/fat/dairy/beverage；diet_tags 如 high_protein,low_carb（逗号分隔）。返回食物列表，每个含 id/name/category/calories_kcal/protein_g/carbs_g/fat_g/default_portion_g。"""
    from app.models.user import Food
    from sqlalchemy import create_engine, select as sync_select
    from sqlalchemy.orm import Session as SyncSession
    from app.core.config import get_settings as _get_settings

    sync_url = _get_settings().DATABASE_URL.replace("+aiosqlite", "")
    sync_engine = create_engine(sync_url)

    with SyncSession(sync_engine) as session:
        stmt = sync_select(Food)
        if category:
            stmt = stmt.where(Food.category == category)
        stmt = stmt.order_by(Food.id).limit(30)
        result = session.execute(stmt)
        foods = result.scalars().all()

    sync_engine.dispose()

    # Filter by diet_tags if provided
    tags = [t.strip() for t in diet_tags.split(",")] if diet_tags else []
    result_list = []
    for food in foods:
        food_tags = json.loads(food.diet_tags) if food.diet_tags else []
        if tags and not any(t in food_tags for t in tags):
            continue
        result_list.append({
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
    return result_list


@tool
def retrieve_knowledge_tool(
    query: str,
    categories: str,
) -> str:
    """检索专业知识库。query 为检索关键词；categories 为知识域（逗号分隔），可选值：fat_loss_standards/muscle_gain_standards/nutrition_planning/chinese_meals/training_principles/exercise_technique/risk_rules。返回相关知识文本。"""
    retriever = get_retriever()

    cat_list = []
    cat_map = {
        "fat_loss_standards": KnowledgeCategory.fat_loss_standards,
        "muscle_gain_standards": KnowledgeCategory.muscle_gain_standards,
        "nutrition_planning": KnowledgeCategory.nutrition_planning,
        "chinese_meals": KnowledgeCategory.chinese_meals,
        "training_principles": KnowledgeCategory.training_principles,
        "exercise_technique": KnowledgeCategory.exercise_technique,
        "risk_rules": KnowledgeCategory.risk_rules,
    }
    for c in (categories or "").split(","):
        c = c.strip()
        if c in cat_map:
            cat_list.append(cat_map[c])

    sq = SearchQuery(query=query, categories=cat_list if cat_list else None, top_k=3)
    result = retriever.search(sq)
    docs = "\n".join(d.content for d in result.documents)
    return docs if docs else "(no relevant knowledge found)"


# ========== ReAct Agent 节点 ==========


def _bounded_number(value: object, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean is not a numeric plan value")
    number = float(value)
    if not minimum <= number <= maximum:
        raise ValueError("numeric plan value is out of range")
    return number


_MAX_MEAL_ITEM_PORTION_G = 600.0
_MAX_DAILY_FOOD_WEIGHT_G = 3000.0
_MAX_ITEMS_PER_MEAL = 4
_FALLBACK_MEAL_TYPES = ("breakfast", "lunch", "dinner")


def _sanitize_agent_plan_output(
    plan_data: object,
    food_candidates: list[dict],
    exercise_candidates: list[dict],
    target_kcal: float,
    *,
    enforce_target: bool,
    target_macros: dict | None = None,
    training_constraints: dict | None = None,
) -> dict:
    """把 ReAct/降级模型输出收紧为候选池内的可计算计划。"""
    if not isinstance(plan_data, dict):
        raise ValueError("agent plan must be an object")
    raw_meal_plan = plan_data.get("meal_plan")
    raw_workout_plan = plan_data.get("workout_plan")
    if not isinstance(raw_meal_plan, dict) or not isinstance(raw_workout_plan, dict):
        raise ValueError("agent plan sections must be objects")

    valid_foods = {food["id"]: food for food in food_candidates}
    clean_meals = []
    raw_meals = raw_meal_plan.get("meals")
    if not isinstance(raw_meals, list) or not 1 <= len(raw_meals) <= 6:
        raise ValueError("meal plan must contain 1-6 meals")
    trusted_totals = {
        "calories": 0.0,
        "protein_g": 0.0,
        "carbs_g": 0.0,
        "fat_g": 0.0,
    }
    for raw_meal in raw_meals:
        if not isinstance(raw_meal, dict):
            continue
        meal_type = raw_meal.get("meal_type")
        if meal_type not in {"breakfast", "lunch", "dinner", "snack"}:
            continue
        raw_items = raw_meal.get("items")
        if not isinstance(raw_items, list):
            continue
        clean_items = []
        for raw_item in raw_items[:_MAX_ITEMS_PER_MEAL]:
            if not isinstance(raw_item, dict):
                continue
            food_id = raw_item.get("food_id")
            if isinstance(food_id, bool):
                continue
            try:
                food_id = int(food_id)
                portion_g = _bounded_number(
                    raw_item.get("portion_g"),
                    minimum=1,
                    maximum=_MAX_MEAL_ITEM_PORTION_G,
                )
            except (TypeError, ValueError, OverflowError):
                continue
            food = valid_foods.get(food_id)
            if not food:
                continue
            calories = round(food["calories_kcal"] * portion_g / 100, 1)
            protein_g = round(food["protein_g"] * portion_g / 100, 1)
            carbs_g = round(food["carbs_g"] * portion_g / 100, 1)
            fat_g = round(food["fat_g"] * portion_g / 100, 1)
            trusted_totals["calories"] += calories
            trusted_totals["protein_g"] += protein_g
            trusted_totals["carbs_g"] += carbs_g
            trusted_totals["fat_g"] += fat_g
            clean_items.append({
                "food_id": food_id,
                "name": food["name"],
                "portion_g": portion_g,
                "calories": calories,
                "protein_g": protein_g,
                "carbs_g": carbs_g,
                "fat_g": fat_g,
                "is_from_database": True,
            })
        if clean_items:
            clean_meals.append({"meal_type": meal_type, "items": clean_items})
    if not clean_meals:
        raise ValueError("agent meal plan has no trusted food items")
    daily_food_weight = sum(
        item["portion_g"]
        for meal in clean_meals
        for item in meal["items"]
    )
    if daily_food_weight > _MAX_DAILY_FOOD_WEIGHT_G:
        raise ValueError("agent meal food weight exceeds the executable daily limit")
    if enforce_target and target_kcal > 0 and not 0.85 <= trusted_totals["calories"] / target_kcal <= 1.15:
        raise ValueError("agent meal calories are outside the target tolerance")
    if enforce_target and target_macros:
        for nutrient in ("protein_g", "carbs_g", "fat_g"):
            target = float(target_macros.get(nutrient) or 0)
            if target > 0 and not 0.85 <= trusted_totals[nutrient] / target <= 1.15:
                raise ValueError(f"agent meal {nutrient.removesuffix('_g')} is outside the target tolerance")

    valid_exercise_ids = {exercise["id"] for exercise in exercise_candidates}
    raw_days = raw_workout_plan.get("weekly_plan")
    if not isinstance(raw_days, list) or not 1 <= len(raw_days) <= 7:
        raise ValueError("workout plan must contain 1-7 days")
    clean_days = []
    seen_days = set()
    for raw_day in raw_days:
        if not isinstance(raw_day, dict):
            continue
        try:
            day_number = int(raw_day.get("day"))
        except (TypeError, ValueError):
            continue
        theme = raw_day.get("theme")
        if not 1 <= day_number <= 7 or day_number in seen_days or not isinstance(theme, str) or not theme.strip():
            continue
        seen_days.add(day_number)
        is_rest = theme.strip().lower() in {"rest", "休息"}
        clean_duration = None
        raw_duration = raw_day.get("duration_minutes")
        if raw_duration is not None and not is_rest:
            try:
                clean_duration = int(_bounded_number(raw_duration, minimum=1, maximum=300))
            except (TypeError, ValueError, OverflowError):
                clean_duration = None
        clean_exercises = []
        raw_exercises = raw_day.get("exercises", [])
        if isinstance(raw_exercises, list) and not is_rest:
            for raw_exercise in raw_exercises[:12]:
                if not isinstance(raw_exercise, dict):
                    continue
                exercise_id = raw_exercise.get("exercise_id")
                if exercise_id not in valid_exercise_ids and not (
                    exercise_id == "manual" and not valid_exercise_ids
                ):
                    continue
                try:
                    sets = int(_bounded_number(raw_exercise.get("sets"), minimum=1, maximum=20))
                    rest_seconds = int(_bounded_number(raw_exercise.get("rest_seconds", 60), minimum=0, maximum=900))
                except (TypeError, ValueError, OverflowError):
                    continue
                reps = str(raw_exercise.get("reps", "")).strip()[:40]
                if not reps:
                    continue
                clean_exercises.append({
                    "exercise_id": exercise_id,
                    "sets": sets,
                    "reps": reps,
                    "rest_seconds": rest_seconds,
                })
        clean_cardio = None
        raw_cardio = raw_day.get("cardio")
        if isinstance(raw_cardio, dict) and not is_rest:
            cardio_type = raw_cardio.get("type")
            try:
                duration = int(_bounded_number(raw_cardio.get("duration_minutes"), minimum=1, maximum=300))
            except (TypeError, ValueError, OverflowError):
                duration = 0
            if isinstance(cardio_type, str) and cardio_type.strip() and duration:
                clean_cardio = {
                    "type": cardio_type.strip()[:100],
                    "duration_minutes": duration,
                    "intensity": str(raw_cardio.get("intensity", "moderate"))[:100],
                }
        if is_rest:
            clean_days.append({"day": day_number, "theme": "rest", "exercises": []})
        elif clean_exercises or clean_cardio:
            clean_day = {
                "day": day_number,
                "theme": theme.strip()[:100],
                "exercises": clean_exercises,
            }
            if clean_duration is not None:
                clean_day["duration_minutes"] = clean_duration
            if clean_cardio:
                clean_day["cardio"] = clean_cardio
            clean_days.append(clean_day)
    if not clean_days:
        raise ValueError("agent workout plan has no valid days")

    if training_constraints:
        requested_days = int(training_constraints.get("training_days_per_week") or 0)
        requested_duration = int(training_constraints.get("session_duration_minutes") or 0)
        training_days = [day for day in clean_days if day["theme"].lower() not in {"rest", "休息"}]
        if requested_days > 0 and len(training_days) != requested_days:
            raise ValueError("agent workout training days do not match the user constraint")
        for day in training_days:
            if not 4 <= len(day.get("exercises", [])) <= 6:
                raise ValueError("agent workout exercises per training day are outside the user constraint")
            duration = day.get("duration_minutes")
            if requested_duration > 0 and (
                duration is None
                or duration < max(1, int(requested_duration * 0.75))
                or duration > requested_duration
            ):
                raise ValueError("agent workout duration is outside the user constraint")

    clean_excluded = []
    raw_excluded = raw_workout_plan.get("excluded", [])
    if isinstance(raw_excluded, list):
        for item in raw_excluded[:100]:
            if not isinstance(item, dict):
                continue
            exercise_id = item.get("exercise_id")
            reason = item.get("reason")
            if exercise_id in valid_exercise_ids and isinstance(reason, str) and reason.strip():
                clean_excluded.append({"exercise_id": exercise_id, "reason": reason.strip()[:300]})

    clean_workout_plan = {
        "excluded": clean_excluded,
        "weekly_plan": clean_days,
        "warmup": [str(value)[:300] for value in raw_workout_plan.get("warmup", [])[:30]]
        if isinstance(raw_workout_plan.get("warmup"), list) else [],
        "notes": [str(value)[:300] for value in raw_workout_plan.get("notes", [])[:50]]
        if isinstance(raw_workout_plan.get("notes"), list) else [],
    }
    clean_workout_plan = WorkoutPlanData.model_validate(clean_workout_plan).model_dump(
        exclude_none=True,
        by_alias=True,
    )

    return {
        "meal_plan": {
            "meals": clean_meals,
            "snack_suggestion": str(raw_meal_plan.get("snack_suggestion", ""))[:300],
            "tips": [str(value)[:300] for value in raw_meal_plan.get("tips", [])[:20]]
            if isinstance(raw_meal_plan.get("tips"), list) else [],
        },
        "workout_plan": clean_workout_plan,
    }


def react_agent_node(state: AgentState) -> dict:
    """ReAct Agent 节点：LLM 自主调用工具生成饮食和训练计划。

    前置条件：档案已通过 check_profile 校验。
    后置条件：输出 meal_plan_json + workout_plan_json + meal_plan + workout_plan。
    """
    profile = state["user_profile"]
    goal_type = state.get("goal_type", "fat_loss")

    # 使用预查的候选池作为工具补充信息
    exercise_candidates = state.get("exercise_candidates", [])
    food_candidates = state.get("food_candidates", [])

    # 如果前置已经算好了热量和检索了知识，直接传入
    calorie_info = state.get("calorie_info", {})
    macros = state.get("macros", {})
    food_knowledge = state.get("food_knowledge", "")
    exercise_knowledge = state.get("exercise_knowledge", "")
    diet_knowledge = state.get("diet_knowledge", "")
    risk_knowledge = state.get("risk_knowledge", "")

    # 预查的候选池文本
    exercise_pool_lines = []
    for ex in exercise_candidates:
        exercise_pool_lines.append(
            f"[{ex['id']}] {ex['name']} "
            f"(body_part:{ex['body_part']}, equipment:{ex['equipment']}, target:{ex.get('target', '')})"
        )
    exercise_pool_text = "\n".join(exercise_pool_lines) if exercise_pool_lines else "(empty)"

    food_pool_lines = []
    for f in food_candidates:
        food_pool_lines.append(
            f"[{f['id']}] {f['name']} ({f['category']}) "
            f"per100g: {f['calories_kcal']}kcal P{f['protein_g']}g C{f['carbs_g']}g F{f['fat_g']}g "
            f"default_portion: {f['default_portion_g']}g"
        )
    food_pool_text = "\n".join(food_pool_lines) if food_pool_lines else "(empty)"

    # 构建系统提示
    forbidden = ", ".join(profile.get("forbidden_foods", [])) or "none"
    allergies = ", ".join(profile.get("allergies", [])) or "none"
    injuries = ", ".join(profile.get("injuries", [])) or "none"
    training_days = profile.get("training_days_per_week", 3)
    session_duration = profile.get("session_duration_minutes", 60)
    experience = profile.get("training_experience", "beginner")
    preference = profile.get("diet_preference", "balanced")

    scenario_map = {
        "home_cooking": "home cooking",
        "takeout": "takeout/delivery",
        "canteen": "canteen/cafeteria",
        "convenience_store": "convenience store",
    }
    scenario = scenario_map.get(profile.get("meal_scenario", "home_cooking"), "home cooking")
    prep_time = profile.get("prep_time_limit_minutes", 30)

    target_kcal = calorie_info.get("target_calories", 1850) if calorie_info else 1850
    target_p = macros.get("protein_g", 150) if macros else 150
    target_c = macros.get("carbs_g", 180) if macros else 180
    target_f = macros.get("fat_g", 55) if macros else 55

    if goal_type == "muscle_gain":
        goal_desc = "muscle gain: ensure protein and training-day carbs, add snacks, hypertrophy focus 12-20 sets per muscle group per week"
    else:
        goal_desc = "fat loss: high protein for muscle retention, control oil and sugar, high fiber, 3-4x cardio 30-40min"

    system_prompt = f"""You are a fitness and nutrition AI agent. Generate a 1-day meal plan and a weekly workout plan for the user.

User: {profile.get('gender','')}, {profile.get('age','')}yo, {profile.get('weight','')}kg -> target {profile.get('target_weight','')}kg
Goal: {goal_type}
Diet preference: {preference}
Forbidden/allergies: {forbidden} / {allergies}
Injuries: {injuries}
Training: {training_days} days/week, {session_duration} min/session, experience={experience}
Scenario: {scenario}, prep time limit: {prep_time}min

Daily targets (MUST match within +/-15%):
- Calories: {target_kcal} kcal
- Protein: {target_p}g
- Carbs: {target_c}g
- Fat: {target_f}g

Strategy: {goal_desc}

Pre-queried exercise candidate pool (select exercise_id ONLY from this list):
{exercise_pool_text}

Pre-queried food candidate pool (select food_id ONLY from this list, use per-100g data to calculate portions):
{food_pool_text}

Knowledge from RAG:
- Food/nutrition: {food_knowledge[:400]}
- Exercise/training: {exercise_knowledge[:400]}
- Goal standards: {diet_knowledge[:400]}
- Risk rules: {risk_knowledge[:400]}

You have tools available to search for more exercises, foods, or knowledge if the pre-queried pools are insufficient.

Output your final answer as strict JSON (no markdown, no extra text):
{{
  "meal_plan": {{
    "meals": [
      {{
        "meal_type": "breakfast",
        "items": [
          {{"food_id": 20, "name": "oats", "portion_g": 40, "calories": 151, "protein_g": 5.2, "carbs_g": 26.8, "fat_g": 2.7}}
        ],
        "meal_total": {{"calories": 300, "protein_g": 20, "carbs_g": 35, "fat_g": 8}}
      }}
    ],
    "daily_total": {{"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}},
    "target_match": {{"protein_pct": 0, "carbs_pct": 0, "fat_pct": 0, "calories_pct": 0}},
    "snack_suggestion": "optional snack",
    "tips": ["tip1", "tip2"]
  }},
  "workout_plan": {{
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
    "notes": ["control tempo", "ensure rest"]
  }}
}}

Rules:
1. Select food_id ONLY from the candidate pool, calculate nutrition = per_100g * portion_g / 100
2. Select exercise_id ONLY from the candidate pool, do not invent IDs
3. Exclude all exercises unsafe for user injuries, explain each reason
4. 4-6 exercises per training day, fit within {session_duration} minutes
5. {training_days} training days, rest days have theme "rest"
6. Each meal should have 2-4 food items
7. Sum all meals to get daily_total, target_match = daily_total / target * 100
8. If pools are empty, recommend basic items with id 0 or "manual"
"""

    tools = [calc_calorie_tool, search_exercises_tool, search_foods_tool, retrieve_knowledge_tool]

    react_agent = create_react_agent(
        model=get_llm(max_tokens=2500),
        tools=tools,
        prompt=system_prompt,
    )

    try:
        response = react_agent.invoke({
            "messages": [HumanMessage(content="Generate the meal plan and workout plan as specified. Output only the JSON.")],
        })

        # Extract the final message content
        final_content = response["messages"][-1].content.strip()

        # Parse JSON from response
        json_start = final_content.find("{")
        json_end = final_content.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            plan_data = json.loads(final_content[json_start:json_end])
        else:
            raise ValueError("No JSON found in ReAct agent response")

        plan_data = _sanitize_agent_plan_output(
            plan_data,
            food_candidates,
            exercise_candidates,
            target_kcal,
            enforce_target=True,
            target_macros=macros,
            training_constraints=profile,
        )

    except Exception:
        # 降级：用原有节点逻辑生成
        fallback = _fallback_generate(
            profile, state, exercise_candidates, food_candidates, calorie_info, macros, goal_type
        )
        fallback["workout_plan"] = _build_constraint_fallback_workout(
            exercise_candidates,
            profile.get("training_days_per_week", 3),
            profile.get("session_duration_minutes", 60),
        )
        try:
            plan_data = _sanitize_agent_plan_output(
                fallback,
                food_candidates,
                exercise_candidates,
                target_kcal,
                enforce_target=True,
                target_macros=macros,
                training_constraints=profile,
            )
        except (TypeError, ValueError):
            fallback["meal_plan"] = _build_constraint_fallback_meal(
                food_candidates, target_kcal, macros,
            )
            plan_data = _sanitize_agent_plan_output(
                fallback,
                food_candidates,
                exercise_candidates,
                target_kcal,
                enforce_target=True,
                target_macros=macros,
                training_constraints=profile,
            )

    # 提取和验证 meal_plan
    meal_plan_data = plan_data.get("meal_plan", {})

    # 后端验证：用数据库数据重算营养
    valid_foods = {f["id"]: f for f in food_candidates}
    for meal in meal_plan_data.get("meals", []):
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
    for meal in meal_plan_data.get("meals", []):
        mt = meal.get("meal_total", {})
        dt["calories"] += mt.get("calories", 0)
        dt["protein_g"] += mt.get("protein_g", 0)
        dt["carbs_g"] += mt.get("carbs_g", 0)
        dt["fat_g"] += mt.get("fat_g", 0)
    meal_plan_data["daily_total"] = {k: round(v, 1) for k, v in dt.items()}

    # Recalculate target match
    tm = {}
    tm["protein_pct"] = round(dt["protein_g"] / target_p * 100, 1) if target_p else 0
    tm["carbs_pct"] = round(dt["carbs_g"] / target_c * 100, 1) if target_c else 0
    tm["fat_pct"] = round(dt["fat_g"] / target_f * 100, 1) if target_f else 0
    tm["calories_pct"] = round(dt["calories"] / target_kcal * 100, 1) if target_kcal else 0
    meal_plan_data["target_match"] = tm

    meal_plan_json = json.dumps(meal_plan_data, ensure_ascii=False)

    # 生成饮食计划文本
    meal_text_lines = []
    for meal in meal_plan_data.get("meals", []):
        items_text = ", ".join(
            f"{i.get('name','?')} {i.get('portion_g',0)}g" for i in meal.get("items", [])
        )
        mt = meal.get("meal_total", {})
        meal_text_lines.append(
            f"**{meal.get('meal_type','')}** {items_text} "
            f"({mt.get('calories',0)}kcal P{mt.get('protein_g',0)}g C{mt.get('carbs_g',0)}g F{mt.get('fat_g',0)}g)"
        )
    meal_plan_text = "\n".join(meal_text_lines) if meal_text_lines else "meal plan generation failed"

    # 提取和验证 workout_plan
    workout_plan_data = plan_data.get("workout_plan", {})

    # 后端验证：过滤不存在的 exercise_id
    valid_ids = {ex["id"] for ex in exercise_candidates}
    for day in workout_plan_data.get("weekly_plan", []):
        day["exercises"] = [
            ex for ex in day.get("exercises", [])
            if ex.get("exercise_id") in valid_ids or ex.get("exercise_id") == "manual"
        ]

    workout_plan_json = json.dumps(workout_plan_data, ensure_ascii=False)

    # 生成训练计划文本
    workout_text_lines = []
    for day in workout_plan_data.get("weekly_plan", []):
        day_label = f"Day {day.get('day', '?')}"
        if day.get("theme") == "rest":
            workout_text_lines.append(f"**{day_label}** rest")
            continue
        ex_names = []
        for ex in day.get("exercises", []):
            ex_info = next((c for c in exercise_candidates if c["id"] == ex["exercise_id"]), None)
            name = ex_info["name"] if ex_info else ex.get("exercise_id", "?")
            ex_names.append(f"{name} {ex.get('sets','')}x{ex.get('reps','')}")
        cardio = day.get("cardio")
        cardio_text = f" / cardio: {cardio['type']} {cardio['duration_minutes']}min" if cardio else ""
        workout_text_lines.append(f"**{day_label}** {day.get('theme','')}: {' / '.join(ex_names)}{cardio_text}")

    if workout_plan_data.get("excluded"):
        workout_text_lines.append("\nExcluded (injury safety):")
        for ex in workout_plan_data["excluded"]:
            workout_text_lines.append(f"- {ex['exercise_id']}: {ex['reason']}")

    workout_plan_text = "\n".join(workout_text_lines) if workout_text_lines else "plan generation failed"

    return {
        "meal_plan": meal_plan_text,
        "meal_plan_json": meal_plan_json,
        "workout_plan": workout_plan_text,
        "workout_plan_json": workout_plan_json,
    }


def _fallback_generate(
    profile: dict,
    state: AgentState,
    exercise_candidates: list[dict],
    food_candidates: list[dict],
    calorie_info: dict,
    macros: dict,
    goal_type: str,
) -> dict:
    """ReAct Agent 失败时的降级生成：调用原有 generate_meal_plan + generate_workout_plan 逻辑。"""
    # 用原有节点函数生成
    meal_result = generate_meal_plan(state)
    workout_result = generate_workout_plan(state)

    # 从 meal_plan_json 和 workout_plan_json 提取数据
    try:
        meal_data = json.loads(meal_result["meal_plan_json"]) if meal_result.get("meal_plan_json") else {}
    except Exception:
        meal_data = {"meals": [], "daily_total": {}, "target_match": {}, "tips": []}

    try:
        workout_data = json.loads(workout_result["workout_plan_json"]) if workout_result.get("workout_plan_json") else {}
    except Exception:
        workout_data = {"excluded": [], "weekly_plan": [], "warmup": [], "notes": []}

    return {"meal_plan": meal_data, "workout_plan": workout_data}


def _build_constraint_fallback_workout(
    exercise_candidates: list[dict],
    training_days_per_week: object,
    session_duration_minutes: object,
) -> dict:
    """构造满足用户训练频次、动作数和时长边界的本地降级计划。"""
    try:
        training_days = max(1, min(7, int(training_days_per_week)))
    except (TypeError, ValueError):
        training_days = 3
    try:
        duration = max(1, min(300, int(session_duration_minutes)))
    except (TypeError, ValueError):
        duration = 60

    exercise_ids = [candidate["id"] for candidate in exercise_candidates if candidate.get("id")]
    if not exercise_ids:
        exercise_ids = ["manual"]

    weekly_plan = []
    for day in range(1, training_days + 1):
        exercises = [
            {
                "exercise_id": exercise_ids[((day - 1) * 4 + offset) % len(exercise_ids)],
                "sets": 3,
                "reps": "8-12",
                "rest_seconds": 60,
            }
            for offset in range(4)
        ]
        weekly_plan.append({
            "day": day,
            "theme": "full body",
            "duration_minutes": duration,
            "exercises": exercises,
        })
    return {
        "excluded": [],
        "weekly_plan": weekly_plan,
        "warmup": ["5min dynamic warmup"],
        "notes": ["local fallback plan"],
    }


def _build_constraint_fallback_meal(
    food_candidates: list[dict],
    target_kcal: object,
    target_macros: dict,
) -> dict:
    """用候选池营养数据拟合目标，作为模型输出不可用时的本地降级餐单。"""
    targets = (
        float(target_kcal or 0),
        float(target_macros.get("protein_g") or 0),
        float(target_macros.get("carbs_g") or 0),
        float(target_macros.get("fat_g") or 0),
    )
    if any(target <= 0 for target in targets):
        raise ValueError("无法在可执行份量边界内生成降级餐单：营养目标无效")

    usable = [
        food for food in food_candidates
        if food.get("id") is not None and float(food.get("calories_kcal") or 0) >= 10
    ]
    if not usable:
        raise ValueError("无法在可执行份量边界内生成降级餐单：没有可用候选食物")

    vectors = [
        (
            float(food.get("calories_kcal") or 0) / targets[0],
            float(food.get("protein_g") or 0) / targets[1],
            float(food.get("carbs_g") or 0) / targets[2],
            float(food.get("fat_g") or 0) / targets[3],
        )
        for food in usable
    ]

    max_daily_portion_units = len(_FALLBACK_MEAL_TYPES) * _MAX_MEAL_ITEM_PORTION_G / 100
    max_daily_weight_units = _MAX_DAILY_FOOD_WEIGHT_G / 100

    def solve(indices: list[int]) -> list[float]:
        portions = [0.0] * len(indices)
        current = [0.0] * 4
        total_portion = 0.0
        for sweep in range(400):
            order = range(len(indices)) if sweep % 2 == 0 else range(len(indices) - 1, -1, -1)
            for position in order:
                vector = vectors[indices[position]]
                denominator = sum(value * value for value in vector)
                if denominator <= 0:
                    continue
                delta = sum(
                    vector[index] * (1.0 - current[index])
                    for index in range(4)
                ) / denominator
                available_total = max_daily_weight_units - total_portion + portions[position]
                updated = max(
                    0.0,
                    min(max_daily_portion_units, available_total, portions[position] + delta),
                )
                applied = updated - portions[position]
                portions[position] = updated
                total_portion += applied
                for index in range(4):
                    current[index] += vector[index] * applied
        return portions

    all_indices = list(range(len(usable)))
    initial_portions = solve(all_indices)
    selected_indices = sorted(
        all_indices,
        key=lambda index: initial_portions[index]
        * sum(value * value for value in vectors[index]) ** 0.5,
        reverse=True,
    )[:8]
    selected_portions = solve(selected_indices)

    daily_items = [
        (index, round(portion * 100, 1))
        for index, portion in zip(selected_indices, selected_portions)
        if portion >= 0.01
    ]
    trusted_totals = [
        sum(
            vectors[index][nutrient_index] * portion_g / 100
            for index, portion_g in daily_items
        )
        for nutrient_index in range(4)
    ]
    if not daily_items or any(not 0.85 <= ratio <= 1.15 for ratio in trusted_totals):
        raise ValueError("无法在可执行份量边界内满足热量和三大宏量目标 ±15%")
    if sum(portion_g for _, portion_g in daily_items) > _MAX_DAILY_FOOD_WEIGHT_G:
        raise ValueError("无法在可执行份量边界内满足每日总食物重量限制")

    split_items = []
    for index, daily_portion_g in daily_items:
        remaining = daily_portion_g
        while remaining > 0:
            portion_g = min(_MAX_MEAL_ITEM_PORTION_G, remaining)
            split_items.append({"food_id": usable[index]["id"], "portion_g": round(portion_g, 1)})
            remaining = round(remaining - portion_g, 1)
    if len(split_items) == 1 and split_items[0]["portion_g"] >= 2:
        only_item = split_items[0]
        first_portion = round(only_item["portion_g"] / 2, 1)
        split_items = [
            {**only_item, "portion_g": first_portion},
            {**only_item, "portion_g": round(only_item["portion_g"] - first_portion, 1)},
        ]
    if len(split_items) > len(_FALLBACK_MEAL_TYPES) * _MAX_ITEMS_PER_MEAL:
        raise ValueError("无法在可执行份量边界内分配餐次和食物项目")

    meals = [
        {"meal_type": meal_type, "items": []}
        for meal_type in _FALLBACK_MEAL_TYPES
    ]
    for index, item in enumerate(split_items):
        meals[index % len(meals)]["items"].append(item)
    meals = [meal for meal in meals if meal["items"]]
    if len(meals) < 2:
        raise ValueError("无法在可执行份量边界内分配到多个餐次")
    return {
        "meals": meals,
        "tips": ["本地营养数据降级餐单，已按可执行份量分配到三餐。"],
    }


def build_graph():
    """构建LangGraph工作流（ReAct Agent + 条件分支 + 风险校验）

    流程：parse -> check -> [react_agent | ask_followup] -> risk_guardrail -> summarize
    """
    workflow = StateGraph(AgentState)

    workflow.add_node("parse_user_profile", parse_user_profile)
    workflow.add_node("check_profile", check_profile)
    workflow.add_node("ask_followup", ask_followup)
    workflow.add_node("retrieve_knowledge", retrieve_knowledge_node)
    workflow.add_node("calc_calorie", calc_calorie_node)
    workflow.add_node("react_agent", react_agent_node)
    workflow.add_node("risk_guardrail", risk_guardrail)
    workflow.add_node("summarize_plan", summarize_plan)

    workflow.set_entry_point("parse_user_profile")
    workflow.add_edge("parse_user_profile", "check_profile")
    workflow.add_conditional_edges(
        "check_profile",
        _route_after_check,
        {
            "react_agent": "retrieve_knowledge",
            "ask_followup": "ask_followup",
        },
    )
    workflow.add_edge("ask_followup", END)
    workflow.add_edge("retrieve_knowledge", "calc_calorie")
    workflow.add_edge("calc_calorie", "react_agent")
    workflow.add_edge("react_agent", "risk_guardrail")
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
    injuries = user_profile.get("injuries", [])

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
        if _exercise_conflicts_with_injuries(ex, injuries):
            continue
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


def _exercise_conflicts_with_injuries(exercise: object, injuries: list[str]) -> bool:
    """按动作名称做保守粗筛，LLM 仅在安全候选池内精筛。"""
    injury_tags = canonical_injury_tags(injuries)
    exercise_text = " ".join(
        str(getattr(exercise, field, "") or "").lower()
        for field in ("name", "name_zh", "body_part", "target")
    )
    rules = (
        ("knee", ("squat", "lunge", "jump", "run", "leg press", "深蹲", "弓步", "跳跃", "跑步", "腿举")),
        ("back", ("deadlift", "good morning", "sit-up", "hyperextension", "硬拉", "早安式", "仰卧起坐")),
        ("shoulder", ("overhead press", "military press", "bench press", "chest press", "pull-up", "推举", "卧推", "推胸", "引体向上")),
    )
    return any(
        injury_tag in injury_tags and any(keyword in exercise_text for keyword in unsafe_keywords)
        for injury_tag, unsafe_keywords in rules
    )




def _sort_food_candidates_for_preference(
    candidates: list[dict], diet_preference: str,
) -> list[dict]:
    """Order candidates so deterministic fallbacks can satisfy the chosen diet."""
    if diet_preference != "low_carb":
        return candidates

    category_rank = {"fat": 0, "protein": 1, "carb": 2}
    return sorted(
        candidates,
        key=lambda food: (
            category_rank.get(food.get("category"), 3),
            food.get("id", 0),
        ),
    )


async def _query_food_candidates(user_profile: dict, macros: dict) -> list[dict]:
    """Query food database for candidate pool based on diet preference and allergies."""
    from app.models.user import Food
    from sqlalchemy import select, or_

    forbidden = user_profile.get("forbidden_foods", [])
    allergies = user_profile.get("allergies", [])
    exclude_keywords = forbidden + allergies
    diet_preference = user_profile.get("diet_preference", "balanced")

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
        try:
            diet_tags = set(json.loads(food.diet_tags)) if food.diet_tags else set()
        except (TypeError, json.JSONDecodeError):
            diet_tags = set()
        if diet_preference == "high_protein" and diet_preference not in diet_tags:
            continue
        if diet_preference == "vegetarian":
            plant_categories = {"carb", "vegetable", "fruit", "fat", "beverage"}
            animal_keywords = (
                "肉", "鸡", "鸭", "鹅", "鱼", "虾", "蟹", "贝", "蛤", "蚝", "螺",
                "鱿", "章鱼", "蛋", "奶", "培根", "火腿", "血", "肝", "肚", "胗",
            )
            trusted_name = f"{food.name_zh} {food.aliases or ''}".lower()
            is_explicitly_vegetarian = "vegetarian" in diet_tags
            is_plant_category = food.category in plant_categories and not any(
                keyword in trusted_name for keyword in animal_keywords
            )
            if not (is_explicitly_vegetarian or is_plant_category):
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
            "diet_tags": sorted(diet_tags),
        })
    return _sort_food_candidates_for_preference(candidates, diet_preference)


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
        user_profile.get("diet_preference", "balanced"),
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
        "bmr": bmr,
        "calorie_info": calorie_info,
        "macros": macros,
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
        "supplements_json": "",
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


def review_workout_adjustment(state: ReviewState) -> dict:
    """复盘节点：根据打卡记录生成训练调整草案。

    触发条件：
    - 打卡中伤病关键词出现 -> 建议替换对应部位高冲击动作
    - 打卡中运动记录连续标注未完成/太累 -> 建议降低训练容量
    - 减脂平台期（体重2周无变化） -> 建议增加有氧
    - 增肌停滞（体重2周无变化） -> 建议增加训练容量
    """
    profile = state["user_profile"]
    checkin_history = state["checkin_history"]
    injuries = profile.get("injuries", [])
    goal_type = profile.get("goal_type", "fat_loss")

    changes = []
    reason_parts = []
    risk_notes = []

    # 1. 伤病关键词检测：档案伤病 + 打卡中带疼痛/受伤语境的部位描述。
    injury_rules = {
        "knee": ("膝盖", ["深蹲", "squat", "跳跃", "jump", "跑步", "run"]),
        "back": ("腰", ["硬拉", "deadlift", "仰卧起坐", "sit-up"]),
        "shoulder": ("肩", ["推举", "press", "引体向上", "pull-up"]),
    }
    checkin_injury_tags = set()
    body_aliases = {
        "knee": ("膝", "膝盖", "膝关节", "knee"),
        "back": ("腰", "腰椎", "下背", "lower back", "back"),
        "shoulder": ("肩", "肩膀", "肩关节", "肩袖", "shoulder"),
    }
    symptom_terms = ("疼", "痛", "不适", "受伤", "扭伤", "拉伤", "伤病", "pain", "hurt", "injur", "sore")
    for entry in checkin_history:
        normalized_entry = str(entry).lower()
        for injury_tag, aliases in body_aliases.items():
            if any(
                re.search(
                    rf"(?:{re.escape(alias)}.{{0,10}}(?:{'|'.join(symptom_terms)})|"
                    rf"(?:{'|'.join(symptom_terms)}).{{0,10}}{re.escape(alias)})",
                    normalized_entry,
                )
                for alias in aliases
            ):
                checkin_injury_tags.add(injury_tag)

    detected_injury_tags = canonical_injury_tags(injuries) | checkin_injury_tags
    for injury_tag in detected_injury_tags:
        label, unsafe_exercises = injury_rules[injury_tag]
        for ex_name in unsafe_exercises:
            changes.append({
                "day": "all",
                "action": "replace",
                "old_exercise_keyword": ex_name,
                "reason": f"检测到{label}不适，建议替换含{ex_name}的训练动作",
            })
            reason_parts.append(f"检测到{label}不适，建议替换{ex_name}类动作")

    # 2. 打卡中运动未完成/疲劳检测
    fatigue_count = 0
    for entry in checkin_history:
        exercise_text = entry.split("运动:", 1)[1].split("|", 1)[0].lower() if "运动:" in entry else ""
        if any(kw in exercise_text for kw in ["未完成", "太累", "没做", "skip", "太疲劳"]):
            fatigue_count += 1

    if fatigue_count >= 3:
        changes.append({
            "day": "all",
            "action": "reduce_volume",
            "detail": "每个动作减少1组",
            "reason": f"近期{fatigue_count}次打卡显示训练未完成或疲劳，建议降低训练容量",
        })
        reason_parts.append(f"近期{fatigue_count}次打卡显示疲劳或未完成")

    # 3. 平台期检测：体重变化
    dated_weights = []
    for entry in checkin_history:
        if "体重" in entry:
            nums = re.findall(r"[\d.]+", entry.split("体重")[-1][:20])
            date_match = re.search(r"日期:\s*(\d{4}-\d{2}-\d{2})", entry)
            if nums and date_match:
                try:
                    dated_weights.append((date.fromisoformat(date_match.group(1)), float(nums[0])))
                except ValueError:
                    continue

    dated_weights.sort(key=lambda item: item[0])
    if len(dated_weights) >= 4 and (dated_weights[-1][0] - dated_weights[0][0]).days >= 14:
        first_w, last_w = dated_weights[0][1], dated_weights[-1][1]
        if first_w > 0:
            change_pct = abs(last_w - first_w) / first_w * 100
            if change_pct < 0.5:  # 体重几乎没变
                if goal_type == "fat_loss":
                    changes.append({
                        "day": "all",
                        "action": "increase_cardio",
                        "detail": "有氧时长增加10分钟或频率+1次",
                        "reason": "体重2周以上无明显变化，可能进入平台期，建议增加有氧消耗",
                    })
                    reason_parts.append("体重停滞，疑似平台期")
                else:
                    changes.append({
                        "day": "all",
                        "action": "increase_volume",
                        "detail": "主要肌群动作增加1组",
                        "reason": "体重2周以上无明显变化，建议增加训练容量促进增肌",
                    })
                    reason_parts.append("体重停滞，建议增加训练容量")

    if not changes:
        return {"workout_adjustment": None}

    if detected_injury_tags:
        risk_notes.append("如伤病持续不适，建议咨询医生或康复师")

    adjustment = {
        "reason": "；".join(reason_parts),
        "changes": changes,
        "risk_notes": risk_notes,
    }

    return {"workout_adjustment": adjustment}


def build_review_graph():
    """构建复盘工作流"""
    workflow = StateGraph(ReviewState)

    workflow.add_node("retrieve_knowledge", review_retrieve_knowledge)
    workflow.add_node("analyze_checkins", review_analyze_checkins)
    workflow.add_node("next_day_advice", review_next_day_advice)
    workflow.add_node("workout_adjustment", review_workout_adjustment)

    workflow.set_entry_point("retrieve_knowledge")
    workflow.add_edge("retrieve_knowledge", "analyze_checkins")
    workflow.add_edge("analyze_checkins", "next_day_advice")
    workflow.add_edge("next_day_advice", "workout_adjustment")
    workflow.add_edge("workout_adjustment", END)

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
        "workout_adjustment": None,
    }

    result = await graph.ainvoke(initial_state)

    return {
        "review_summary": result["review_summary"],
        "next_day_advice": result["next_day_advice"],
        "workout_adjustment": result.get("workout_adjustment"),
    }
