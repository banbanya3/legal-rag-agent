"""FastAPI 依赖注入。

和 Flask 版的 `flask.g` 相比，这里的思路从"命令式调用"变成了"声明式注入"：

    # Flask：函数体里主动拿
    def domains():
        db = get_db()
        ...

    # FastAPI：签名里声明，框架替你调
    async def domains(db: Session = Depends(get_db)):
        ...

`Depends` 的本质不是依赖注入框架 —— 它只是个"参数预处理器"：
框架在调用你的函数之前先调 `get_db()`，把 yield 出来的值塞进参数。
没有容器、没有 bean 生命周期管理。

⚠️ 流式接口不要用这个依赖，原因见 `service/chat_service.py` 的注释：
FastAPI 的 yield 依赖在响应开始发送时就退出，那时生成器还没开始迭代。
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.orm import Session

from dao.db import SessionLocal


def get_db() -> Generator[Session, None, None]:
    """请求级 Session：路由函数执行前打开，响应结束后关闭。

    `yield` 之前是准备，`yield` 之后是清理 —— 这一段 FastAPI 会自动
    在请求结束时执行（即使处理过程中抛了异常）。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
