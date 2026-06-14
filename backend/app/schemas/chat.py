from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatCitation(BaseModel):
    chunk_id: str
    title: str
    category: str = ""
    source_name: str = ""
    source_url: str = ""
    evidence_level: str = ""
    score: float = 0.0


class ChatMessageResponse(BaseModel):
    id: int
    role: Literal["user", "assistant", "system"]
    content: str
    citations: list[ChatCitation] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    status: str
    created_at: datetime


class ChatConversationCreate(BaseModel):
    user_id: int = Field(gt=0)
    title: str = Field(default="新对话", max_length=100)


class ChatConversationResponse(BaseModel):
    id: int
    user_id: int
    title: str
    status: str
    created_at: datetime
    updated_at: datetime
    last_message: str = ""


class ChatConversationDetail(ChatConversationResponse):
    messages: list[ChatMessageResponse] = Field(default_factory=list)


class ChatMessageCreate(BaseModel):
    user_id: int = Field(gt=0)
    content: str = Field(min_length=1, max_length=4000)
    current_page: str = Field(default="", max_length=100)
    page_context: dict[str, Any] = Field(default_factory=dict)
