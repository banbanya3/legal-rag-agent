"""法条检索模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from schemas.chat_schema import SourceItem


class StatuteQuery(BaseModel):
    """GET /api/statutes 的查询参数。

    FastAPI 里查询参数既可以一个个写 `Query(...)`，
    也可以像这样用 `Depends()` 注入一个模型 —— 后者更适合参数多、
    且要在多个接口复用的场景。
    """

    keyword: str = Field(default="", max_length=50, description="匹配条文正文与标题")
    law_name: str = Field(default="", max_length=64, description="法律名模糊匹配")
    domain: str = Field(default="", max_length=32, description="领域 key，空为全部")
    page: int = Field(default=1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(default=20, ge=1, le=100, description="每页条数")


class StatuteItem(BaseModel):
    """一条法条。"""

    id: int
    law_name: str = Field(description="法律全称")
    law_short: str = Field(default="", description="简称")
    domain: str = Field(default="", description="领域 key")
    domain_label: str = Field(default="", description="领域中文名")
    chapter: str = Field(default="", description="所属编/章")
    article_no: str = Field(description="条号，如 第十九条")
    heading: str = Field(default="", description="条文主旨")
    content: str = Field(description="条文原文")
    effective_date: str = Field(default="", description="施行日期")
    source_file: str = Field(default="", description="来源知识文件")


class StatutePage(BaseModel):
    """分页结果。"""

    total: int = Field(ge=0, description="命中总数")
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    items: list[StatuteItem] = Field(default_factory=list)


class LawInfo(BaseModel):
    """法律清单里的一项。"""

    law_name: str
    law_short: str
    domain: str
    domain_label: str = ""
    article_count: int = Field(default=0, ge=0)


class DomainStat(BaseModel):
    """按领域的法条统计。"""

    domain: str
    label: str
    color: str = ""
    articles: int = Field(default=0, ge=0)
    laws: int = Field(default=0, ge=0)


class StatuteOverview(BaseModel):
    """GET /api/statutes/overview 的返回。"""

    total_articles: int = Field(default=0, ge=0)
    total_laws: int = Field(default=0, ge=0)
    by_domain: list[DomainStat] = Field(default_factory=list)
    laws: list[LawInfo] = Field(default_factory=list)


class SemanticSearchResult(BaseModel):
    """GET /api/statutes/semantic 的返回。

    和 `StatutePage` 的区别：那边是关键词匹配的精确结果（有条号、有原文），
    这边是语义召回（可能包含"解读段落"，用 SourceItem 统一表达）。
    """

    query: str = Field(description="原始查询")
    domain: str = Field(default="", description="限定的领域，空表示全库")
    total: int = Field(default=0, ge=0)
    items: list[SourceItem] = Field(default_factory=list)
