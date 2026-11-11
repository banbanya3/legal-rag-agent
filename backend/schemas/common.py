"""统一响应信封的泛型模型。

后端所有接口都返回 `{code, message, data}` 三层结构。
用泛型包一层，好处是 `/docs` 里能展开看到 `data` 的具体结构，
而不是显示成一个 `object`。

用法：

    @router.get("/laws", response_model=ApiResponse[list[LawInfo]])
    async def list_laws(...):
        return Result.ok(...)
"""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = Field(default=0, description="0 表示成功，非 0 为业务错误码")
    message: str = Field(default="success", description="人类可读的提示")
    data: T | None = Field(default=None, description="业务数据")
