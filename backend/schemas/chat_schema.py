"""Chat / 对话相关模型。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ===========================================================================
# 请求
# ===========================================================================
class ChatRequest(BaseModel):
    """POST /api/chat 与 /api/chat/stream 的请求体。"""

    session_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="会话 ID，前端生成；后端不存在时会自动创建",
        examples=["s_abc123def456"],
    )
    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="用户问题",
        examples=["试用期最长可以约定多久？"],
    )
    use_rerank: bool = Field(
        default=True,
        description="是否开启精排；不传则用服务端保存的配置",
    )

    # 前端多传字段（如埋点参数）不报错
    model_config = ConfigDict(extra="ignore")


class DirectChatRequest(BaseModel):
    """直聊模式请求体：跳过检索，纯模型回答。"""

    session_id: str = Field(..., min_length=1, max_length=64)
    query: str = Field(..., min_length=1, max_length=2000)
    history_limit: int = Field(
        default=10, ge=0, le=40, description="携带多少条历史消息"
    )


# ===========================================================================
# 响应子结构
# ===========================================================================
class SourceItem(BaseModel):
    """一条"引用的法条"，对应 rag.retriever.to_source_payload() 的产出。"""

    title: str = Field(description="展示用标题，如《劳动合同法》第十九条【试用期期限】")
    text: str = Field(description="条文原文或解读片段")
    score: float | None = Field(
        default=None, description="向量余弦相似度，前端显示成百分比"
    )
    rerank_score: float | None = Field(
        default=None, description="精排分，仅内部排序参考"
    )
    law_name: str = Field(default="", description="法律全称")
    article_no: str = Field(default="", description="条号，如 第十九条")
    domain: str = Field(default="", description="法律领域 key")
    domain_label: str = Field(default="", description="领域中文名")
    filename: str = Field(default="", description="来源文件名")
    kind: Literal["article", "passage"] = Field(
        default="passage", description="article=条文原文，passage=解读段落"
    )
    reranked: bool = Field(default=False, description="是否经过精排")
    source: Literal["vector", "expanded", "structured"] = Field(
        default="vector", description="召回通道"
    )


class ChatResponse(BaseModel):
    """非流式对话响应。"""

    session_id: str
    answer: str
    sources: list[SourceItem] = Field(default_factory=list)
    elapsed_ms: int = Field(default=0, ge=0, description="本轮耗时（毫秒）")


# ===========================================================================
# SSE 事件结构（不用于 response_model，只做文档与单测校验）
# ===========================================================================
class StreamEvent(BaseModel):
    """SSE 单帧。

    SSE 是手动拼 `data: {...}\\n\\n` 的，不走 FastAPI 的序列化，
    所以这个模型不挂在 `response_model` 上。
    它的作用是：① 把帧格式文档化；② 写单测时校验帧内容。
    """

    type: Literal["status", "sources", "delta", "answer", "done", "error"]
    stage: str | None = None
    message: str | None = None
    text: str | None = None
    answer: str | None = None
    sources: list[SourceItem] | None = None
    elapsed_ms: int | None = None
    intent: str | None = None
    domain: str | None = None
    rewritten: str | None = None
