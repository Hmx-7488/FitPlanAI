import json
from typing import TypedDict, Any
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from app.core.config import get_settings
from app.tools.calorie_tools import calc_bmr, calc_daily_calorie, calc_macros
from app.rag.retriever import retrieve_knowledge

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
    meal_plan: str
    workout_plan: str
    risk_warnings: list[str]       # 风险校验结果
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

    # 选填但建议补充的字段
    if profile.get("body_fat_rate") is None:
        missing.append("体脂率（选填，但能让计划更精准）")
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
    """RAG检索相关知识"""
    profile = state["user_profile"]

    # 基础知识检索
    food_query = f"食材热量 蛋白质 {profile.get('diet_preference', '')}"
    exercise_query = f"运动消耗 {profile.get('activity_level', '')}"

    food_knowledge = "\n".join(retrieve_knowledge(food_query, k=2))
    exercise_knowledge = "\n".join(retrieve_knowledge(exercise_query, k=2))
    diet_knowledge = "\n".join(retrieve_knowledge("减脂原则 热量缺口", k=2))

    # 构建风险相关查询（结合用户伤病和过敏信息）
    risk_parts = ["健康风险 规则"]
    if profile.get("injuries"):
        risk_parts.append(" ".join(profile["injuries"]) + " 伤病 禁忌动作")
    if profile.get("allergies"):
        risk_parts.append(" ".join(profile["allergies"]) + " 过敏 替代")
    risk_query = " ".join(risk_parts)
    risk_knowledge = "\n".join(retrieve_knowledge(risk_query, k=3))

    return {
        "food_knowledge": food_knowledge[:600],
        "exercise_knowledge": exercise_knowledge[:600],
        "diet_knowledge": diet_knowledge[:400],
        "risk_knowledge": risk_knowledge[:600],
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
    """生成饮食建议，根据目标类型分支"""
    llm = get_llm(max_tokens=1500)
    profile = state["user_profile"]
    macros = state["macros"]
    calorie_info = state["calorie_info"]
    food_knowledge = state["food_knowledge"]
    diet_knowledge = state["diet_knowledge"]
    goal_type = state.get("goal_type", "fat_loss")

    forbidden = ", ".join(profile.get("forbidden_foods", [])) or "无"
    preference = profile.get("diet_preference", "balanced")

    if goal_type == "muscle_gain":
        goal_desc = f"""用户目标：增肌。每日热量盈余约{abs(calorie_info['deficit'])}kcal，蛋白质需求高（{macros['protein_g']}g）。
饮食策略：保证蛋白质和训练日前后碳水，增加正餐和加餐安排，避免脏增肌。
要求：每个方案都要有加餐，蛋白质来源丰富。"""
    else:
        goal_desc = f"""用户目标：减脂。每日热量缺口{calorie_info['deficit']}kcal。
饮食策略：高蛋白保肌，控制油脂和精制糖，餐食偏高蛋白、高纤维、适量碳水。
要求：控制总热量，避免高热量零食。"""

    prompt = f"""你是营养师。根据以下信息生成3天饮食计划（不需要7天，3天即可展示模式）。

用户：{profile['gender']}，{profile['age']}岁，{profile['height']}cm，{profile['weight']}kg→目标{profile['target_weight']}kg
偏好：{preference}，忌口：{forbidden}
每日目标：热量{calorie_info['target_calories']}kcal，蛋白{macros['protein_g']}g，碳水{macros['carbs_g']}g，脂肪{macros['fat_g']}g

{goal_desc}

参考知识：
{food_knowledge[:500]}

{diet_knowledge[:300]}

输出格式：
**第1天/第2天/第3天**
- 早餐：菜品 + 大约热量
- 午餐：菜品 + 大约热量
- 晚餐：菜品 + 大约热量
- 加餐：可选

最后附：烹饪建议（3条）+ 饮食注意事项（3条）。简洁，不要冗长解释。"""

    response = llm.invoke([HumanMessage(content=prompt)])
    return {"meal_plan": response.content}


def generate_workout_plan(state: AgentState) -> dict:
    """生成运动建议，根据目标类型分支"""
    llm = get_llm(max_tokens=1200)
    profile = state["user_profile"]
    exercise_knowledge = state["exercise_knowledge"]
    calorie_info = state["calorie_info"]
    goal_type = state.get("goal_type", "fat_loss")

    if goal_type == "muscle_gain":
        goal_desc = """用户目标：增肌。
训练策略：
- 以力量训练和肌肥大训练为主，按胸/背/腿/肩/手臂或推拉腿拆分
- 强调渐进超负荷，输出动作、组数、次数、RPE建议、进阶方式
- 有氧只作为心肺和恢复辅助，每周1-2次，每次20-30分钟
- 训练容量充足，每个肌群每周12-20组"""
    else:
        goal_desc = """用户目标：减脂。
训练策略：
- 力量训练用于保留肌肉，中等强度
- 有氧训练增加消耗，每周3-4次，每次30-40分钟中低强度
- 控制训练容量，避免热量缺口下恢复不足
- 力量和有氧可以安排在同一天或交替"""

    prompt = f"""你是健身教练。根据以下信息生成一周训练计划。

用户：{profile['gender']}，{profile['age']}岁，{profile['weight']}kg→目标{profile['target_weight']}kg
活动水平：{profile.get('activity_level', 'medium')}，每日热量目标：{calorie_info['target_calories']}kcal

{goal_desc}

运动参考：
{exercise_knowledge[:500]}

输出格式（按天列出）：
**周一** 力量（上肢）：动作1 组数x次数 / 动作2 ... / 有氧 时长
**周二** 有氧：...
...

最后附：热身建议（2条）+ 训练注意事项（3条）。简洁明了。"""

    response = llm.invoke([HumanMessage(content=prompt)])
    return {"workout_plan": response.content}


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


async def run_workflow(user_profile: dict) -> dict:
    """执行完整工作流。返回 dict 必含 status 字段：
    - status="plan"：计划生成成功
    - status="need_info"：需要用户补充信息
    """
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
        "meal_plan": "",
        "workout_plan": "",
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
        "workout_plan": result["workout_plan"],
        "summary": result["summary"],
    }


# ========== 第二版：复盘工作流 ==========


def review_retrieve_knowledge(state: ReviewState) -> dict:
    """复盘节点：检索相关知识"""
    history_text = "\n".join(state["checkin_history"])
    goal_type = state["user_profile"].get("goal_type", "fat_loss")

    if goal_type == "muscle_gain":
        query = f"增肌饮食调整 蛋白质摄入 力量训练恢复 {history_text[:200]}"
    else:
        query = f"减脂饮食调整 平台期 运动恢复 {history_text[:200]}"
    knowledge = "\n".join(retrieve_knowledge(query, k=3))

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
