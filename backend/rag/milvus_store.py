"""Milvus Lite 向量库封装。

Milvus Lite 是 Milvus 官方提供的嵌入式模式：`MilvusClient("./xxx.db")`
直接在当前进程里起一个向量库，不需要 Docker、不需要单独的服务进程。
数据落在一个目录里，随项目一起走，非常适合"面试演示 / 单机部署"这种场景。

生产环境要换 Standalone 集群时，只要把 MILVUS_URI 改成
`http://host:19530`，这个文件里的代码一行都不用动 —— 这正是
MilvusClient 这层统一 API 的价值。
"""
from __future__ import annotations

import threading
from typing import Optional

from pymilvus import DataType, MilvusClient
from pymilvus.milvus_client.index import IndexParams

from common.logger import get_logger
from config import settings
from rag.chunker import Chunk

logger = get_logger("milvus")

# VARCHAR 的 max_length 单位是**字节**不是字符，中文 UTF-8 占 3 字节。
# 2048 足够放下法条正文（约 680 汉字），再长的正文会走 passage 切片逻辑。
MAX_TEXT_BYTES = 8192
MAX_FIELD_BYTES = 512

_client: Optional[MilvusClient] = None
_lock = threading.Lock()
# 已确认 load 过的集合。Milvus 是"存算分离"的设计：数据落盘后集合会处于
# released 状态，检索前必须先 load 进内存。进程重启后这个状态不会自动恢复，
# 不 load 直接 search 会报 code=101 "call load() before search/get/query"。
_loaded: set[str] = set()


def get_client() -> MilvusClient:
    """全局单例客户端。

    Milvus Lite 是进程内数据库，多个客户端实例指向同一个目录会互相锁死，
    所以必须保证整个进程只有一个，且创建过程加锁。
    """
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                logger.info("连接 Milvus：%s", settings.MILVUS_URI)
                _client = MilvusClient(uri=settings.MILVUS_URI)
    return _client


def _schema(client: MilvusClient):
    """统一的集合 schema。

    显式声明字段而不是纯动态字段，好处是能在文章号、领域上建标量索引，
    后续做"只在劳动法领域里检索"这类过滤会快很多。
    """
    schema = client.create_schema(auto_id=False, enable_dynamic_field=True)

    schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
    schema.add_field("vector", DataType.FLOAT_VECTOR, dim=settings.EMBED_DIM)
    schema.add_field("text", DataType.VARCHAR, max_length=MAX_TEXT_BYTES)
    schema.add_field("content", DataType.VARCHAR, max_length=MAX_TEXT_BYTES)
    schema.add_field("domain", DataType.VARCHAR, max_length=32)
    schema.add_field("filename", DataType.VARCHAR, max_length=MAX_FIELD_BYTES)
    schema.add_field("law_name", DataType.VARCHAR, max_length=MAX_FIELD_BYTES)
    schema.add_field("law_short", DataType.VARCHAR, max_length=MAX_FIELD_BYTES)
    schema.add_field("article_no", DataType.VARCHAR, max_length=64)
    schema.add_field("heading", DataType.VARCHAR, max_length=MAX_FIELD_BYTES)
    schema.add_field("chapter", DataType.VARCHAR, max_length=MAX_FIELD_BYTES)
    schema.add_field("kind", DataType.VARCHAR, max_length=32)
    return schema


def ensure_loaded(name: str) -> None:
    """确保集合已加载进内存，可以检索。

    这是 Milvus 最容易踩的一个坑：插入数据、建完索引之后能立刻 search，
    因为集合还在内存里；但进程一重启，集合状态就是 released，
    再 search 会直接抛异常。而且这个异常在 Lite 模式下不会自动恢复，
    必须显式 load 一次。

    用集合缓存避免重复调用 —— load 本身是幂等的，但每次检索都调一次
    会多一次 RPC，在 SSE 链路里能省则省。
    """
    if name in _loaded:
        return
    client = get_client()
    try:
        client.load_collection(name)
    except Exception as exc:  # noqa: BLE001
        # 集合不存在时会抛错，这里不阻断，交给后续 search 的 has_collection 判断
        logger.debug("load 集合 %s 失败：%s", name, exc)
    _loaded.add(name)


def ensure_collection(name: str) -> None:
    """集合不存在就建，存在就跳过。

    注意：建完集合必须建索引，否则 Milvus Lite 插入后检索会报
    "index not found"。索引类型用 FLAT —— 几千条数据暴力搜索
    比建 IVF/HNSW 更快也更准，还省内存。
    """
    client = get_client()
    if client.has_collection(name):
        ensure_loaded(name)
        return

    client.create_collection(name, schema=_schema(client))

    index_params = IndexParams()
    index_params.add_index(
        field_name="vector",
        index_type="FLAT",
        metric_type="COSINE",  # 向量已归一化，余弦相似度等价于内积，语义检索的常规选择
    )
    client.create_index(name, index_params)
    logger.info("已创建集合 %s", name)
    ensure_loaded(name)


def upsert_chunks(name: str, chunks: list[Chunk], vectors: list[list[float]]) -> int:
    """写入切片。

    用 upsert 而不是 insert：chunk_id 是内容哈希，重建索引时同一条
    会覆盖旧记录，不会出现"改了一次文件，检索结果里同一段话出现两遍"。
    """
    if not chunks:
        return 0

    client = get_client()
    ensure_collection(name)

    rows = []
    for chunk, vector in zip(chunks, vectors):
        rows.append(
            {
                "id": chunk.chunk_id,
                "vector": vector,
                "text": chunk.text[:2700],
                "content": chunk.content[:2700],
                "domain": chunk.domain,
                "filename": chunk.filename[:160],
                "law_name": (chunk.law_name or "")[:160],
                "law_short": (chunk.law_short or "")[:160],
                "article_no": chunk.article_no or "",
                "heading": (chunk.heading or "")[:160],
                "chapter": (chunk.chapter or "")[:160],
                "kind": chunk.kind,
            }
        )

    client.upsert(name, rows)
    client.flush(name)
    return len(rows)


def search(
    name: str, vector: list[float], top_k: int = 8, expr: str = ""
) -> list[dict]:
    """向量检索，返回统一结构的候选列表。

    score 用的是 Milvus 的 distance：COSINE 下范围 [-1, 1]，越大越相似。
    """
    client = get_client()
    if not client.has_collection(name):
        return []

    ensure_loaded(name)

    try:
        raw = client.search(
            collection_name=name,
            data=[vector],
            limit=top_k,
            filter=expr or "",
            output_fields=[
                "text", "content", "domain", "filename", "law_name",
                "law_short", "article_no", "heading", "chapter", "kind",
            ],
            search_params={"metric_type": "COSINE", "params": {}},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("检索 %s 失败：%s", name, exc)
        return []

    hits: list[dict] = []
    for group in raw:
        for item in group:
            entity = item.get("entity", {}) or {}
            hits.append(
                {
                    "chunk_id": item.get("id"),
                    "score": float(item.get("distance", 0.0)),
                    "text": entity.get("content") or entity.get("text") or "",
                    "display": entity.get("text") or "",
                    "domain": entity.get("domain", ""),
                    "filename": entity.get("filename", ""),
                    "law_name": entity.get("law_name", ""),
                    "law_short": entity.get("law_short", ""),
                    "article_no": entity.get("article_no", ""),
                    "heading": entity.get("heading", ""),
                    "chapter": entity.get("chapter", ""),
                    "kind": entity.get("kind", "passage"),
                }
            )
    return hits


def count(name: str) -> int:
    client = get_client()
    if not client.has_collection(name):
        return 0
    try:
        stats = client.get_collection_stats(name)
        return int(stats.get("row_count", 0))
    except Exception:  # noqa: BLE001
        return 0


def delete_by_file(name: str, filename: str) -> None:
    """删除某份文件产生的全部切片（改文件后重建用）。

    Milvus 的 delete 是"打删除标记"，物理空间要等 compaction 才回收，
    但检索层面立刻生效，业务上够用。
    """
    client = get_client()
    if not client.has_collection(name):
        return
    safe = filename.replace('"', '\\"')
    try:
        client.delete(name, filter=f'filename == "{safe}"')
        client.flush(name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("删除 %s 中 %s 的切片失败：%s", name, filename, exc)


def drop(name: str) -> None:
    client = get_client()
    if client.has_collection(name):
        client.drop_collection(name)
        _loaded.discard(name)
        logger.info("已删除集合 %s", name)


def list_collections() -> list[str]:
    """只返回本项目的业务集合，避免把别的实验集合也算进统计。"""
    try:
        names = get_client().list_collections()
    except Exception:  # noqa: BLE001
        return []
    return sorted(n for n in names if n.startswith("law_"))
