"""结构化法条数据访问。

这张表的定位是"确定性查询"：用户明确说了哪部法、第几条，
就不该让向量检索去猜，直接走主键式的精确匹配。
"""
from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from dao.models import StatuteArticle


def bulk_upsert(db: Session, law_name: str, records: Iterable[dict]) -> int:
    """按 (法律名, 条号) 覆盖写入，保证重复初始化不会产生重复行。

    没有用 MySQL 的 ON DUPLICATE KEY：那需要建唯一索引 + 方言写法，
    这里数据量只有几千条，先查已有条号再决定 insert/update 更直白，
    也方便以后换数据库。
    """
    existing = {
        row.article_no: row
        for row in db.query(StatuteArticle)
        .filter(StatuteArticle.law_name == law_name)
        .all()
    }

    written = 0
    for rec in records:
        article_no = rec.get("article_no")
        if not article_no:
            continue
        row = existing.get(article_no)
        if row is None:
            row = StatuteArticle(law_name=law_name, article_no=article_no, content="")
            db.add(row)
        row.law_short = rec.get("law_short") or row.law_short
        row.domain = rec.get("domain") or row.domain
        row.chapter = rec.get("chapter") or row.chapter
        row.article_index = rec.get("article_index") or row.article_index
        row.heading = rec.get("heading") or row.heading
        row.content = rec.get("content") or row.content
        row.effective_date = rec.get("effective_date") or row.effective_date
        row.source_file = rec.get("source_file") or row.source_file
        written += 1

    db.flush()
    return written


def find_by_article(
    db: Session, law_name: str, article_no: str
) -> Optional[StatuteArticle]:
    return (
        db.query(StatuteArticle)
        .filter(
            StatuteArticle.law_name.like(f"%{law_name}%"),
            StatuteArticle.article_no == article_no,
        )
        .first()
    )


def search(
    db: Session,
    keyword: str = "",
    law_name: str = "",
    domain: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """法条检索页用的分页查询。关键词同时匹配条文正文和条目标题。"""
    query = db.query(StatuteArticle)

    if keyword.strip():
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(StatuteArticle.content.like(like), StatuteArticle.heading.like(like))
        )
    if law_name.strip():
        query = query.filter(StatuteArticle.law_name.like(f"%{law_name.strip()}%"))
    if domain.strip():
        query = query.filter(StatuteArticle.domain == domain.strip())

    total = query.count()
    rows = (
        query.order_by(
            StatuteArticle.domain.asc(),
            StatuteArticle.law_name.asc(),
            StatuteArticle.article_index.asc(),
        )
        .offset(max(page - 1, 0) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [to_dict(r) for r in rows],
    }


def list_laws(db: Session) -> list[dict]:
    """所有已收录的法律及条数，给前端下拉框用。"""
    rows = (
        db.query(
            StatuteArticle.law_name,
            StatuteArticle.law_short,
            StatuteArticle.domain,
            func.count(StatuteArticle.id).label("cnt"),
        )
        .group_by(StatuteArticle.law_name, StatuteArticle.law_short, StatuteArticle.domain)
        .order_by(StatuteArticle.domain.asc(), StatuteArticle.law_name.asc())
        .all()
    )
    return [
        {
            "law_name": r.law_name,
            "law_short": r.law_short or r.law_name,
            "domain": r.domain,
            "article_count": r.cnt,
        }
        for r in rows
    ]


def count_by_domain(db: Session) -> dict[str, int]:
    rows = (
        db.query(StatuteArticle.domain, func.count(StatuteArticle.id))
        .group_by(StatuteArticle.domain)
        .all()
    )
    return {domain: cnt for domain, cnt in rows}


def count_all(db: Session) -> int:
    return db.query(func.count(StatuteArticle.id)).scalar() or 0


def delete_by_source(db: Session, source_file: str) -> int:
    deleted = (
        db.query(StatuteArticle)
        .filter(StatuteArticle.source_file == source_file)
        .delete(synchronize_session=False)
    )
    db.flush()
    return deleted


def to_dict(row: StatuteArticle) -> dict:
    return {
        "id": row.id,
        "law_name": row.law_name,
        "law_short": row.law_short or row.law_name,
        "domain": row.domain,
        "chapter": row.chapter or "",
        "article_no": row.article_no,
        "heading": row.heading or "",
        "content": row.content,
        "effective_date": row.effective_date or "",
        "source_file": row.source_file or "",
    }
