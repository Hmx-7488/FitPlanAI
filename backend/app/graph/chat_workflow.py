from __future__ import annotations

import re
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.rag.models import GoalType, SearchQuery
from app.rag.retriever import get_retriever


class ChatAgentState(TypedDict):
    user_message: str
    current_page: str
    profile: dict[str, Any]
    latest_plan: dict[str, Any] | None
    page_context: dict[str, Any]
    risk_level: str
    risk_notice: str
    retrieved_knowledge: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    long_term_memories: list[Any]


_HIGH_RISK_TERMS = {
    "药物", "停药", "用药", "诊断", "治疗", "厌食", "催吐", "晕厥",
    "胸痛", "呼吸困难", "严重受伤", "每天500", "500大卡",
}

_HIGH_RISK_PATTERNS = (
    # 极低热量摄入：兼容数字与单位间空格以及“只吃/摄入/控制”等表达。
    re.compile(r"(?:每天|每日|一天)?(?:只吃|仅吃|摄入|控制在)?.{0,4}(?:[1-6]\d{2})\s*(?:大卡|千卡|kcal)"),
    # 自行停用处方或慢病药物。
    re.compile(r"(?:自行|自己)?(?:停用|停服|停吃|停止服用|减停).{0,12}药"),
    # 可能需要紧急处置的心肺症状及常见同义表达。
    re.compile(r"胸(?:口|部)?[^。！？!?]{0,8}(?:痛|疼|闷)"),
    re.compile(r"(?:喘不上气|喘不过气|无法呼吸|不能呼吸|气短|呼吸急促)"),
    re.compile(r"(?:头晕|眩晕|昏厥|晕倒)"),
)


def assess_risk(state: ChatAgentState) -> dict:
    message = state["user_message"].lower()
    compact_message = re.sub(r"\s+", "", message)
    matched = [term for term in _HIGH_RISK_TERMS if term.lower() in compact_message]
    matched.extend(
        pattern.pattern
        for pattern in _HIGH_RISK_PATTERNS
        if pattern.search(message)
    )
    if not matched:
        return {"risk_level": "normal", "risk_notice": ""}
    return {
        "risk_level": "high",
        "risk_notice": (
            "该问题可能涉及医疗诊断、药物、进食障碍或紧急健康风险。"
            "回答只能提供一般健康信息，不能替代医生、营养师或康复治疗师。"
        ),
    }


def retrieve_chat_knowledge(state: ChatAgentState) -> dict:
    profile = state.get("profile") or {}
    goal = profile.get("goal_type")
    goal_type = None
    if goal in {GoalType.fat_loss.value, GoalType.muscle_gain.value}:
        goal_type = GoalType(goal)

    restrictions = list(profile.get("allergies") or [])
    restrictions.extend(profile.get("forbidden_foods") or [])
    query = SearchQuery(
        query=state["user_message"],
        goal_type=goal_type,
        current_page=state.get("current_page", ""),
        training_level=profile.get("training_experience"),
        dietary_restrictions=restrictions,
        injuries=profile.get("injuries") or [],
        top_k=5,
    )
    result = get_retriever().search(query)
    documents = [
        {
            "chunk_id": item.chunk_id,
            "title": item.title,
            "content": item.content,
            "category": item.category,
            "source_name": item.source_name,
            "source_url": item.source_url,
            "evidence_level": item.evidence_level,
            "score": item.score,
        }
        for item in result.documents
    ]
    citations = [
        {
            "chunk_id": item.chunk_id,
            "title": item.title,
            "category": item.category,
            "source_name": item.source_name,
            "source_url": item.source_url,
            "evidence_level": item.evidence_level,
            "score": item.score,
        }
        for item in result.documents
    ]
    return {"retrieved_knowledge": documents, "citations": citations}


def build_chat_graph():
    workflow = StateGraph(ChatAgentState)
    workflow.add_node("assess_risk", assess_risk)
    workflow.add_node("retrieve_knowledge", retrieve_chat_knowledge)
    workflow.set_entry_point("assess_risk")
    workflow.add_edge("assess_risk", "retrieve_knowledge")
    workflow.add_edge("retrieve_knowledge", END)
    return workflow.compile()
