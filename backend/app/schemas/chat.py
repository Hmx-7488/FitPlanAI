import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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


class UserMemoryResponse(BaseModel):
    id: int
    user_id: int
    memory_type: Literal["preference", "goal", "habit", "constraint", "experience"]
    memory_key: str
    content: dict[str, Any] = Field(default_factory=dict)
    content_text: str
    source_conversation_id: int | None = None
    source_message_id: int | None = None
    confirmation_status: Literal["candidate", "confirmed", "rejected"]
    sensitivity: Literal["normal", "health_sensitive"]
    confidence: float
    valid_from: datetime
    valid_until: datetime | None = None
    supersedes_memory_id: int | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime


class UserMemoryActionRequest(BaseModel):
    user_id: int = Field(gt=0)


class UserMemoryUpdateRequest(BaseModel):
    user_id: int = Field(gt=0)
    memory_type: Literal["preference", "goal", "habit", "constraint", "experience"] | None = None
    memory_key: str | None = Field(
        default=None,
        min_length=3,
        max_length=160,
        pattern=r"^[a-z0-9][a-z0-9._-]{2,159}$",
    )
    content: dict[str, Any] | None = None
    content_text: str | None = Field(default=None, min_length=2, max_length=500)
    valid_until: datetime | None = None

    @field_validator("content")
    @classmethod
    def limit_structured_content(cls, value: dict[str, Any] | None):
        if value is not None and len(json.dumps(value, ensure_ascii=False)) > 4000:
            raise ValueError("memory content is too large")
        return value

    @model_validator(mode="after")
    def require_memory_change(self):
        editable_fields = {
            "memory_type",
            "memory_key",
            "content",
            "content_text",
            "valid_until",
        }
        if not (self.model_fields_set & editable_fields):
            raise ValueError("at least one memory field must be provided")
        return self
