"""系统状态业务层：健康检查与数据概览。"""
from __future__ import annotations

import platform
import sys
from datetime import datetime

from sqlalchemy.orm import Session

from config import LAW_DOMAINS, collection_name, settings
from dao import knowledge_dao, message_dao, session_dao, statute_dao
from dao.db import ping as ping_mysql
from rag import milvus_store
from service import knowledge_service


def health(db: Session) -> dict:
    """三件事都要真的探一次，不能"看配置猜状态"。

    MySQL 发 SELECT 1，Milvus 数一下集合行数，模型只报配置不真调用
    （真调用要花钱，放到设置面板的"测试连接"里由用户主动触发）。
    """
    mysql_ok, mysql_msg = ping_mysql()

    milvus_ok, milvus_msg, vectors = True, "连接正常", 0
    try:
        for key in LAW_DOMAINS:
            vectors += milvus_store.count(collection_name(key))
    except Exception as exc:  # noqa: BLE001
        milvus_ok, milvus_msg = False, f"{type(exc).__name__}: {exc}"

    return {
        "status": "ok" if mysql_ok and milvus_ok else "degraded",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mysql": {"ok": mysql_ok, "message": mysql_msg},
        "milvus": {
            "ok": milvus_ok,
            "message": milvus_msg,
            "vectors": vectors,
            "mode": "Lite（嵌入式）" if "://" not in settings.MILVUS_URI else "Standalone",
        },
        "python": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.release()}",
        "storage_mb": knowledge_service.storage_size_mb(),
    }


def stats(db: Session) -> dict:
    """首页数据概览。一次请求把所有卡片要的数字都算完，
    省得前端连发五六个接口。"""
    sessions = session_dao.count_all(db)
    msg_stats = message_dao.stats(db)
    trend = message_dao.trend_last_days(db, 7)

    domains = knowledge_service.domain_overview(db)
    statute_counts = statute_dao.count_by_domain(db)

    for item in domains:
        item["statutes"] = statute_counts.get(item["domain"], 0)

    total_chunks = sum(item["vectors"] for item in domains)
    total_articles = sum(item["statutes"] for item in domains)
    total_docs = knowledge_dao.count_docs(db)

    return {
        "sessions": sessions,
        "messages": msg_stats["total_messages"],
        "user_messages": msg_stats["user_messages"],
        "assistant_messages": msg_stats["assistant_messages"],
        "today_messages": msg_stats["today_messages"],
        "avg_elapsed_ms": msg_stats["avg_elapsed_ms"],
        "avg_per_session": round(msg_stats["total_messages"] / sessions, 1)
        if sessions
        else 0,
        "trend": trend,
        "knowledge": {
            "domains": len(LAW_DOMAINS),
            "docs": total_docs,
            "chunks": total_chunks,
            "articles": total_articles,
            "storage_mb": knowledge_service.storage_size_mb(),
        },
        "domains": domains,
    }
