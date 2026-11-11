"""索引构建流水线：一份 markdown -> Milvus 切片 + MySQL 法条。

完整链路：
    读文件 -> 算指纹 -> 判断是否需要重建 -> 解析成 chunks/articles
           -> 批量向量化 -> upsert 进 Milvus -> 写入法条表 -> 更新台账

每一步都能单独调用，方便测试；也支持"只重建一个领域"，
避免改一份文件就要重新花钱向量化全部 30 多份文档。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from common.logger import get_logger
from config import LAW_DOMAINS, collection_name, settings
from dao import knowledge_dao, statute_dao
from rag import milvus_store
from rag.chunker import file_fingerprint, parse_markdown
from rag.embedder import get_embedder

logger = get_logger("indexer")


@dataclass
class IndexResult:
    domain: str
    filename: str
    chunks: int
    articles: int
    chars: int
    skipped: bool = False
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "domain": self.domain,
            "filename": self.filename,
            "chunks": self.chunks,
            "articles": self.articles,
            "chars": self.chars,
            "skipped": self.skipped,
            "reason": self.reason,
        }


def index_file(
    db: Session,
    path: Path,
    domain: str,
    force: bool = False,
) -> IndexResult:
    """索引单个文件。

    force=False 时按内容指纹判断：文件没改就整段跳过，
    连解析都省了。这是增量索引的核心。
    """
    collection = collection_name(domain)
    filename = path.name
    raw_text = path.read_text(encoding="utf-8")
    char_count = len(raw_text)
    fingerprint = file_fingerprint(path)

    record = knowledge_dao.get(db, domain, filename)
    if not force and record and record.file_hash == fingerprint:
        return IndexResult(
            domain=domain,
            filename=filename,
            chunks=record.chunk_count,
            articles=record.article_count,
            chars=record.char_count,
            skipped=True,
            reason="文件未变化，跳过",
        )

    parsed = parse_markdown(
        path,
        domain=domain,
        chunk_size=settings.CHUNK_SIZE,
        overlap=settings.CHUNK_OVERLAP,
    )

    if not parsed.chunks:
        logger.warning("%s 未解析出任何切片，跳过", filename)
        return IndexResult(domain, filename, 0, 0, char_count, skipped=True,
                           reason="未解析出内容")

    # 1. 先清掉这个文件的旧切片，防止文件删了几条法条后旧内容继续被检索到
    milvus_store.delete_by_file(collection, filename)

    # 2. 向量化并写入 Milvus
    vectors = get_embedder().embed_documents([c.text for c in parsed.chunks])
    written = milvus_store.upsert_chunks(collection, parsed.chunks, vectors)

    # 3. 法条写进 MySQL 结构化表（同一份数据的第二种索引形态）
    statute_dao.delete_by_source(db, filename)
    if parsed.articles:
        by_law: dict[str, list[dict]] = {}
        for article in parsed.articles:
            by_law.setdefault(article.law_name, []).append(
                {
                    "article_no": article.article_no,
                    "article_index": article.article_index,
                    "heading": article.heading,
                    "content": article.content,
                    "law_short": article.law_short,
                    "domain": article.domain,
                    "chapter": article.chapter,
                    "effective_date": article.effective_date,
                    "source_file": article.source_file,
                }
            )
        for law_name, rows in by_law.items():
            statute_dao.bulk_upsert(db, law_name, rows)

    # 4. 更新台账
    knowledge_dao.upsert(
        db,
        domain=domain,
        filename=filename,
        file_hash=fingerprint,
        char_count=char_count,
        chunk_count=written,
        article_count=len(parsed.articles),
    )

    logger.info(
        "索引完成 %s：%d 切片 / %d 条法条", filename, written, len(parsed.articles)
    )
    return IndexResult(
        domain=domain,
        filename=filename,
        chunks=written,
        articles=len(parsed.articles),
        chars=char_count,
    )


def list_domain_files(domain: str) -> list[Path]:
    """某个领域目录下的全部 markdown 文件。"""
    meta = LAW_DOMAINS.get(domain)
    if not meta:
        return []
    directory = settings.KNOWLEDGE_DIR / meta["dir"]
    if not directory.exists():
        return []
    return sorted(
        p
        for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in settings.ALLOWED_SUFFIXES
    )


def rebuild_domain(db: Session, domain: str, force: bool = False) -> list[IndexResult]:
    """重建一个领域下的所有文件。

    force=True 会先把整个集合删掉重建 —— 用在"改了切分参数"或者
    "怀疑索引脏了"的时候。日常改文件用 force=False 的增量模式就够了。
    """
    if domain not in LAW_DOMAINS:
        raise KeyError(f"未知法律领域：{domain}")

    if force:
        milvus_store.drop(collection_name(domain))

    results = []
    for path in list_domain_files(domain):
        try:
            results.append(index_file(db, path, domain, force=force))
        except Exception as exc:  # noqa: BLE001
            logger.error("索引 %s 失败：%s", path.name, exc)
            results.append(
                IndexResult(domain, path.name, 0, 0, 0, skipped=True,
                            reason=f"失败：{exc}")
            )

    # 向量库变了，BM25 的内存索引必须跟着失效，否则两路召回的数据源不一致
    from rag import bm25_index

    bm25_index.invalidate(domain)
    return results
