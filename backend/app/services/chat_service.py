from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, AsyncIterator

import anyio
from langchain_openai import ChatOpenAI
from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.agent.chat_tool_agent import ToolAgentReport, run_chat_tool_agent
from app.agent.read_tools import ChatReadToolContext
from app.graph.chat_workflow import ChatAgentState, assess_risk, build_chat_graph
from app.models.user import ChatConversation, ChatMessage, Plan, User
from app.services.artifact_microcompact import MicrocompactPolicy
from app.services.context_builder import ContextBudget, build_chat_context
from app.services.conversation_summary_service import get_latest_completed_summary
from app.services.memory_retrieval_service import (
    mark_memory_hits_included,
    retrieve_user_memory_result,
)

_CHAT_GRAPH = build_chat_graph()
logger = logging.getLogger(__name__)
_CANCELLATION_CLEANUP_TIMEOUT_SECONDS = 5.0


def _json_load(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value) if value else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


async def _persist_cancelled_assistant(
    db: AsyncSession,
    assistant_message_id: int | None,
    *,
    content: str,
    citations_json: str = "[]",
    context_json: str = "{}",
) -> None:
    """Repair a pending assistant outside the request's cancelled scope."""
    if assistant_message_id is None:
        return

    cleanup_timed_out = False
    with anyio.CancelScope(shield=True):
        with anyio.move_on_after(_CANCELLATION_CLEANUP_TIMEOUT_SECONDS) as scope:
            try:
                # A cancelled SQLAlchemy operation must be rolled back before its
                # connection can be safely returned to the pool. Persist the
                # terminal state in a fresh session so an interrupted request
                # transaction cannot swallow the repair.
                await db.rollback()
            except Exception as exc:
                logger.error(
                    "Cancelled chat session rollback failed",
                    extra={
                        "assistant_message_id": assistant_message_id,
                        "error_type": type(exc).__name__,
                    },
                )

            try:
                repair_session_factory = async_sessionmaker(
                    db.bind,
                    expire_on_commit=False,
                )
                async with repair_session_factory() as repair_db:
                    await repair_db.execute(
                        update(ChatMessage)
                        .where(
                            ChatMessage.id == assistant_message_id,
                            ChatMessage.status == "pending",
                        )
                        .values(
                            status="stopped",
                            content=content,
                            citations_json=citations_json,
                            context_json=context_json,
                        )
                    )
                    await repair_db.commit()
            except Exception as exc:
                logger.error(
                    "Cancelled chat message repair failed",
                    extra={
                        "assistant_message_id": assistant_message_id,
                        "error_type": type(exc).__name__,
                    },
                )
        cleanup_timed_out = scope.cancel_called

    if cleanup_timed_out:
        logger.error(
            "Cancelled chat message repair timed out",
            extra={"assistant_message_id": assistant_message_id},
        )


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


async def _load_legacy_profile_plan(
    db: AsyncSession,
    conversation: ChatConversation,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    user = await db.get(User, conversation.user_id)
    plan_stmt = (
        select(Plan)
        .where(Plan.user_id == conversation.user_id)
        .order_by(desc(Plan.created_at), desc(Plan.id))
        .limit(1)
    )
    plan = (await db.execute(plan_stmt)).scalar_one_or_none()
    return _profile_context(user), _plan_context(plan)


async def _load_chat_history(
    db: AsyncSession,
    conversation_id: int,
) -> list[ChatMessage]:
    settings = get_settings()
    history_stmt = (
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(desc(ChatMessage.id))
        .limit(settings.CHAT_CONTEXT_MAX_HISTORY_MESSAGES)
    )
    return list(reversed((await db.execute(history_stmt)).scalars().all()))


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


def _chat_planner_llm() -> ChatOpenAI:
    settings = get_settings()
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        openai_api_key=settings.LLM_API_KEY,
        openai_api_base=settings.LLM_BASE_URL,
        temperature=0.1,
        request_timeout=min(60, settings.CHAT_TOOL_TIMEOUT_SECONDS),
        max_retries=1,
        max_tokens=800,
        streaming=False,
    )


def _deduplicate_citations(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for citation in citations:
        chunk_id = str(citation.get("chunk_id") or "")
        if not chunk_id or chunk_id in seen:
            continue
        seen.add(chunk_id)
        output.append(citation)
    return output


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
    assistant_message = ChatMessage(
        conversation_id=conversation.id,
        role="assistant",
        content="",
        status="pending",
    )
    db.add_all([user_message, assistant_message])
    if conversation.title == "新对话":
        conversation.title = content.strip()[:30]
    conversation.updated_at = datetime.utcnow()
    assistant_message_id: int | None = None
    try:
        await db.flush()
        assistant_message_id = assistant_message.id
        await db.commit()
    except asyncio.CancelledError:
        await _persist_cancelled_assistant(
            db,
            assistant_message_id,
            content="已停止生成。",
        )
        raise
    conversation_db_id = conversation.id
    user_message_id = user_message.id
    if assistant_message_id is None:
        raise RuntimeError("assistant message ID was not assigned")
    chunks: list[str] = []
    persisted_citations_json = "[]"
    persisted_context_json = "{}"

    try:
        history = await _load_chat_history(db, conversation_db_id)
        summary = await get_latest_completed_summary(db, conversation_db_id)
        memory_recall_result = None
        memory_retrieval_run_id = None
        state: ChatAgentState = {
            "user_message": content,
            "current_page": current_page,
            "profile": {},
            "latest_plan": None,
            "page_context": page_context or {},
            "risk_level": "normal",
            "risk_notice": "",
            "retrieved_knowledge": [],
            "citations": [],
            "long_term_memories": [],
        }
        settings = get_settings()
        tool_report = ToolAgentReport()
        result: dict[str, Any] = {**state, **assess_risk(state)}
        if settings.CHAT_TOOL_AGENT_ENABLED:
            tool_session_factory = async_sessionmaker(
                db.bind,
                expire_on_commit=False,
            )
            async with tool_session_factory() as tool_db:
                tool_report = await run_chat_tool_agent(
                    context=ChatReadToolContext(
                        db=tool_db,
                        user_id=user_id,
                        conversation_id=conversation_db_id,
                        source_message_id=user_message_id,
                    ),
                    user_message=content,
                    current_page=current_page,
                    planner=_chat_planner_llm(),
                )
        completed_tool_names = {
            trace.tool_name
            for trace in tool_report.traces
            if trace.status == "completed"
        }
        needs_legacy_context = (
            not settings.CHAT_TOOL_AGENT_ENABLED or tool_report.degraded
        )
        if needs_legacy_context:
            profile, latest_plan = await _load_legacy_profile_plan(db, conversation)
            state["profile"] = profile
            state["latest_plan"] = latest_plan
            if "search_memories" not in completed_tool_names:
                try:
                    memory_recall_result, memory_retrieval_run_id = (
                        await retrieve_user_memory_result(
                            db,
                            user_id,
                            content,
                            consumer="chat",
                            conversation_id=conversation_db_id,
                            source_message_id=user_message_id,
                        )
                    )
                    state["long_term_memories"] = memory_recall_result.memories
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "Long-term memory recall failed; continuing without memories",
                        extra={
                            "user_id": user_id,
                            "error_type": type(exc).__name__,
                        },
                    )
            result = await _CHAT_GRAPH.ainvoke(state)
        result["tool_artifacts"] = tool_report.artifacts
        built_context = build_chat_context(
            state=result,
            history=history,
            current_user_content=content,
            current_user_message_id=user_message_id,
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
        legacy_citations = [
            result["citations"][index]
            for index in built_context.included_citation_indexes
            if index < len(result["citations"])
        ]
        included_tool_references = set(
            built_context.included_tool_reference_ids
        )
        tool_citations = [
            {
                key: value
                for key, value in citation.items()
                if key != "tool_reference_id"
            }
            for citation in tool_report.citations
            if citation.get("tool_reference_id") in included_tool_references
        ]
        effective_citations = _deduplicate_citations(
            [*legacy_citations, *tool_citations]
        )
        for trace in tool_report.traces:
            trace.included_in_answer = (
                f"tool:{trace.call_id}" in included_tool_references
            )
        tool_traces = [trace.to_dict() for trace in tool_report.traces]
        included_tool_names = {
            trace.tool_name for trace in tool_report.traces
            if trace.included_in_answer
        }
        effective_plan_id = (
            (result.get("latest_plan") or {}).get("id")
            if isinstance(result.get("latest_plan"), dict)
            else None
        )
        if effective_plan_id is None and "get_latest_plan" in included_tool_names:
            for trace in tool_report.traces:
                if trace.tool_name != "get_latest_plan":
                    continue
                plan_source = next(
                    (
                        source for source in trace.sources
                        if source.get("source_type") == "plan"
                    ),
                    None,
                )
                if plan_source is not None:
                    try:
                        effective_plan_id = int(plan_source.get("source_id"))
                    except (TypeError, ValueError):
                        effective_plan_id = None
                break
        automatic_memory_ids = list(
            built_context.diagnostics.get("long_term_memory_ids", [])
        )
        included_tool_memory_usages = [
            usage
            for usage in tool_report.memory_usages
            if usage.get("tool_reference_id") in included_tool_references
        ]
        tool_memory_ids = [
            int(memory_id)
            for usage in included_tool_memory_usages
            for memory_id in usage.get("memory_ids") or []
        ]
        effective_memory_ids = list(dict.fromkeys([
            *automatic_memory_ids,
            *tool_memory_ids,
        ]))
        memory_retrieval_runs: list[dict[str, Any]] = []
        if memory_recall_result is not None:
            memory_retrieval_runs.append({
                "run_id": memory_retrieval_run_id,
                "memory_ids": automatic_memory_ids,
                "effective_mode": memory_recall_result.effective_mode,
                "degraded": memory_recall_result.degraded,
            })
        memory_retrieval_runs.extend(
            {
                "run_id": usage.get("run_id"),
                "memory_ids": [
                    int(memory_id) for memory_id in usage.get("memory_ids") or []
                ],
                "effective_mode": usage.get("effective_mode"),
                "degraded": bool(usage.get("degraded")),
            }
            for usage in included_tool_memory_usages
        )
        single_memory_run = (
            memory_retrieval_runs[0]
            if len(memory_retrieval_runs) == 1
            else None
        )
        context_summary = {
            "current_page": current_page,
            "has_profile": bool(result.get("profile"))
            or "get_user_profile" in included_tool_names,
            "latest_plan_id": effective_plan_id,
            "risk_level": result["risk_level"],
            # Count only citations that survived the shared context budget.
            # Tool-only knowledge lives outside the legacy RAG result array.
            "knowledge_count": len(effective_citations),
            "memory_count": len(effective_memory_ids),
            "memory_ids": effective_memory_ids,
            # Scalar fields remain compatible for the normal one-retrieval case.
            # Multiple distinct runs are represented only by the structured list
            # so mode/run/degraded values can never be mixed across executions.
            "memory_retrieval_run_id": (
                single_memory_run.get("run_id") if single_memory_run else None
            ),
            "memory_retrieval_mode": (
                single_memory_run.get("effective_mode")
                if single_memory_run
                else None
            ),
            "memory_retrieval_degraded": any(
                bool(run["degraded"]) for run in memory_retrieval_runs
            ),
            "memory_retrieval_runs": memory_retrieval_runs,
            "tool_agent_enabled": settings.CHAT_TOOL_AGENT_ENABLED,
            "tool_agent_degraded": tool_report.degraded,
            "tool_agent_degradation_reason": tool_report.degradation_reason,
            "tool_call_count": tool_report.selected_count,
            "tool_calls": tool_traces,
            "context_budget": built_context.diagnostics,
        }
        persisted_citations_json = json.dumps(
            effective_citations, ensure_ascii=False
        )
        persisted_context_json = json.dumps(
            context_summary, ensure_ascii=False
        )
        await mark_memory_hits_included(
            db,
            memory_retrieval_run_id,
            automatic_memory_ids,
        )
        for usage in tool_report.memory_usages:
            if usage.get("tool_reference_id") not in included_tool_references:
                continue
            await mark_memory_hits_included(
                db,
                usage.get("run_id"),
                [int(item) for item in usage.get("memory_ids") or []],
            )
        yield {
            "event": "meta",
            "data": context_summary,
            "internal": {"source_message_id": user_message_id},
        }
        for trace in tool_traces:
            yield {"event": "tool", "data": trace}

        async for chunk in _chat_llm().astream(built_context.messages):
            text = chunk.content if isinstance(chunk.content, str) else ""
            if not text:
                continue
            chunks.append(text)
            yield {"event": "delta", "data": {"content": text}}

        answer = "".join(chunks).strip()
        if not answer:
            raise RuntimeError("chat model returned an empty response")
        assistant_message.content = answer
        assistant_message.citations_json = persisted_citations_json
        assistant_message.context_json = persisted_context_json
        assistant_message.status = "completed"
        conversation.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(assistant_message)

        yield {"event": "citations", "data": effective_citations}
        yield {
            "event": "done",
            "data": _message_payload(assistant_message),
            "internal": {"source_message_id": user_message_id},
        }
    except asyncio.CancelledError:
        partial_answer = "".join(chunks).strip()
        await _persist_cancelled_assistant(
            db,
            assistant_message_id,
            content=partial_answer or "已停止生成。",
            citations_json=persisted_citations_json,
            context_json=persisted_context_json,
        )
        raise
    except Exception as exc:
        await db.rollback()
        partial_answer = "".join(chunks).strip()
        logger.warning(
            "Chat response generation failed",
            extra={"error_type": type(exc).__name__},
        )
        await db.execute(
            update(ChatMessage)
            .where(ChatMessage.id == assistant_message_id)
            .values(
                status="failed",
                content=partial_answer or "生成失败，请稍后重试。",
                citations_json=persisted_citations_json,
                context_json=persisted_context_json,
            )
        )
        await db.commit()
        yield {
            "event": "error",
            "data": {"message": "AI 服务暂时不可用，请稍后重试。"},
            "internal": {"source_message_id": user_message_id},
        }
