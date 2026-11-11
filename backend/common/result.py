"""统一响应结构与业务异常。

为什么要有这一层：
前端 axios 拦截器只需要认 {code, message, data} 一种形状，
不用为每个接口写不同的错误处理；后端抛业务异常时也不用层层 try/except，
交给 Flask 的 errorhandler 统一兜底。
"""
from __future__ import annotations

from typing import Any


class Result:
    """成功响应。HTTP 状态码固定 200，业务码放 body 里。"""

    @staticmethod
    def ok(data: Any = None, message: str = "success") -> dict:
        return {"code": 0, "message": message, "data": data}

    @staticmethod
    def fail(message: str, code: int = 1, data: Any = None) -> dict:
        return {"code": code, "message": message, "data": data}


class BizError(Exception):
    """可预期的业务错误（用户输入错、资源不存在、参数越界）。

    这类错误不需要打堆栈，只需要把 message 原样告诉前端。
    """

    def __init__(self, message: str, code: int = 1, status: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


class NotFoundError(BizError):
    def __init__(self, message: str = "资源不存在"):
        super().__init__(message, code=404, status=404)


class PermissionDeniedError(BizError):
    def __init__(self, message: str = "没有权限执行该操作"):
        super().__init__(message, code=403, status=403)
