"""法条业务层：结构化查询、法律清单、条文详情。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from common.result import BizError, NotFoundError
from config import LAW_DOMAINS
from dao import setting_dao, statute_dao


def search(
    db: Session,
    keyword: str = "",
    law_name: str = "",
    domain: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    if page < 1:
        page = 1
    page_size = min(max(page_size, 1), 100)

    data = statute_dao.search(
        db, keyword=keyword, law_name=law_name, domain=domain,
        page=page, page_size=page_size,
    )

    # 补上领域中文名，前端不用自己维护一份映射表
    for item in data["items"]:
        item["domain_label"] = LAW_DOMAINS.get(item["domain"], {}).get("label", "")
    return data


def list_laws(db: Session, domain: str = "") -> list[dict]:
    laws = statute_dao.list_laws(db)
    if domain:
        laws = [law for law in laws if law["domain"] == domain]
    for law in laws:
        law["domain_label"] = LAW_DOMAINS.get(law["domain"], {}).get("label", "")
    return laws


def get_article(db: Session, law_name: str, article_no: str) -> dict:
    if not law_name.strip() or not article_no.strip():
        raise BizError("法律名称和条号都不能为空")

    row = statute_dao.find_by_article(db, law_name, article_no)
    if row is None:
        raise NotFoundError(f"未收录：{law_name} {article_no}")

    data = statute_dao.to_dict(row)
    data["domain_label"] = LAW_DOMAINS.get(row.domain, {}).get("label", "")
    return data


def overview(db: Session) -> dict:
    """法条库总览，给首页卡片用。"""
    counts = statute_dao.count_by_domain(db)
    laws = statute_dao.list_laws(db)

    by_domain = []
    for key, meta in LAW_DOMAINS.items():
        by_domain.append(
            {
                "domain": key,
                "label": meta["label"],
                "color": meta["color"],
                "articles": counts.get(key, 0),
                "laws": len([law for law in laws if law["domain"] == key]),
            }
        )

    return {
        "total_articles": statute_dao.count_all(db),
        "total_laws": len(laws),
        "by_domain": by_domain,
        "laws": laws,
    }


def semantic_search(
    db: Session,
    query: str,
    domain: str | None = None,
    top_k: int = 6,
    use_rerank: bool = True,
) -> dict:
    """语义检索法条（走向量库 + 精排），不生成答案。

    和 `search()` 的区别：

        search()          关键词/法律名过滤，走 MySQL LIKE，精确但只认字面
        semantic_search() 把问题转成向量，召回"意思相近"的条文，能处理口语

    这个接口是给 MCP 服务用的 —— MCP server 是独立进程，如果它自己去开 Milvus，
    会和主服务抢库锁（Milvus Lite 单进程独占）。所以让它走 HTTP 调这里，
    由主服务统一持有向量库连接。

    参数：
        domain：限定在某个法律领域里检索，空表示全库
        top_k ：返回多少条（内部会先粗排再精排，实际保留数不会超过它）
    """
    # 延迟导入：避免 statute_service 在 import 阶段就拉起向量库依赖，
    # 法条列表这类纯 DB 接口不需要 Milvus
    from rag.retriever import retrieve, to_source_payload

    cfg = setting_dao.get_or_create(db)
    db.commit()

    hits = retrieve(
        db,
        query,
        domain=domain or None,
        top_k=max(top_k, 4),          # 粗排至少捞 4 条，否则精排没得选
        rerank_n=min(top_k, 4),
        use_rerank=use_rerank,
        api_key=cfg.api_key,
    )

    return {
        "query": query,
        "domain": domain or "",
        "total": len(hits),
        "items": to_source_payload(hits),
    }
