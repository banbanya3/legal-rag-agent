"""会话数据访问。

只做 CRUD 与 SQL 拼装，不掺业务判断（比如"标题该取几个字"属于 service 层）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from dao.models import ChatMessage, ChatSession


def get(db: Session, session_id: str) -> Optional[ChatSession]:
    return db.get(ChatSession, session_id)


def create(db: Session, session_id: str, title: str = "新对话") -> ChatSession:
    obj = ChatSession(session_id=session_id, title=title)
    db.add(obj)
    db.flush()
    return obj


def get_or_create(db: Session, session_id: str, title: str) -> ChatSession:
    obj = get(db, session_id)
    if obj is None:
        obj = create(db, session_id, title)
    return obj


def rename(db: Session, session_id: str, title: str) -> bool:
    obj = get(db, session_id)
    if obj is None:
        return False
    obj.title = title
    obj.updated_at = datetime.now()
    db.flush()
    return True


def delete(db: Session, session_id: str) -> None:
    """先删子表再删主表。MySQL 里虽然有外键级联，但显式删除更直观也更可控。"""
    db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete(
        synchronize_session=False
    )
    db.query(ChatSession).filter(ChatSession.session_id == session_id).delete(
        synchronize_session=False
    )
    db.flush()


def list_with_stats(
    db: Session, keyword: str = "", limit: int = 200
) -> list[dict]:
    """左侧会话列表：一次 group by 把消息条数和最后活跃时间一起算出来。

    避免 N+1 查询 —— 如果用 for 循环逐个查 count，200 个会话就是 200 条 SQL，
    打开页面要转两秒。
    """
    last_at = func.max(ChatMessage.created_at)
    msg_count = func.count(ChatMessage.id)

    query = (
        db.query(
            ChatSession.session_id,
            ChatSession.title,
            ChatSession.created_at,
            last_at.label("last_at"),
            msg_count.label("msg_count"),
        )
        .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.session_id)
        .group_by(
            ChatSession.session_id,
            ChatSession.title,
            ChatSession.created_at,
        )
    )

    if keyword.strip():
        query = query.filter(ChatSession.title.like(f"%{keyword.strip()}%"))

    rows = (
        query.order_by(func.coalesce(last_at, ChatSession.created_at).desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "session_id": r.session_id,
            "title": r.title or "未命名对话",
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M")
            if r.created_at
            else "",
            "last_message_at": r.last_at.strftime("%Y-%m-%d %H:%M")
            if r.last_at
            else None,
            "message_count": r.msg_count or 0,
        }
        for r in rows
    ]


def count_all(db: Session) -> int:
    return db.query(func.count(ChatSession.session_id)).scalar() or 0
