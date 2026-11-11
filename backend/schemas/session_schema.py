"""会话与消息模型。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from schemas.chat_schema import SourceItem


class RenameRequest(BaseModel):
    """PATCH /api/sessions/{id} 的请求体。"""

    title: str = Field(..., min_length=1, max_length=60, description="新标题")


class SessionInfo(BaseModel):
    """左侧会话列表的一项。"""

    session_id: str
    title: str
    created_at: str = Field(default="", description="创建时间，格式 YYYY-MM-DD HH:MM")
    last_message_at: str | None = Field(
        default=None, description="最后一条消息时间，空会话为 null"
    )
    message_count: int = Field(default=0, ge=0)


class MessageInfo(BaseModel):
    """历史消息。带 sources 是为了回看时也能展开法条依据。"""

    id: int
    role: Literal["user", "assistant"]
    content: str
    sources: list[SourceItem] = Field(default_factory=list)
    elapsed_ms: int = Field(default=0, ge=0)
    created_at: str = Field(default="", description="格式 HH:MM")


class CreateSessionResult(BaseModel):
    """POST /api/sessions 的返回。"""

    session_id: str
    title: str


class ClearResult(BaseModel):
    """DELETE /api/sessions/{id}/messages 的返回。"""

    deleted: int = Field(ge=0, description="清掉的消息条数")
