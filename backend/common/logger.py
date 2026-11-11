"""极简日志封装。

只用标准库 logging，不引第三方库：项目要"零额外依赖就能跑起来"，
日志这点需求不值得再加一个 loguru。
"""
from __future__ import annotations

import logging
import sys

_FORMAT = "%(asctime)s │ %(levelname)-5s │ %(name)-14s │ %(message)s"
_DATE_FORMAT = "%H:%M:%S"

_configured = False


def _configure() -> None:
    global _configured
    if _configured:
        return

    # 输出到 stderr 而不是 stdout。
    # 原因：MCP 服务的 stdio 传输用 stdout 传 JSON-RPC，
    # 任何写到 stdout 的日志都会把协议帧冲坏，客户端直接报解析错误。
    # 对 Web 服务没影响 —— uvicorn 本来就把访问日志和错误日志分开。
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT))

    root = logging.getLogger("legal")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    root.propagate = False

    # 压掉第三方库的噪音（Milvus 和 httpx 话特别多）
    for noisy in ("httpx", "httpcore", "pymilvus", "urllib3", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    _configure()
    return logging.getLogger(f"legal.{name}")
