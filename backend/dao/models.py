"""SQLAlchemy ORM 模型（数据层的唯一真相来源）。

四张表分工：
- chat_session / chat_message：对话与会话，撑起"永久记忆 + 历史列表"
- statute_article：结构化法条库，支撑"按条号精确查询"和"统计类问题"
- knowledge_doc：知识文件索引台账，支撑增量构建与知识库面板
- system_setting：全局唯一一行，存当前生效的模型配置
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class ChatSession(Base):
    """会话表。一条记录 = 左侧边栏里的一个对话。"""

    __tablename__ = "chat_session"

    session_id = Column(String(64), primary_key=True, comment="前端生成的会话 UUID")
    title = Column(String(128), default="新对话", comment="取首句提问自动截断")
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(
        DateTime, default=datetime.now, onupdate=datetime.now, index=True
    )


class ChatMessage(Base):
    """消息明细表。落库即永久记忆，重启、换浏览器都能续上。"""

    __tablename__ = "chat_message"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(
        String(64),
        ForeignKey("chat_session.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(16), nullable=False, comment="user / assistant")
    content = Column(Text, nullable=False)
    # 溯源切片序列化后的 JSON，历史消息回看时也能展开"参考了哪些法条"
    sources_json = Column(Text, nullable=True)
    elapsed_ms = Column(Integer, default=0, comment="本轮推理耗时")
    created_at = Column(DateTime, default=datetime.now, index=True)


class StatuteArticle(Base):
    """结构化法条表。

    这是"双索引"设计里的一环：向量库负责模糊语义召回，
    这张表负责"第X条到底写了什么"的确定性查询。
    比如用户问"劳动合同法第十九条"，走这张表是 100% 准确的，
    走向量检索反而可能召回相邻条文。
    """

    __tablename__ = "statute_article"

    id = Column(Integer, primary_key=True, autoincrement=True)
    law_name = Column(String(128), nullable=False, index=True, comment="法律全称")
    law_short = Column(String(64), nullable=True, comment="简称，如《劳动合同法》")
    domain = Column(String(32), nullable=False, index=True, comment="法律领域 key")
    chapter = Column(String(128), nullable=True, comment="所属编/章")
    article_no = Column(String(32), nullable=False, comment="条号，如 第十九条")
    article_index = Column(Integer, default=0, comment="条号数字，便于排序与区间查询")
    heading = Column(String(255), nullable=True, comment="条文主旨，如【试用期期限】")
    content = Column(Text, nullable=False, comment="条文原文")
    effective_date = Column(String(32), nullable=True, comment="施行日期")
    source_file = Column(String(255), nullable=True, comment="来源知识文件")

    __table_args__ = (
        Index("idx_law_article", "law_name", "article_no"),
        Index("idx_domain_index", "domain", "article_index"),
    )


class KnowledgeDoc(Base):
    """知识文件台账。

    存文件内容指纹（sha1），重建索引时只处理变化的文件。
    32 个法律文件全量重跑要花掉几块钱 embedding 费用，
    有了这张表，改一个文件只重建一个，是实打实的成本优化。
    """

    __tablename__ = "knowledge_doc"

    id = Column(Integer, primary_key=True, autoincrement=True)
    domain = Column(String(32), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    file_hash = Column(String(64), nullable=False, comment="文件内容 sha1")
    char_count = Column(Integer, default=0)
    chunk_count = Column(Integer, default=0, comment="写入向量库的切片数")
    article_count = Column(Integer, default=0, comment="解析出的法条条数")
    indexed_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (Index("idx_domain_file", "domain", "filename", unique=True),)


class SystemSetting(Base):
    """全局模型配置。固定主键 1，保证永远只有一行。"""

    __tablename__ = "system_setting"

    id = Column(Integer, primary_key=True, default=1)
    provider = Column(String(32), default="zhipu")
    model_name = Column(String(64), default="glm-4-flash")
    api_key = Column(String(255), nullable=False, default="")
    base_url = Column(String(255), default="https://open.bigmodel.cn/api/paas/v4/")
    temperature = Column(Float, default=0.1, comment="法律问答要保守，默认低温")
    top_k = Column(Integer, default=8, comment="向量粗排召回条数")
    rerank_n = Column(Integer, default=4, comment="精排后保留条数")
    use_rerank = Column(Boolean, default=True)
    strict_mode = Column(
        Boolean, default=True, comment="严格模式：只允许依据检索到的法条回答"
    )
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
