"""法条检索接口（结构化查询，不经过大模型）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.deps import get_db
from common.result import Result
from schemas.common import ApiResponse
from schemas.statute_schema import (
    LawInfo,
    SemanticSearchResult,
    StatuteItem,
    StatuteOverview,
    StatutePage,
)
from service import statute_service

router = APIRouter(prefix="/api/statutes", tags=["法条检索"])


@router.get(
    "",
    summary="分页检索法条",
    response_model=ApiResponse[StatutePage],
)
def search_statutes(
    keyword: str = Query(default="", max_length=50, description="匹配条文正文与标题"),
    law_name: str = Query(default="", max_length=64, description="法律名模糊匹配"),
    domain: str = Query(default="", max_length=32, description="领域 key"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    data = statute_service.search(
        db,
        keyword=keyword,
        law_name=law_name,
        domain=domain,
        page=page,
        page_size=page_size,
    )
    return Result.ok(data)


@router.get(
    "/laws",
    summary="已收录的法律清单",
    response_model=ApiResponse[list[LawInfo]],
)
def list_laws(
    domain: str = Query(default="", max_length=32),
    db: Session = Depends(get_db),
):
    return Result.ok(statute_service.list_laws(db, domain))


@router.get(
    "/overview",
    summary="法条库总览",
    response_model=ApiResponse[StatuteOverview],
)
def overview(db: Session = Depends(get_db)):
    return Result.ok(statute_service.overview(db))


@router.get(
    "/semantic",
    summary="语义检索法条（走向量库 + 精排）",
    response_model=ApiResponse[SemanticSearchResult],
    description=(
        "把问题转成向量召回意思相近的条文，能处理口语（如「老板不给加班费」）。"
        "和 `/api/statutes` 的区别是：那个走关键词 LIKE，只认字面。\n\n"
        "这个接口主要供 MCP 服务调用 —— MCP 是独立进程，自己开 Milvus 会和主服务抢库锁。"
    ),
)
def semantic_search(
    query: str = Query(..., min_length=1, max_length=200, description="自然语言查询"),
    domain: str = Query(default="", max_length=32, description="限定领域，空为全库"),
    top_k: int = Query(default=6, ge=1, le=12, description="返回条数"),
    use_rerank: bool = Query(default=True, description="是否开启精排"),
    db: Session = Depends(get_db),
):
    data = statute_service.semantic_search(
        db, query, domain=domain or None, top_k=top_k, use_rerank=use_rerank
    )
    return Result.ok(data)


@router.get(
    "/{law_name}/{article_no}",
    summary="精确取某一条",
    response_model=ApiResponse[StatuteItem],
    description="law_name 支持模糊，传简称即可，如 `/api/statutes/劳动合同法/第十九条`",
)
def get_article(law_name: str, article_no: str, db: Session = Depends(get_db)):
    return Result.ok(statute_service.get_article(db, law_name, article_no))
