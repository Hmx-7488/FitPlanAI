from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, AsyncIterator

from langchain_openai import ChatOpenAI
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.graph.chat_workflow import ChatAgentState, build_chat_graph
from app.models.user import ChatConversation, ChatMessage, Plan, User
from app.services.artifact_microcompact import MicrocompactPolicy
from app.services.context_builder import ContextBudget, build_chat_context
from app.services.conversation_summary_service import get_latest_completed_summary
from app.services.user_memory_service import recall_user_memories

_CHAT_GRAPH = build_chat_graph()
logger = logging.getLogger(__name__)


def _json_load(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value) if value else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


def _profile_context(user: User | None) -> dict[str, Any]:
    if user is None:
        return {}
    return {
        "id": user.id,
        "gender": user.gender,
        "age": user.age,
        "height": user.height,
        "weight": user.weight,
        "target_weight": user.target_weight,
        "body_fat_rate": user.body_fat_rate,
        "activity_level": user.activity_level,
        "diet_preference": user.diet_preference,
        "goal_type": user.goal_type,
        "forbidden_foods": _json_load(user.forbidden_foods, []),
        "injuries": _json_load(user.injuries, []),
        "allergies": _json_load(user.allergies, []),
        "training_days_per_week": user.training_days_per_week,
        "session_duration_minutes": user.session_duration_minutes,
        "training_location": user.training_location,
        "equipment": _json_load(user.equipment, []),
        "training_experience": user.training_experience,
        "meal_scenario": user.meal_scenario,
        "prep_time_limit_minutes": user.prep_time_limit_minutes,
    }


def _plan_context(plan: Plan | None) -> dict[str, Any] | None:
    if plan is None:
        return None
    return {
        "id": plan.id,
        "daily_calorie_target": plan.daily_calorie_target,
        "calorie_info": _json_load(plan.calorie_info_json, {}),
        "macros": _json_load(plan.macros_json, {}),
        "meal_plan": plan.meal_plan[:2500],
        "workout_plan": plan.workout_plan[:2500],
        "summary": plan.summary[:1000],
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
    }


def _message_payload(message: ChatMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "citations": _json_load(message.citations_json, []),
        "context": _json_load(message.context_json, {}),
        "status": message.status,
        "created_at": message.created_at,
    }


async def _owned_conversation(
    db: AsyncSession, conversation_id: int, user_id: int, include_archived: bool = False
) -> ChatConversation | None:
    stmt = select(ChatConversation).where(
        ChatConversation.id == conversation_id,
        ChatConversation.user_id == user_id,
    )
    if not include_archived:
        stmt = stmt.where(ChatConversation.status == "active")
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_conversation(
    db: AsyncSession, user_id: int, title: str = "新对话"
) -> ChatConversation:
    user = await db.get(User, user_id)
    if user is None:
        raise ValueError("用户不存在")
    conversation = ChatConversation(user_id=user_id, title=title.strip() or "新对话")
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def list_conversations(
    db: AsyncSession, user_id: int
) -> list[tuple[ChatConversation, str]]:
    stmt = (
        select(ChatConversation)
        .where(
            ChatConversation.user_id == user_id,
            ChatConversation.status == "active",
        )
        .order_by(desc(ChatConversation.updated_at), desc(ChatConversation.id))
    )
    conversations = list((await db.execute(stmt)).scalars().all())
    output = []
    for conversation in conversations:
        message_stmt = (
            select(ChatMessage.content)
            .where(ChatMessage.conversation_id == conversation.id)
            .order_by(desc(ChatMessage.id))
            .limit(1)
        )
        last_message = (await db.execute(message_stmt)).scalar_one_or_none() or ""
        output.append((conversation, last_message[:120]))
    return output


async def get_conversation_detail(
    db: AsyncSession, conversation_id: int, user_id: int
) -> tuple[ChatConversation, list[ChatMessage]] | None:
    conversation = await _owned_conversation(db, conversation_id, user_id)
    if conversation is None:
        return None
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.id)
    )
    messages = list((await db.execute(stmt)).scalars().all())
    return conversation, messages


async def archive_conversation(
    db: AsyncSession, conversation_id: int, user_id: int
) -> bool:
    conversation = await _owned_conversation(db, conversation_id, user_id)
    if conversation is None:
        return False
    conversation.status = "archived"
    conversation.updated_at = datetime.utcnow()
    await db.commit()
    return True


async def _load_agent_context(
    db: AsyncSession,
    conversation: ChatConversation,
    current_page: str,
    page_context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None, list[ChatMessage]]:
    settings = get_settings()
    user = await db.get(User, conversation.user_id)
    plan_stmt = (
        select(Plan)
        .where(Plan.user_id == conversation.user_id)
        .order_by(desc(Plan.created_at), desc(Plan.id))
        .limit(1)
    )
    plan = (await db.execute(plan_stmt)).scalar_one_or_none()
    history_stmt = (
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation.id)
        .order_by(desc(ChatMessage.id))
        .limit(settings.CHAT_CONTEXT_MAX_HISTORY_MESSAGES)
    )
    history = list(reversed((await db.execute(history_stmt)).scalars().all()))
    return _profile_context(user), _plan_context(plan), history


def _chat_llm() -> ChatOpenAI:
    settings = get_settings()
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        openai_api_key=settings.LLM_API_KEY,
        openai_api_base=settings.LLM_BASE_URL,
        temperature=0.4,
        request_timeout=120,
        max_retries=2,
        max_tokens=settings.CHAT_CONTEXT_MAX_OUTPUT_TOKENS,
        streaming=True,
    )


async def stream_chat_message(
    db: AsyncSession,
    conversation_id: int,
    user_id: int,
    content: str,
    current_page: str = "",
    page_context: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    conversation = await _owned_conversation(db, conversation_id, user_id)
    if conversation is None:
        yield {"event": "error", "data": {"message": "会话不存在"}}
        return

    user_message = ChatMessage(
        conversation_id=conversation.id,
        role="user",
        content=content.strip(),
        status="completed",
    )
    db.add(user_message)
    if conversation.title == "新对话":
        conversation.title = content.strip()[:30]
    conversation.updated_at = datetime.utcnow()
    await db.commit()

    profile, latest_plan, history = await _load_agent_context(
        db, conversation, current_page, page_context or {}
    )
    try:
        long_term_memories = await recall_user_memories(db, user_id, content)
    except Exception as exc:
        long_term_memories = []
        logger.warning(
            "Long-term memory recall failed; continuing without memories",
            extra={"user_id": user_id, "error_type": type(exc).__name__},
        )
    summary = await get_latest_completed_summary(db, conversation.id)
    state: ChatAgentState = {
        "user_message": content,
        "current_page": current_page,
        "profile": profile,
        "latest_plan": latest_plan,
        "page_context": page_context or {},
        "risk_level": "normal",
        "risk_notice": "",
        "retrieved_knowledge": [],
        "citations": [],
        "long_term_memories": long_term_memories,
    }

    assistant_message = ChatMessage(
        conversation_id=conversation.id,
        role="assistant",
        content="",
        status="pending",
    )
    db.add(assistant_message)
    await db.commit()
    await db.refresh(assistant_message)

    try:
        result = await _CHAT_GRAPH.ainvoke(state)
        settings = get_settings()
        built_context = build_chat_context(
            state=result,
            history=history,
            current_user_content=content,
            current_user_message_id=user_message.id,
            budget=ContextBudget(
                context_window_tokens=settings.CHAT_CONTEXT_WINDOW_TOKENS,
                max_output_tokens=settings.CHAT_CONTEXT_MAX_OUTPUT_TOKENS,
                safety_buffer_tokens=settings.CHAT_CONTEXT_SAFETY_BUFFER_TOKENS,
            ),
            summary=summary,
            microcompact_policy=MicrocompactPolicy(
                full_content_tokens=(
                    settings.CHAT_MICROCOMPACT_FULL_ARTIFACT_TOKENS
                ),
                compact_content_tokens=(
                    settings.CHAT_MICROCOMPACT_TARGET_ARTIFACT_TOKENS
                ),
            ),
        )
        effective_citations = [
            result["citations"][index]
            for index in built_context.included_citation_indexes
            if index < len(result["citations"])
        ]
        context_summary = {
            "current_page": current_page,
            "has_profile": bool(profile),
            "latest_plan_id": latest_plan.get("id") if latest_plan else None,
            "risk_level": result["risk_level"],
            "knowledge_count": len(result["retrieved_knowledge"]),
            "memory_count": len(
                built_context.diagnostics.get("long_term_memory_ids", [])
            ),
            "memory_ids": built_context.diagnostics.get(
                "long_term_memory_ids", []
            ),
            "context_budget": built_context.diagnostics,
        }
        yield {
            "event": "meta",
            "data": context_summary,
            "internal": {"source_message_id": user_message.id},
        }

        chunks: list[str] = []
        async for chunk in _chat_llm().astream(built_context.messages):
            text = chunk.content if isinstance(chunk.content, str) else ""
            if not text:
                continue
            chunks.append(text)
            yield {"event": "delta", "data": {"content": text}}

        answer = "".join(chunks).strip()
        assistant_message.content = answer
        assistant_message.citations_json = json.dumps(
            effective_citations, ensure_ascii=False
        )
        assistant_message.context_json = json.dumps(
            context_summary, ensure_ascii=False
        )
        assistant_message.status = "completed"
        conversation.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(assistant_message)

        yield {"event": "citations", "data": effective_citations}
        yield {
            "event": "done",
            "data": _message_payload(assistant_message),
            "internal": {"source_message_id": user_message.id},
        }
    except asyncio.CancelledError:
        assistant_message.status = "stopped"
        assistant_message.content = assistant_message.content or "已停止生成。"
        await db.commit()
        raise
    except Exception:
        assistant_message.status = "failed"
        assistant_message.content = "生成失败，请稍后重试。"
        await db.commit()
        yield {
            "event": "error",
            "data": {"message": "AI 服务暂时不可用，请稍后重试。"},
            "internal": {"source_message_id": user_message.id},
        }
