"""对话接口。"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from common.result import Result
from schemas.chat_schema import ChatRequest, ChatResponse
from schemas.common import ApiResponse
from service import chat_service

router = APIRouter(prefix="/api/chat", tags=["对话"])

# SSE 必须显式关掉各级缓冲，否则 Nginx / 浏览器会攒够一批才吐给前端，
# "打字机效果"就退化成"等 5 秒一次性出现"。
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@router.post(
    "/stream",
    summary="流式对话（SSE）",
    description=(
        "事件序列：status(route) → status(routed) → status(retrieve) → sources "
        "→ status(generate) → delta* → answer → done。\n\n"
        "每帧格式为 `data: {json}\\n\\n`，前端按空行切帧。"
    ),
    response_class=StreamingResponse,
)
async def chat_stream(payload: ChatRequest):
    """流式问答。

    注意这里**没有** `db: Session = Depends(get_db)` ——
    FastAPI 的 yield 依赖在响应开始发送时就退出并 close，
    而生成器要到那之后才开始迭代。所以 session 在生成器内部自己开，
    详见 service/chat_service.py 的注释。
    """
    return StreamingResponse(
        chat_service.sse_stream(
            payload.session_id, payload.query, payload.use_rerank
        ),
        media_type="text/event-stream; charset=utf-8",
        headers=SSE_HEADERS,
    )


@router.post(
    "/direct/stream",
    summary="直聊模式（SSE，跳过检索）",
    description=(
        "和 `/stream` 的区别：不做意图路由、不检索法条、不精排，"
        "直接把问题交给模型，由它基于通用法律知识回答。\n\n"
        "适合「帮我解释一个法律概念」这类不需要条文依据的场景，"
        "响应快（省掉一次路由调用 + 一次检索 + 一次精排）。"
    ),
    response_class=StreamingResponse,
)
async def chat_direct_stream(payload: ChatRequest):
    return StreamingResponse(
        chat_service.sse_stream(
            payload.session_id, payload.query, payload.use_rerank, direct=True
        ),
        media_type="text/event-stream; charset=utf-8",
        headers=SSE_HEADERS,
    )


@router.post(
    "",
    summary="非流式对话",
    response_model=ApiResponse[ChatResponse],
)
async def chat_once(payload: ChatRequest):
    """一次性返回完整答案。给脚本调用和前端"关闭流式"开关用。"""
    data = await chat_service.chat_once(
        payload.session_id, payload.query, payload.use_rerank
    )
    return Result.ok(data)
