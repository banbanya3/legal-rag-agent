"""FastAPI 应用入口。

启动方式：

    # 开发（不要在 Milvus Lite 上开 reload，会起两个进程抢库锁）
    cd backend && python main.py
    # 或者
    uvicorn main:app --host 127.0.0.1 --port 8000 --reload

    # 生产
    uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4

启动时会自动做三件事，保证"克隆下来就能跑"：
    1. MySQL 库不存在 -> 建库
    2. 表不存在 -> 建表
    3. 向量库为空 -> 提示先跑 init_knowledge.py（不自动建，因为要花 embedding 费用）
"""
from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# 允许在 PyCharm 里直接右键 Run
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import register_exception_handlers, register_routers
from common.logger import get_logger
from common.result import Result
from config import LAW_DOMAINS, collection_name, settings
from dao import statute_dao
from dao.db import create_tables, ensure_database, session_scope
from rag import milvus_store

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动/关闭钩子。

    替代 Flask 版的 `before_request` + `_db_ready` 标志位组合 ——
    Flask 没有"只执行一次的启动钩子"，那个标志位本质上是个 workaround。
    FastAPI 的 lifespan 是原生支持：yield 之前跑一次，之后跑一次。
    """
    logger.info("正在执行启动自检…")

    try:
        ensure_database()
        create_tables()
        with session_scope() as db:
            total = statute_dao.count_all(db)
        logger.info("启动自检完成，法条表共 %d 条", total)

        vectors = sum(
            milvus_store.count(collection_name(key)) for key in LAW_DOMAINS
        )
        if vectors == 0:
            logger.warning(
                "向量库为空，请先运行：python init_knowledge.py --build"
            )
        else:
            logger.info("向量库就绪，共 %d 条切片", vectors)

        # 预热 BM25：jieba 首次加载词典要 3—5 秒，放在启动时做，用户感知不到。
        # 放在线程里跑是因为它会阻塞几百毫秒到几秒，不该拖慢服务就绪。
        if settings.USE_BM25 and vectors:
            from rag import bm25_index

            await asyncio.to_thread(bm25_index.warmup)
    except Exception as exc:  # noqa: BLE001
        # 数据库没起来也先把服务拉起来，让前端能看到明确的报错，而不是白屏
        logger.error("启动自检失败：%s", exc)

    yield

    logger.info("服务关闭，释放资源")


app = FastAPI(
    title="法眼 · 法律知识库智能问答系统",
    description=(
        "基于 Milvus 向量检索 + 结构化法条库的中国法律问答系统。\n\n"
        "**架构**：路由（1 次 LLM）→ 检索（三路召回 + 精排）→ 生成（1 次 LLM 流式）\n\n"
        "**接口文档**：本页由 FastAPI 自动生成，可直接展开调用。"
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# 开发期前后端分离，必须放行 Vite 的源。
# 生产环境同源部署时可以去掉这段。
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    # SSE 需要浏览器能读到这些响应头
    expose_headers=["Content-Type", "Cache-Control"],
)

register_routers(app)
register_exception_handlers(app)


@app.get("/", tags=["根路径"], summary="服务信息")
async def index():
    return Result.ok(
        {
            "name": "法律知识库智能问答系统",
            "version": "1.0.0",
            "framework": "FastAPI",
            "docs": "/docs",
            "health": "/api/health",
            "frontend": "Vue3 前端请访问 http://localhost:5173",
        }
    )


if __name__ == "__main__":
    import uvicorn

    print(
        f"""
╭──────────────────────────────────────────────────────────╮
│  法律知识库智能问答系统（FastAPI）                 │
│  接口文档: http://{settings.HOST}:{settings.PORT}/docs               │
│  健康检查: http://{settings.HOST}:{settings.PORT}/api/health         │
│  前端地址: http://localhost:5173                          │
╰──────────────────────────────────────────────────────────╯
"""
    )
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        # 不开 reload：reloader 会起两个进程，第二个抢不到 Milvus Lite 的库锁。
        # 同理，多 worker 部署前要先把向量库换成 Milvus Standalone。
        reload=False,
        log_level="info",
    )
