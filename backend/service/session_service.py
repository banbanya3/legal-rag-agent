"""会话业务层。"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from common.result import BizError, NotFoundError
from dao import message_dao, session_dao


def list_sessions(db: Session, keyword: str = "", limit: int = 200) -> list[dict]:
    return session_dao.list_with_stats(db, keyword=keyword, limit=min(limit, 500))


def create_session(db: Session) -> dict:
    session_id = f"s_{uuid.uuid4().hex[:16]}"
    session_dao.create(db, session_id, "新对话")
    db.commit()
    return {"session_id": session_id, "title": "新对话"}


def get_messages(db: Session, session_id: str) -> list[dict]:
    return message_dao.list_by_session(db, session_id)


def rename(db: Session, session_id: str, title: str) -> dict:
    title = (title or "").strip()
    if not title:
        raise BizError("标题不能为空")
    if len(title) > 60:
        raise BizError("标题最多 60 个字")

    if not session_dao.rename(db, session_id, title):
        raise NotFoundError("会话不存在")
    db.commit()
    return {"session_id": session_id, "title": title}


def delete(db: Session, session_id: str) -> dict:
    session_dao.delete(db, session_id)
    db.commit()
    return {"session_id": session_id}


def clear_messages(db: Session, session_id: str) -> dict:
    count = message_dao.clear(db, session_id)
    db.commit()
    return {"deleted": count}
