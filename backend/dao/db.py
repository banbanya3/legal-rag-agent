"""数据库连接管理。

和 Flask-SQLAlchemy 的区别：这里用手动 Session，生命周期在 service 层显式控制。
好处是 SSE 流式响应里可以在生成器内部自己开一个 Session，
不会出现"响应还没结束，Flask 就把请求上下文和连接一起回收了"的经典坑。
"""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from common.logger import get_logger
from config import settings
from dao.models import Base

logger = get_logger("db")

engine = create_engine(
    settings.mysql_url,
    pool_pre_ping=True,   # 取连接前先探活，避免 MySQL 8 小时断连后的 2013 错误
    pool_recycle=1800,    # 提前回收，比 MySQL 的 wait_timeout 更激进
    pool_size=10,
    max_overflow=20,
    echo=False,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
)


def ensure_database() -> None:
    """首次运行自动建库。

    连 MySQL 时如果库不存在，驱动会直接抛 1049，所以这里先连"无库"的
    服务端连接，CREATE DATABASE IF NOT EXISTS 之后再建表。
    """
    server_engine = create_engine(settings.mysql_server_url, future=True)
    db_name = settings.MYSQL_DATABASE
    try:
        with server_engine.connect() as conn:
            conn.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                    "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            )
            conn.commit()
        logger.info("MySQL 数据库 %s 已就绪", db_name)
    finally:
        server_engine.dispose()


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)
    logger.info("MySQL 数据表检查/创建完成（%d 张表）", len(Base.metadata.tables))


@contextmanager
def session_scope():
    """给脚本、初始化流程用的上下文管理器：正常提交、异常回滚、最后关闭。"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def ping() -> tuple[bool, str]:
    """健康检查用：真的发一条 SELECT 1，而不是看连接池里有没有对象。"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "连接正常"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
