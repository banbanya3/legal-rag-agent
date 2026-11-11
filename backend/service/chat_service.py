"""对话业务层：把 Agent 输出的事件流接到持久化上。

FastAPI 版本有三处和 Flask 版不同，都值得留意：

1. **生成器改成 async generator**。
   Flask 版是同步 `def` + `yield`；这里必须是 `async def` + `yield`，
   否则 Starlette 会把它丢进线程池迭代，每个连接占一个线程，
   等于没享受到异步的好处。

2. **同步的 DB 操作要包 `asyncio.to_thread`**。
   SQLAlchemy 用的是同步驱动（pymysql），在 async 函数里直接调用会阻塞事件循环。
   这些操作都是毫秒级，扔线程池完全够。
   用标准库的 `asyncio.to_thread` 而不是 fastapi 的 `run_in_threadpool`，
   是为了让 service 层保持零框架依赖。

3. **断线保存不能 await**。
   客户端断开时任务已经被取消，此时 `await` 会立刻抛 `CancelledError`。
   所以取消路径上的写库操作直接同步执行 —— 反正马上就要退出了，
   阻塞几毫秒可以接受，总比丢掉这轮对话好。
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncGenerator

from common.logger import get_logger
from dao import message_dao, session_dao, setting_dao
from dao.db import SessionLocal
from service import agent_service

logger = get_logger("chat")


def _sse(payload: dict) -> str:
    """SSE 帧格式：data: {...}\\n\\n。前端按 \\n\\n 切帧。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _auto_title(query: str) -> str:
    """首句提问自动生成会话标题。去掉换行和多余空格，截 16 个字。"""
    clean = " ".join((query or "").split())
    return clean[:16] + "…" if len(clean) > 16 else (clean or "新对话")


# ===========================================================================
# 同步的 DB 辅助函数
#
# 抽出来的目的是：让 async 函数里只出现 `await asyncio.to_thread(xxx, ...)` 一行，
# 而不是把 SQLAlchemy 的 commit/flush 混进异步逻辑里。
# ===========================================================================
def _load_setting(db):
    """读全局模型配置，不存在就按 .env 默认值建一行。"""
    cfg = setting_dao.get_or_create(db)
    db.commit()
    return cfg


def prepare_session(db, session_id: str, query: str) -> None:
    """确保会话存在。不存在就用第一句话当标题建一个。"""
    existing = session_dao.get(db, session_id)
    if existing is None:
        session_dao.create(db, session_id, _auto_title(query))
        db.commit()
    else:
        # 每次提问刷新 updated_at，左侧列表才能正确按活跃时间排序
        existing.title = existing.title or _auto_title(query)


def save_turn(
    db, session_id: str, query: str, answer: str, sources: list, elapsed_ms: int
) -> None:
    """一轮问答落库。用户消息和助手消息一起写，保证不会只存半轮。"""
    message_dao.add(db, session_id, "user", query)
    message_dao.add(
        db, session_id, "assistant", answer, sources=sources, elapsed_ms=elapsed_ms
    )
    db.commit()


# ===========================================================================
# 流式对话
# ===========================================================================
async def sse_stream(
    session_id: str,
    query: str,
    use_rerank: bool | None = None,
    direct: bool = False,
) -> AsyncGenerator[str, None]:
    """SSE 主链路。

    事件顺序：
        status(route) -> status(routed) -> status(retrieve) -> sources
        -> status(generate) -> delta* -> answer -> done

    前端据此渲染"思考过程"，用户能看见系统在干什么，
    而不是对着一个转圈干等 5 秒。

    `direct=True` 走直聊模式：跳过路由和检索，直接把问题交给模型。
    落库逻辑完全一样 —— 直聊也是正式对话，不该因为没检索就不存。

    ⚠️ 注意这里**没有**用 `Depends(get_db)` 注入 session。
    FastAPI 的 yield 依赖在「响应开始发送」时就退出了（会执行 finally 里的 close），
    而那时生成器还没开始迭代。所以必须像 Flask 版一样，在生成器内部自己开。
    """
    db = SessionLocal()
    started = time.perf_counter()
    answer_text = ""
    sources: list[dict] = []

    try:
        cfg = await asyncio.to_thread(_load_setting, db)
        await asyncio.to_thread(prepare_session, db, session_id, query)
        history = await asyncio.to_thread(
            message_dao.recent_for_memory, db, session_id, 6
        )

        async for event in agent_service.stream_answer(
            db, cfg, query, history=history, use_rerank=use_rerank, direct=direct
        ):
            # 注意顺序：answer 事件必须先推给前端再 break。
            # 之前写成"先 break 后 yield"，前端永远收不到 answer，
            # 只能收到 done —— 表现就是回答一片空白，但日志里一切正常。
            yield _sse(event)

            event_type = event["type"]

            if event_type == "delta":
                # 逐字累积！这一行是断线保存的前提。
                #
                # 之前的写法只在 answer 事件里赋值 answer_text，
                # 结果用户中途点"停止生成"时（那时还没到 answer），
                # answer_text 仍是空字符串，`if answer_text:` 直接跳过，
                # 整轮对话一条都没存 —— 表现为"停止生成后刷新，这段对话消失了"。
                answer_text += event.get("text", "")

            elif event_type == "answer":
                # answer 里是清洗过的最终版（去了尾部参考资料复述、角标），
                # 用它覆盖掉原始累积文本
                answer_text = event.get("answer", "") or answer_text
                sources = event.get("sources", [])
                break

            elif event_type == "sources":
                sources = event.get("sources", [])

        elapsed = int((time.perf_counter() - started) * 1000)
        await asyncio.to_thread(
            save_turn, db, session_id, query, answer_text, sources, elapsed
        )

        yield _sse({"type": "done", "elapsed_ms": elapsed})

    except (GeneratorExit, asyncio.CancelledError):
        # 用户点了"停止生成"或直接关了页面。
        #
        # 两种异常都要接：
        #   - GeneratorExit：生成器被 aclose() 时在 yield 处抛出
        #   - CancelledError：Starlette 在客户端断开时取消任务
        #
        # 这里**不能**用 await —— 任务已经处于取消状态，
        # 任何 await 都会立刻再抛 CancelledError，代码根本走不到保存那一步。
        # 所以直接同步写库，几毫秒的事。
        logger.info("客户端断开，保存已生成内容（%d 字）", len(answer_text))
        try:
            if answer_text:
                elapsed = int((time.perf_counter() - started) * 1000)
                save_turn(
                    db,
                    session_id,
                    query,
                    answer_text + "\n\n_（已停止生成）_",
                    sources,
                    elapsed,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("断线保存失败：%s", exc)
        raise

    except Exception as exc:  # noqa: BLE001
        logger.exception("对话链路异常")
        db.rollback()
        yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})

    finally:
        db.close()


# ===========================================================================
# 非流式对话
# ===========================================================================
async def chat_once(
    session_id: str, query: str, use_rerank: bool | None = None
) -> dict:
    """非流式对话。给"调试 / 脚本调用 / 单测"用。"""
    db = SessionLocal()
    try:
        cfg = await asyncio.to_thread(_load_setting, db)
        await asyncio.to_thread(prepare_session, db, session_id, query)
        history = await asyncio.to_thread(
            message_dao.recent_for_memory, db, session_id, 6
        )

        result = await agent_service.answer_once(
            db, cfg, query, history, use_rerank
        )

        await asyncio.to_thread(
            save_turn,
            db,
            session_id,
            query,
            result.get("answer", ""),
            result.get("sources", []),
            result.get("elapsed_ms", 0),
        )

        return {
            "session_id": session_id,
            "answer": result.get("answer", ""),
            "sources": result.get("sources", []),
            "elapsed_ms": result.get("elapsed_ms", 0),
        }
    finally:
        db.close()
