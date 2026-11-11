"""路由注册表 + 全局异常处理。

集中在这里 import，main.py 只调两个函数 —— 新增模块时只改这个文件，
不会出现"写了接口但忘了注册"的低级错误。
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from common.logger import get_logger
from common.result import BizError, Result

logger = get_logger("api")


def register_routers(app: FastAPI) -> None:
    from api import (
        chat_api,
        knowledge_api,
        session_api,
        settings_api,
        statute_api,
        system_api,
    )

    for module in (
        chat_api,
        session_api,
        statute_api,
        knowledge_api,
        settings_api,
        system_api,
    ):
        app.include_router(module.router)
        logger.info("已挂载路由：%s", module.router.prefix)


def register_exception_handlers(app: FastAPI) -> None:
    """统一错误出口。

    四类异常分开处理，目标是让前端拿到的 message 始终是"人话"：

    - BizError：业务主动抛的，原样返回，不打堆栈
    - RequestValidationError：Pydantic 校验失败，压成一句可读提示
    - HTTPException：404 / 405 这类，保持状态码
    - 其它：打完整堆栈到日志，只给前端一句概括，不泄露内部细节
    """

    @app.exception_handler(BizError)
    async def handle_biz_error(request: Request, exc: BizError):
        return JSONResponse(
            status_code=exc.status,
            content=Result.fail(exc.message, exc.code),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ):
        """把 Pydantic 的 422 结构压成和业务错误统一的信封。

        不加这个 handler 的话，前端会收到：

            {"detail": [{"type": "string_too_short",
                         "loc": ["body", "query"],
                         "msg": "String should have at least 1 character"}]}

        而前端的 axios 拦截器是按 `{code, message, data}` 解析的，
        看到没有 `code` 字段会当成成功响应放过去 —— 表现就是"明明报错了，
        界面却显示成功"。
        """
        errors = exc.errors()
        first = errors[0] if errors else {}

        # loc 形如 ("body", "query") 或 ("query", "page")
        # [1:] 跳过 "body"/"query" 这一层，只留字段名
        loc = [str(x) for x in first.get("loc", [])]
        field = ".".join(loc[1:]) if len(loc) > 1 else (loc[0] if loc else "参数")
        msg = first.get("msg", "格式不正确")

        return JSONResponse(
            status_code=400,
            content=Result.fail(f"参数 {field} 不合法：{msg}", 400),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=Result.fail(exc.detail or "请求失败", exc.status_code),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception):
        logger.exception("未捕获异常：%s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=Result.fail(
                f"服务器内部错误：{type(exc).__name__}: {exc}", 500
            ),
        )
