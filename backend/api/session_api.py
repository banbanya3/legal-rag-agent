"""会话管理接口。

这些接口全是同步的 DB 操作（毫秒级），所以统一用 `def` 而不是 `async def` ——
FastAPI 看到 `def` 会自动把整个函数丢进线程池，不会阻塞事件循环。
反过来说，如果写成 `async def` 却调同步 DB，才会出问题。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.deps import get_db
from common.result import Result
from schemas.common import ApiResponse
from schemas.session_schema import (
    ClearResult,
    CreateSessionResult,
    MessageInfo,
    RenameRequest,
    SessionInfo,
)
from service import session_service

router = APIRouter(prefix="/api/sessions", tags=["会话"])


@router.get(
    "",
    summary="获取会话列表",
    response_model=ApiResponse[list[SessionInfo]],
)
def list_sessions(
    keyword: str = Query(default="", max_length=50, description="按标题模糊搜索"),
    limit: int = Query(default=200, ge=1, le=500, description="最多返回多少条"),
    db: Session = Depends(get_db),
):
    """按「最后一条消息时间」倒序，最近聊过的排最前。"""
    return Result.ok(session_service.list_sessions(db, keyword, limit))


@router.post(
    "",
    summary="手动创建一个空会话",
    response_model=ApiResponse[CreateSessionResult],
)
def create_session(db: Session = Depends(get_db)):
    return Result.ok(session_service.create_session(db))


@router.get(
    "/{session_id}/messages",
    summary="获取指定会话的历史消息",
    response_model=ApiResponse[list[MessageInfo]],
)
def get_messages(session_id: str, db: Session = Depends(get_db)):
    return Result.ok(session_service.get_messages(db, session_id))


@router.patch("/{session_id}", summary="重命名会话")
def rename_session(
    session_id: str, payload: RenameRequest, db: Session = Depends(get_db)
):
    data = session_service.rename(db, session_id, payload.title)
    return Result.ok(data, "标题已更新")


@router.delete("/{session_id}", summary="删除会话及其消息")
def delete_session(session_id: str, db: Session = Depends(get_db)):
    return Result.ok(session_service.delete(db, session_id), "会话已删除")


@router.delete(
    "/{session_id}/messages",
    summary="清空会话消息（保留会话）",
    response_model=ApiResponse[ClearResult],
)
def clear_messages(session_id: str, db: Session = Depends(get_db)):
    data = session_service.clear_messages(db, session_id)
    return Result.ok(data, f"已清空 {data['deleted']} 条消息")
