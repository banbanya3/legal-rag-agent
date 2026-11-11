"""知识文件索引台账数据访问。"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from dao.models import KnowledgeDoc


def get(db: Session, domain: str, filename: str) -> KnowledgeDoc | None:
    return (
        db.query(KnowledgeDoc)
        .filter(KnowledgeDoc.domain == domain, KnowledgeDoc.filename == filename)
        .first()
    )


def upsert(
    db: Session,
    domain: str,
    filename: str,
    file_hash: str,
    char_count: int,
    chunk_count: int,
    article_count: int,
) -> KnowledgeDoc:
    row = get(db, domain, filename)
    if row is None:
        row = KnowledgeDoc(domain=domain, filename=filename)
        db.add(row)
    row.file_hash = file_hash
    row.char_count = char_count
    row.chunk_count = chunk_count
    row.article_count = article_count
    db.flush()
    return row


def delete(db: Session, domain: str, filename: str) -> int:
    deleted = (
        db.query(KnowledgeDoc)
        .filter(KnowledgeDoc.domain == domain, KnowledgeDoc.filename == filename)
        .delete(synchronize_session=False)
    )
    db.flush()
    return deleted
def summary_by_domain(db: Session) -> dict[str, dict]:
    rows = (
        db.query(
            KnowledgeDoc.domain,
            func.count(KnowledgeDoc.id),
            func.coalesce(func.sum(KnowledgeDoc.chunk_count), 0),
            func.coalesce(func.sum(KnowledgeDoc.article_count), 0),
            func.coalesce(func.sum(KnowledgeDoc.char_count), 0),
        )
        .group_by(KnowledgeDoc.domain)
        .all()
    )
    return {
        domain: {
            "docs": docs,
            "chunks": int(chunks),
            "articles": int(articles),
            "chars": int(chars),
        }
        for domain, docs, chunks, articles, chars in rows
    }


def count_docs(db: Session) -> int:
    return db.query(func.count(KnowledgeDoc.id)).scalar() or 0
