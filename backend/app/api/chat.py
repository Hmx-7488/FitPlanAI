import json
import logging
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.core.database import get_db
from app.core.config import get_settings
from app.schemas.chat import (
    ChatConversationCreate,
    ChatConversationDetail,
    ChatConversationResponse,
    ChatMessageCreate,
    ChatMessageResponse,
    UserMemoryActionRequest,
    UserMemoryResponse,
    UserMemoryUpdateRequest,
)
from app.services.chat_service import (
    archive_conversation,
    create_conversation,
    get_conversation_detail,
    list_conversations,
    stream_chat_message,
)
from app.services.conversation_summary_service import compact_conversation_if_needed
from app.services.user_memory_service import (
    MemoryConflictError,
    confirm_user_memory,
    delete_user_memory,
    extract_and_persist_user_memory,
    list_user_memories,
    reject_user_memory,
    update_user_memory,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def require_chat_access(
    x_memory_access_key: str | None = Header(
        default=None,
        alias="X-Memory-Access-Key",
    ),
    settings=Depends(get_settings),
) -> None:
    if settings.APP_ENV == "development":
        return
    configured_key = settings.MEMORY_API_ACCESS_KEY
    if not configured_key:
        raise HTTPException(status_code=503, detail="聊天与记忆 API 尚未配置访问控制")
    if not x_memory_access_key or not secrets.compare_digest(
        x_memory_access_key,
        configured_key,
    ):
        raise HTTPException(status_code=403, detail="无权访问聊天与记忆数据")


def _memory_response(memory) -> UserMemoryResponse:
    try:
        content = json.loads(memory.content_json or "{}")
    except json.JSONDecodeError:
        content = {}
    return UserMemoryResponse(
        id=memory.id,
        user_id=memory.user_id,
        memory_type=memory.memory_type,
        memory_key=memory.memory_key,
        content=content if isinstance(content, dict) else {},
        content_text=memory.content_text,
        source_conversation_id=memory.source_conversation_id,
        source_message_id=memory.source_message_id,
        confirmation_status=memory.confirmation_status,
        sensitivity=memory.sensitivity,
        confidence=memory.confidence,
        valid_from=memory.valid_from,
        valid_until=memory.valid_until,
        supersedes_memory_id=memory.supersedes_memory_id,
        created_by=memory.created_by,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )


async def postprocess_chat_conversation(
    conversation_id: int,
    postprocess_state: dict[str, int | None],
) -> None:
    try:
        await compact_conversation_if_needed(conversation_id)
    except Exception as exc:
        logger.warning(
            "Chat postprocess task failed",
            extra={
                "conversation_id": conversation_id,
                "task": "conversation_summary",
                "error_type": type(exc).__name__,
            },
        )
    source_message_id = postprocess_state.get("source_message_id")
    if source_message_id is None:
        return
    try:
        await extract_and_persist_user_memory(conversation_id, source_message_id)
    except Exception as exc:
        logger.warning(
            "Chat postprocess task failed",
            extra={
                "conversation_id": conversation_id,
                "source_message_id": source_message_id,
                "task": "user_memory",
                "error_type": type(exc).__name__,
            },
        )


def _conversation_response(conversation, last_message: str = ""):
    return ChatConversationResponse(
        id=conversation.id,
        user_id=conversation.user_id,
        title=conversation.title,
        status=conversation.status,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        last_message=last_message,
    )


@router.post("/conversations", response_model=ChatConversationResponse)
async def create_chat_conversation(
    payload: ChatConversationCreate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_chat_access),
):
    try:
        conversation = await create_conversation(db, payload.user_id, payload.title)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _conversation_response(conversation)


@router.get("/conversations", response_model=list[ChatConversationResponse])
async def get_chat_conversations(
    user_id: int = Query(gt=0),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_chat_access),
):
    results = await list_conversations(db, user_id)
    return [
        _conversation_response(conversation, last_message)
        for conversation, last_message in results
    ]


@router.get("/memories", response_model=list[UserMemoryResponse])
async def get_user_memories(
    user_id: int = Query(gt=0),
    confirmation_status: str | None = Query(default=None, pattern="^(candidate|confirmed|rejected)$"),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_chat_access),
):
    memories = await list_user_memories(
        db,
        user_id,
        confirmation_status=confirmation_status,
    )
    return [_memory_response(memory) for memory in memories]


@router.post("/memories/{memory_id}/confirm", response_model=UserMemoryResponse)
async def confirm_memory(
    memory_id: int,
    payload: UserMemoryActionRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_chat_access),
):
    try:
        memory = await confirm_user_memory(db, memory_id, payload.user_id)
    except MemoryConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail="记忆已被其他请求更新，请刷新后重试",
        ) from exc
    if memory is None:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return _memory_response(memory)


@router.post("/memories/{memory_id}/reject", response_model=UserMemoryResponse)
async def reject_memory(
    memory_id: int,
    payload: UserMemoryActionRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_chat_access),
):
    memory = await reject_user_memory(db, memory_id, payload.user_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return _memory_response(memory)


@router.patch("/memories/{memory_id}", response_model=UserMemoryResponse)
async def edit_memory(
    memory_id: int,
    payload: UserMemoryUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_chat_access),
):
    try:
        memory = await update_user_memory(
            db,
            memory_id,
            payload.user_id,
            memory_type=payload.memory_type,
            memory_key=payload.memory_key,
            content=payload.content,
            content_text=payload.content_text,
            valid_until=payload.valid_until,
            update_valid_until="valid_until" in payload.model_fields_set,
        )
    except MemoryConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail="记忆已被其他请求更新，请刷新后重试",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if memory is None:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return _memory_response(memory)


@router.delete("/memories/{memory_id}")
async def forget_memory(
    memory_id: int,
    user_id: int = Query(gt=0),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_chat_access),
):
    if not await delete_user_memory(db, memory_id, user_id):
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {"status": "deleted"}


@router.get(
    "/conversations/{conversation_id}",
    response_model=ChatConversationDetail,
)
async def get_chat_conversation(
    conversation_id: int,
    user_id: int = Query(gt=0),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_chat_access),
):
    result = await get_conversation_detail(db, conversation_id, user_id)
    if result is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    conversation, messages = result
    return ChatConversationDetail(
        **_conversation_response(conversation).model_dump(),
        messages=[
            ChatMessageResponse(
                id=message.id,
                role=message.role,
                content=message.content,
                citations=json.loads(message.citations_json or "[]"),
                context=json.loads(message.context_json or "{}"),
                status=message.status,
                created_at=message.created_at,
            )
            for message in messages
        ],
    )


@router.delete("/conversations/{conversation_id}")
async def delete_chat_conversation(
    conversation_id: int,
    user_id: int = Query(gt=0),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_chat_access),
):
    if not await archive_conversation(db, conversation_id, user_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"status": "archived"}


@router.post("/conversations/{conversation_id}/messages/stream")
async def stream_message(
    conversation_id: int,
    payload: ChatMessageCreate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_chat_access),
):
    if await get_conversation_detail(db, conversation_id, payload.user_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    postprocess_state: dict[str, int | None] = {"source_message_id": None}

    async def event_stream():
        async for event in stream_chat_message(
            db=db,
            conversation_id=conversation_id,
            user_id=payload.user_id,
            content=payload.content,
            current_page=payload.current_page,
            page_context=payload.page_context,
        ):
            internal = event.get("internal") or {}
            if internal.get("source_message_id") is not None:
                postprocess_state["source_message_id"] = int(
                    internal["source_message_id"]
                )
            data = json.dumps(event["data"], ensure_ascii=False, default=str)
            yield f"event: {event['event']}\ndata: {data}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        background=BackgroundTask(
            postprocess_chat_conversation,
            conversation_id,
            postprocess_state,
        ),
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
