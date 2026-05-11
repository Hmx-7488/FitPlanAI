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
    bmr: float
    calorie_info: dict
    macros: dict
    food_knowledge: str
    exercise_knowledge: str
    diet_knowledge: str
    meal_plan: str
    workout_plan: str
    summary: str


class ReviewState(TypedDict):
    user_profile: dict
    checkin_history: list[str]
    related_knowledge: str
    review_summary: str
    next_day_advice: str


def get_llm():
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        openai_api_key=settings.LLM_API_KEY,
        openai_api_base=settings.LLM_BASE_URL,
        temperature=0.7,
    )


def parse_user_profile(state: AgentState) -> dict:
    """解析用户信息"""
    profile = state["user_profile"]
    return {"user_profile": profile}


def retrieve_knowledge_node(state: AgentState) -> dict:
    """RAG检索相关知识"""
    profile = state["user_profile"]

    food_query = f"食材热量 营养素 蛋白质 碳水 {profile.get('diet_preference', '')}"
    exercise_query = f"运动消耗 热量 {profile.get('activity_level', '')}"
    diet_query = "减脂原则 热量缺口 营养分配 饮食建议"

    food_knowledge = "\n".join(retrieve_knowledge(food_query, k=3))
    exercise_knowledge = "\n".join(retrieve_knowledge(exercise_query, k=3))
    diet_knowledge = "\n".join(retrieve_knowledge(diet_query, k=3))

    return {
        "food_knowledge": food_knowledge,
        "exercise_knowledge": exercise_knowledge,
        "diet_knowledge": diet_knowledge,
    }


def calc_calorie_node(state: AgentState) -> dict:
    """计算热量目标"""
    profile = state["user_profile"]

    bmr = calc_bmr(
        gender=profile["gender"],
        weight=profile["weight"],
        height=profile["height"],
        age=profile["age"],
    )

    calorie_info = calc_daily_calorie(
        bmr=bmr,
        activity_level=profile.get("activity_level", "medium"),
    )

    macros = calc_macros(
        target_calories=calorie_info["target_calories"],
        weight=profile["weight"],
        activity_level=profile.get("activity_level", "medium"),
    )

    return {
        "bmr": bmr,
        "calorie_info": calorie_info,
        "macros": macros,
    }


def generate_meal_plan(state: AgentState) -> dict:
    """生成饮食建议"""
    llm = get_llm()
    profile = state["user_profile"]
    macros = state["macros"]
    calorie_info = state["calorie_info"]
    food_knowledge = state["food_knowledge"]
    diet_knowledge = state["diet_knowledge"]

    forbidden = ", ".join(profile.get("forbidden_foods", [])) or "无"
    preference = profile.get("diet_preference", "balanced")

    prompt = f"""你是一位专业的营养师，请根据以下信息生成一份详细的一周饮食计划。

用户信息：
- 性别：{profile['gender']}
- 年龄：{profile['age']}岁
- 身高：{profile['height']}cm
- 体重：{profile['weight']}kg
- 目标体重：{profile['target_weight']}kg
- 饮食偏好：{preference}
- 忌口食物：{forbidden}

每日营养目标：
- 热量：{calorie_info['target_calories']} kcal
- 蛋白质：{macros['protein_g']}g
- 碳水：{macros['carbs_g']}g
- 脂肪：{macros['fat_g']}g
- 膳食纤维：{macros['fiber_g']}g

食材营养参考：
{food_knowledge}

减脂饮食原则：
{diet_knowledge}

请输出：
1. 一日三餐 + 加餐的具体菜品和食材用量
2. 每餐的热量和三大营养素估算
3. 烹饪方式建议
4. 饮食注意事项

请用清晰的格式输出，便于阅读。"""

    response = llm.invoke([HumanMessage(content=prompt)])
    return {"meal_plan": response.content}


def generate_workout_plan(state: AgentState) -> dict:
    """生成运动建议"""
    llm = get_llm()
    profile = state["user_profile"]
    exercise_knowledge = state["exercise_knowledge"]
    calorie_info = state["calorie_info"]

    prompt = f"""你是一位专业的健身教练，请根据以下信息生成一份一周训练计划。

用户信息：
- 性别：{profile['gender']}
- 年龄：{profile['age']}岁
- 身高：{profile['height']}cm
- 体重：{profile['weight']}kg
- 目标：减脂，目标体重{profile['target_weight']}kg
- 活动水平：{profile.get('activity_level', 'medium')}
- 每日热量目标：{calorie_info['target_calories']} kcal

运动消耗参考：
{exercise_knowledge}

请输出：
1. 一周训练安排（每天练什么）
2. 每个训练的具体动作、组数、次数
3. 有氧运动时长和心率建议
4. 热身和拉伸建议
5. 训练注意事项

请用清晰的格式输出，便于阅读。"""

    response = llm.invoke([HumanMessage(content=prompt)])
    return {"workout_plan": response.content}


def summarize_plan(state: AgentState) -> dict:
    """汇总输出"""
    llm = get_llm()
    profile = state["user_profile"]
    calorie_info = state["calorie_info"]
    macros = state["macros"]
    meal_plan = state["meal_plan"]
    workout_plan = state["workout_plan"]

    prompt = f"""你是一位减脂教练，请根据以下生成的计划，给出一份简洁的总结和执行建议。

用户目标：从{profile['weight']}kg减到{profile['target_weight']}kg

每日营养目标：
- 热量：{calorie_info['target_calories']} kcal（TDEE: {calorie_info['tdee']} kcal，缺口: {calorie_info['deficit']} kcal）
- 蛋白质：{macros['protein_g']}g
- 碳水：{macros['carbs_g']}g
- 脂肪：{macros['fat_g']}g

请给出：
1. 3-5条核心执行建议
2. 需要特别注意的风险提醒
3. 预期减重速度
4. 鼓励和信心建设

简洁明了，不超过300字。"""

    response = llm.invoke([HumanMessage(content=prompt)])
    return {"summary": response.content}


def build_graph():
    """构建LangGraph工作流"""
    workflow = StateGraph(AgentState)

    workflow.add_node("parse_user_profile", parse_user_profile)
    workflow.add_node("retrieve_knowledge", retrieve_knowledge_node)
    workflow.add_node("calc_calorie", calc_calorie_node)
    workflow.add_node("generate_meal_plan", generate_meal_plan)
    workflow.add_node("generate_workout_plan", generate_workout_plan)
    workflow.add_node("summarize_plan", summarize_plan)

    workflow.set_entry_point("parse_user_profile")
    workflow.add_edge("parse_user_profile", "retrieve_knowledge")
    workflow.add_edge("retrieve_knowledge", "calc_calorie")
    workflow.add_edge("calc_calorie", "generate_meal_plan")
    workflow.add_edge("generate_meal_plan", "generate_workout_plan")
    workflow.add_edge("generate_workout_plan", "summarize_plan")
    workflow.add_edge("summarize_plan", END)

    return workflow.compile()


async def run_workflow(user_profile: dict) -> dict:
    """执行完整工作流"""
    graph = build_graph()

    initial_state: AgentState = {
        "user_profile": user_profile,
        "bmr": 0,
        "calorie_info": {},
        "macros": {},
        "food_knowledge": "",
        "exercise_knowledge": "",
        "diet_knowledge": "",
        "meal_plan": "",
        "workout_plan": "",
        "summary": "",
    }

    result = await graph.ainvoke(initial_state)

    return {
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

    # 根据打卡记录生成检索 query
    query = f"减脂饮食调整 平台期 运动恢复 {history_text[:200]}"
    knowledge = "\n".join(retrieve_knowledge(query, k=3))

    return {"related_knowledge": knowledge}


def review_analyze_checkins(state: ReviewState) -> dict:
    """复盘节点：分析打卡记录并生成复盘总结"""
    llm = get_llm()
    profile = state["user_profile"]
    history_text = "\n".join(state["checkin_history"])
    knowledge = state["related_knowledge"]

    prompt = f"""你是一位专业的减脂教练，请根据以下用户的打卡记录进行复盘分析。

用户信息：
- 性别：{profile['gender']} | 年龄：{profile['age']}岁
- 身高：{profile['height']}cm | 体重：{profile['weight']}kg
- 目标体重：{profile['target_weight']}kg
- 饮食偏好：{profile.get('diet_preference', 'balanced')}
- 忌口：{', '.join(profile.get('forbidden_foods', [])) or '无'}

最近打卡记录：
{history_text}

相关知识参考：
{knowledge}

请从以下维度进行复盘：
1. 饮食执行情况评估（热量、营养素是否达标）
2. 运动执行情况评估（频率、强度）
3. 体重变化趋势分析
4. 存在的问题和改进建议
5. 做得好的方面（鼓励）

请给出简洁清晰的复盘总结，200-400字。"""

    response = llm.invoke([HumanMessage(content=prompt)])
    return {"review_summary": response.content}


def review_next_day_advice(state: ReviewState) -> dict:
    """复盘节点：生成次日调整建议"""
    llm = get_llm()
    profile = state["user_profile"]
    history_text = "\n".join(state["checkin_history"])
    review_summary = state["review_summary"]
    knowledge = state["related_knowledge"]

    prompt = f"""你是一位专业的减脂教练，根据以下复盘结果和打卡记录，给出明天的具体调整建议。

用户目标：从{profile['weight']}kg减到{profile['target_weight']}kg

复盘总结：
{review_summary}

打卡记录：
{history_text}

调整建议参考：
{knowledge}

请给出明日具体建议，包括：
1. 明日饮食调整（热量、蛋白质、碳水的具体调整方向）
2. 明日运动建议（练什么、时长、强度）
3. 需要注意的事项
4. 鼓励的话

简洁实用，200-300字，让用户看完就知道明天该怎么做。"""

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
