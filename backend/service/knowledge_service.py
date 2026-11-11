"""知识库业务层：索引构建、状态统计、用户文档上传。

知识库有两个来源：
- 内置法律库：knowledge_base/ 下按领域分目录，随项目走，30+ 份 markdown；
- 用户上传：storage/uploads/，进独立集合 law_upload，和内置库物理隔离。

隔离的原因很实际：重建内置库时如果把用户传的文件一起冲掉，会挨骂。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from common.logger import get_logger
from config import (
    LAW_DOMAINS,
    UPLOAD_COLLECTION,
    collection_name,
    settings,
)
from common.result import BizError, NotFoundError, PermissionDeniedError
from dao import knowledge_dao, statute_dao
from dao.db import SessionLocal
from rag import indexer, milvus_store
from rag.chunker import parse_markdown
from rag.doc_loader import DocLoadError, load_text, parse_plain_text
from rag.embedder import get_embedder

logger = get_logger("knowledge")


def domain_overview(db: Session) -> list[dict]:
    """知识库面板的主数据源：每个领域有哪些文档、多少切片、多少条法条。"""
    summary = knowledge_dao.summary_by_domain(db)
    # 法条数直接从 statute_article 表统计，而不是用 knowledge_doc 里的缓存值 ——
    # 台账可能因为中途失败而滞后，法条表才是准的
    statute_counts = statute_dao.count_by_domain(db)
    result = []

    for key, meta in LAW_DOMAINS.items():
        stat = summary.get(key, {})
        files = indexer.list_domain_files(key)
        result.append(
            {
                "domain": key,
                "label": meta["label"],
                "desc": meta["desc"],
                "color": meta["color"],
                "dir": meta["dir"],
                "collections": collection_name(key),
                "vectors": milvus_store.count(collection_name(key)),
                "docs": len(files) or stat.get("docs", 0),
                "chunks": stat.get("chunks", 0),
                "articles": stat.get("articles", 0),
                "statutes": statute_counts.get(key, 0),
                "chars": stat.get("chars", 0),
                "files": [
                    {
                        "filename": p.name,
                        "size_kb": round(p.stat().st_size / 1024, 1),
                    }
                    for p in files
                ],
            }
        )
    return result


def build(domain: str | None = None, force: bool = False) -> dict:
    """构建索引。

    domain=None 表示全量。force=True 会先删集合再重建，
    用在改了切分参数、或者怀疑索引和源文件不一致的时候。
    """
    targets = [domain] if domain else list(LAW_DOMAINS.keys())
    for item in targets:
        if item not in LAW_DOMAINS:
            raise BizError(f"未知的法律领域：{item}")

    total_chunks = 0
    total_articles = 0
    details = []

    db = SessionLocal()
    try:
        for item in targets:
            results = indexer.rebuild_domain(db, item, force=force)
            db.commit()

            chunks = sum(r.chunks for r in results)
            articles = sum(r.articles for r in results)
            total_chunks += chunks
            total_articles += articles
            details.append(
                {
                    "domain": item,
                    "label": LAW_DOMAINS[item]["label"],
                    "files": len(results),
                    "chunks": chunks,
                    "articles": articles,
                    "failed": [
                        {"filename": r.filename, "reason": r.reason}
                        for r in results
                        if r.reason.startswith("失败")
                    ],
                }
            )
    finally:
        db.close()

    return {
        "domains": details,
        "total_chunks": total_chunks,
        "total_articles": total_articles,
        "message": f"索引构建完成：{len(targets)} 个领域 / {total_chunks} 条切片 / "
                   f"{total_articles} 条法条",
    }


# ===========================================================================
# 用户上传文档
# ===========================================================================
def _safe_name(raw: str) -> str:
    """清洗文件名，防路径穿越（../../etc/passwd 这种）。

    只取 basename，再剥掉路径分隔符，最后校验后缀白名单。
    """
    name = Path(raw or "").name.replace("\\", "").replace("/", "").strip()
    if not name:
        raise BizError("文件名不能为空")
    if Path(name).suffix.lower() not in settings.ALLOWED_SUFFIXES:
        supported = " / ".join(settings.ALLOWED_SUFFIXES)
        raise BizError(f"仅支持这些格式：{supported}")
    return name


def save_upload(raw_name: str, content: bytes) -> str:
    """落盘。同名文件自动加序号，绝不静默覆盖用户已经传过的文件。"""
    if not content:
        raise BizError("文件内容为空")
    if len(content) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise BizError(f"文件超过 {settings.MAX_UPLOAD_MB}MB 限制")

    # 格式白名单由 _safe_name 统一校验，这里不再重复判断
    name = _safe_name(raw_name)
    target = settings.UPLOAD_DIR / name

    if target.exists():
        stem, suffix = target.stem, target.suffix
        index = 1
        while True:
            candidate = settings.UPLOAD_DIR / f"{stem}_{index}{suffix}"
            if not candidate.exists():
                target = candidate
                break
            index += 1

    target.write_bytes(content)
    logger.info("已保存上传文件：%s", target.name)
    return target.name


def index_upload(filename: str) -> dict:
    """把上传的文件切分入向量库。

    上传文件不像内置文档那样有规范的法律元信息，
    所以统一按 "upload" 领域解析，前缀只带文件名。
    """
    path = settings.UPLOAD_DIR / filename
    if not path.exists():
        raise NotFoundError(f"文件不存在：{filename}")

    suffix = path.suffix.lower()

    if suffix in {".md", ".txt"}:
        # Markdown 有 `###` 标题结构，走结构感知切分 —— 一条法条不跨 chunk，
        # 顺带还能把「第X条」抽出来（虽然上传的这批不进法条表）
        parsed = parse_markdown(
            path,
            domain="upload",
            chunk_size=settings.CHUNK_SIZE,
            overlap=settings.CHUNK_OVERLAP,
        )
        chunks = parsed.chunks
        char_count = len(path.read_text(encoding="utf-8", errors="ignore"))
    else:
        # PDF / DOCX：先用 LlamaIndex 的 reader 提取纯文本，再按段落切。
        #
        # 这两类文件提取出来的是无结构文本流，没有可靠的「第X条」边界，
        # 所以只产出 passage 切片进向量库，不进 MySQL 法条表 ——
        # 强行解析条文只会产生脏数据。
        try:
            text = load_text(path)
        except DocLoadError as exc:
            # 转成业务错误，前端能看到「这是扫描件，需要 OCR」这类人话提示
            raise BizError(str(exc)) from exc

        chunks = parse_plain_text(
            text,
            domain="upload",
            filename=filename,
            chunk_size=settings.CHUNK_SIZE,
            overlap=settings.CHUNK_OVERLAP,
        )
        char_count = len(text)

    if not chunks:
        raise BizError("文件里没有可索引的文本内容")

    milvus_store.delete_by_file(UPLOAD_COLLECTION, filename)
    vectors = get_embedder().embed_documents([c.text for c in chunks])
    written = milvus_store.upsert_chunks(UPLOAD_COLLECTION, chunks, vectors)

    return {"filename": filename, "chunks": written, "chars": char_count}


def list_uploads() -> list[dict]:
    files = []
    if settings.UPLOAD_DIR.exists():
        for path in sorted(settings.UPLOAD_DIR.iterdir()):
            if not path.is_file():
                continue
            stat = path.stat()
            files.append(
                {
                    "filename": path.name,
                    "size_kb": round(stat.st_size / 1024, 1),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).strftime(
                        "%Y-%m-%d %H:%M"
                    ),
                }
            )
    return files


def delete_upload(filename: str) -> dict:
    """删除上传文件 + 清理它的向量切片。

    只允许删 storage/uploads 下的文件，内置知识库文件不允许从这里删 ——
    那些是项目的固定资产，删了其他人克隆代码就跑不起来了。
    """
    target = (settings.UPLOAD_DIR / Path(filename).name).resolve()
    if settings.UPLOAD_DIR.resolve() not in target.parents:
        raise PermissionDeniedError("非法路径")
    if not target.exists():
        raise NotFoundError(f"文件不存在：{filename}")

    target.unlink()
    milvus_store.delete_by_file(UPLOAD_COLLECTION, target.name)
    logger.info("已删除上传文件：%s", target.name)
    return {"filename": target.name}


def storage_size_mb() -> float:
    total = 0
    for path in settings.STORAGE_DIR.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return round(total / 1024 / 1024, 2)
