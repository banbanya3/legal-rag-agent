"""系统状态模型：健康检查与数据概览。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from schemas.knowledge_schema import DomainInfo


class ComponentStatus(BaseModel):
    """单个依赖组件的探活结果。"""

    ok: bool
    message: str = ""


class MilvusStatus(ComponentStatus):
    """Milvus 探活，额外带切片数与运行模式。"""

    vectors: int = Field(default=0, ge=0)
    mode: str = Field(default="", description="Lite（嵌入式）/ Standalone")


class HealthResult(BaseModel):
    """GET /api/health 的返回。"""

    status: str = Field(description="ok / degraded")
    time: str = ""
    mysql: ComponentStatus
    milvus: MilvusStatus
    python: str = ""
    platform: str = ""
    storage_mb: float = Field(default=0, ge=0)


class TrendPoint(BaseModel):
    """近 7 天消息量的一个点。"""

    date: str = Field(description="格式 MM-DD")
    count: int = Field(default=0, ge=0)


class KnowledgeStat(BaseModel):
    """知识库规模汇总。"""

    domains: int = Field(default=0, ge=0)
    docs: int = Field(default=0, ge=0)
    chunks: int = Field(default=0, ge=0)
    articles: int = Field(default=0, ge=0)
    storage_mb: float = Field(default=0, ge=0)


class StatsResult(BaseModel):
    """GET /api/stats 的返回。前端首页的卡片和趋势图都吃这一份数据。"""

    sessions: int = Field(default=0, ge=0, description="会话总数")
    messages: int = Field(default=0, ge=0, description="消息总数")
    user_messages: int = Field(default=0, ge=0)
    assistant_messages: int = Field(default=0, ge=0)
    today_messages: int = Field(default=0, ge=0)
    avg_elapsed_ms: int = Field(default=0, ge=0, description="平均单轮耗时")
    avg_per_session: float = Field(default=0, ge=0, description="人均消息数")
    trend: list[TrendPoint] = Field(default_factory=list)
    knowledge: KnowledgeStat = Field(default_factory=KnowledgeStat)
    domains: list[DomainInfo] = Field(default_factory=list)
