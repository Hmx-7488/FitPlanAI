import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.chat import (
    ChatConversationCreate,
    ChatConversationDetail,
    ChatConversationResponse,
    ChatMessageCreate,
    ChatMessageResponse,
)
from app.services.chat_service import (
    archive_conversation,
    create_conversation,
    get_conversation_detail,
    list_conversations,
    stream_chat_message,
)

router = APIRouter()


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
):
    results = await list_conversations(db, user_id)
    return [
        _conversation_response(conversation, last_message)
        for conversation, last_message in results
    ]


@router.get(
    "/conversations/{conversation_id}",
    response_model=ChatConversationDetail,
)
async def get_chat_conversation(
    conversation_id: int,
    user_id: int = Query(gt=0),
    db: AsyncSession = Depends(get_db),
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
):
    if not await archive_conversation(db, conversation_id, user_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"status": "archived"}


@router.post("/conversations/{conversation_id}/messages/stream")
async def stream_message(
    conversation_id: int,
    payload: ChatMessageCreate,
    db: AsyncSession = Depends(get_db),
):
    if await get_conversation_detail(db, conversation_id, payload.user_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    async def event_stream():
        async for event in stream_chat_message(
            db=db,
            conversation_id=conversation_id,
            user_id=payload.user_id,
            content=payload.content,
            current_page=payload.current_page,
            page_context=payload.page_context,
        ):
            data = json.dumps(event["data"], ensure_ascii=False, default=str)
            yield f"event: {event['event']}\ndata: {data}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
