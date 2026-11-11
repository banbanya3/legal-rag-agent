"""系统设置模型。

这里刻意把请求和响应拆成两个模型：
  - `LLMSettingIn` 里有 `api_key`（用户要能改）
  - `LLMSettingOut` 里只有 `api_key_masked`（永远不下发明文）

这不是冗余，是安全边界。混用一个模型的后果是 API Key 会原样返回给浏览器。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LLMSettingIn(BaseModel):
    """POST /api/settings 的请求体。"""

    provider: Literal["zhipu", "deepseek", "qwen", "custom"] = Field(
        default="zhipu", description="厂商标识"
    )
    model_name: str = Field(..., min_length=1, max_length=64, description="模型名称")
    api_key: str | None = Field(
        default=None,
        description="留空表示沿用已保存的 Key —— 避免「打开设置直接保存」把 Key 清空",
    )
    base_url: str = Field(..., min_length=10, description="接口地址")
    temperature: float = Field(default=0.1, ge=0.0, le=1.5, description="采样温度")
    top_k: int = Field(default=8, ge=1, le=30, description="向量召回条数")
    rerank_n: int = Field(default=4, ge=1, le=10, description="精排保留条数")
    use_rerank: bool = Field(default=True, description="是否开启精排")
    strict_mode: bool = Field(default=True, description="严格模式：只依据检索到的法条回答")


class LLMSettingOut(BaseModel):
    """返回给前端的设置（密钥已脱敏）。"""

    provider: str
    model_name: str
    api_key_masked: str = Field(default="", description="如 c61efd********9GK7")
    has_api_key: bool = Field(default=False)
    base_url: str
    temperature: float
    top_k: int
    rerank_n: int
    use_rerank: bool
    strict_mode: bool
    updated_at: str = Field(default="", description="格式 YYYY-MM-DD HH:MM")


class SaveSettingsResult(BaseModel):
    """保存设置后的返回。"""

    message: str
    settings: LLMSettingOut


class LLMTestRequest(BaseModel):
    """POST /api/settings/test 的请求体。"""

    model_name: str = Field(..., min_length=1)
    api_key: str | None = Field(default=None, description="留空则用已保存的 Key")
    base_url: str = Field(..., min_length=10)
    temperature: float = Field(default=0.1, ge=0.0, le=1.5)


class LLMTestResult(BaseModel):
    """连通性测试结果。"""

    success: bool
    message: str
    latency_ms: int | None = Field(default=None, ge=0)
    model_reply: str | None = None


class ModelPreset(BaseModel):
    """模型预设里的一项。"""

    name: str
    label: str
    recommended: bool = False
    reasoning: bool = Field(default=False, description="是否推理型（首字更慢）")


class ProviderPreset(BaseModel):
    """模型厂商预设，前端下拉框数据源。"""

    provider: str
    label: str
    base_url: str
    models: list[ModelPreset] = Field(default_factory=list)
