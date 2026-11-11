"""消息数据访问。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from common.logger import get_logger
from dao.models import ChatMessage

logger = get_logger("message")

# 推理模型思维链里的高频短语。正常的法律回答不会出现这些，
# 一旦出现基本可以确定是 reasoning_content 被误存成了答案。
_REASONING_MARKERS = (
    "the user is asking",
    "let me draft",
    "let me think",
    "let me check",
    "i should not",
    "looking at the conversation",
    "note: the",
    "wait, the",
    "okay, the user",
)


def _looks_like_reasoning_leak(text: str) -> bool:
    """判断一条历史消息是不是推理模型的思维链被误存成了答案。

    背景：早期版本在 content 为空时回退用了 reasoning_content，导致整段英文
    思考过程被当成答案存进数据库。这些脏数据如果继续作为历史喂回模型，
    模型会认为"自己"就是这么说话的，下一轮继续用英文自言自语、自我纠正，
    会话越聊越离谱。

    这里做的是"读时过滤"而不是"写时清理"：已经污染的历史不用改数据库，
    但不会再喂给模型。前端展示历史时仍然能看见原文（用户可以自己判断）。
    """
    if not text or len(text) < 300:
        return False

    lowered = text.lower()
    if any(marker in lowered for marker in _REASONING_MARKERS):
        return True

    # 英文草稿的另一个特征：整段英文占比很高。
    # 正常中文回答里夹几个英文术语不会超过 40%。
    ascii_letters = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    return ascii_letters / len(text) > 0.4


def add(
    db: Session,
    session_id: str,
    role: str,
    content: str,
    sources: Optional[list] = None,
    elapsed_ms: int = 0,
) -> ChatMessage:
    obj = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        sources_json=json.dumps(sources, ensure_ascii=False) if sources else None,
        elapsed_ms=elapsed_ms,
    )
    db.add(obj)
    db.flush()
    return obj


def list_by_session(db: Session, session_id: str) -> list[dict]:
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .all()
    )
    result = []
    for r in rows:
        sources = []
        if r.sources_json:
            try:
                sources = json.loads(r.sources_json)
            except (ValueError, TypeError):
                sources = []
        result.append(
            {
                "id": r.id,
                "role": r.role,
                "content": r.content,
                "sources": sources,
                "elapsed_ms": r.elapsed_ms or 0,
                "created_at": r.created_at.strftime("%H:%M") if r.created_at else "",
            }
        )
    return result


def recent_for_memory(db: Session, session_id: str, limit: int = 20) -> list[dict]:
    """取最近 N 条给记忆滑窗用。倒序取再翻转，保证时间顺序正确。

    顺带过滤掉疑似思维链泄漏的助手消息 —— 见 `_looks_like_reasoning_leak` 的说明。
    这类脏数据留在历史里会持续污染后续对话，比一次答错影响大得多。
    """
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(limit)
        .all()
    )
    rows.reverse()

    result: list[dict] = []
    for row in rows:
        content = row.content or ""
        if row.role == "assistant" and _looks_like_reasoning_leak(content):
            logger.warning(
                "历史消息 id=%s 疑似思维链泄漏，已跳过不喂给模型", row.id
            )
            continue
        result.append({"role": row.role, "content": content})
    return result


def clear(db: Session, session_id: str) -> int:
    deleted = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .delete(synchronize_session=False)
    )
    db.flush()
    return deleted


def stats(db: Session) -> dict:
    total = db.query(func.count(ChatMessage.id)).scalar() or 0
    user_total = (
        db.query(func.count(ChatMessage.id))
        .filter(ChatMessage.role == "user")
        .scalar()
        or 0
    )

    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today = (
        db.query(func.count(ChatMessage.id))
        .filter(ChatMessage.created_at >= today_start)
        .scalar()
        or 0
    )

    avg_elapsed = (
        db.query(func.avg(ChatMessage.elapsed_ms))
        .filter(ChatMessage.role == "assistant", ChatMessage.elapsed_ms > 0)
        .scalar()
    )

    return {
        "total_messages": total,
        "user_messages": user_total,
        "assistant_messages": total - user_total,
        "today_messages": today,
        "avg_elapsed_ms": int(avg_elapsed) if avg_elapsed else 0,
    }


def trend_last_days(db: Session, days: int = 7) -> list[dict]:
    """近 N 天每日消息量，缺数据的日期补 0（前端画折线图要连续的点）。"""
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = today_start - timedelta(days=days - 1)

    rows = (
        db.query(
            func.date(ChatMessage.created_at).label("day"),
            func.count(ChatMessage.id),
        )
        .filter(ChatMessage.created_at >= start)
        .group_by(func.date(ChatMessage.created_at))
        .all()
    )
    counted = {str(day): cnt for day, cnt in rows}

    series = []
    for offset in range(days):
        day = (start + timedelta(days=offset)).date()
        series.append(
            {"date": day.strftime("%m-%d"), "count": counted.get(str(day), 0)}
        )
    return series
