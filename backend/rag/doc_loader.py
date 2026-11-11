"""文档解析层：把多格式文件转成纯文本，再交给自己的切分器。

## 为什么只在这一层用 LlamaIndex

本项目的检索链路每个环节都是针对法律语料特化过的 ——

- 切分按「第X条」小节边界，一条法条绝不跨 chunk
- 双索引（Milvus 向量 + MySQL 结构化法条）
- 三路召回 + RRF 融合，结构化命中强制置顶

这些用框架的默认实现接不住（详见 `docs/10-Agent与RAG知识要点.md` 里
"为什么不用 LlamaIndex"那段）。所以整个检索链路是自研的。

但「把 PDF 变成干净文本」这件事，LlamaIndex 的 reader 确实比手写强：

- 版式分析（多栏、表格、页眉页脚）
- 格式覆盖广（PDF / DOCX / PPTX / XLSX / HTML）
- 中文编码处理比直接读字节靠谱

所以职责划分很清楚：

    LlamaIndex   负责「文件 → 文本」
    自己的链路   负责「文本 → 切片 → 向量 → 检索 → 生成」

一句话：**用它的强项，不用它的框架。**

## 支持哪些格式

| 格式 | 处理方式 | 能否进法条表 |
|---|---|---|
| `.md` / `.txt` | 直接读，走原来的 parse_markdown | ✅ 有「第X条」结构就能 |
| `.pdf` | LlamaIndex PDFReader | ❌ 只有向量检索 |
| `.docx` | LlamaIndex DocxReader | ❌ 只有向量检索 |

PDF/DOCX 不进 MySQL 法条表，因为它们提取出来的是纯文本流，
没有可靠的「第X条」边界 —— 强行解析只会产生脏数据。
它们作为**补充语料**只进向量库，参与语义检索。
"""
from __future__ import annotations

import re
from pathlib import Path

from common.logger import get_logger
from config import settings
from rag.chunker import Chunk, _make_chunk_id, _split_long_text

logger = get_logger("doc_loader")

# 能处理的扩展名。加新格式时记得同步改前端的上传 accept
SUPPORTED_SUFFIXES = {".md", ".txt", ".pdf", ".docx"}

# 单个文件的大小上限（MB）。PDF 动辄几十兆，解析会占满内存，卡在这一步
MAX_FILE_MB = 20


class DocLoadError(ValueError):
    """文档解析失败。带上人能看懂的原因，直接展示给用户。"""


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_SUFFIXES


def load_text(path: Path) -> str:
    """把文件读成纯文本。

    这是本项目唯一使用 LlamaIndex 的地方 —— reader 的返回值是
    `llama_index.core.schema.Document` 列表（PDF 按页、DOCX 按段落），
    我们只取其中的 `text`，后面的切分和索引完全走自己的链路。

    Raises:
        DocLoadError: 格式不支持、文件过大、扫描件、解析异常
    """
    path = Path(path)
    if not path.exists():
        raise DocLoadError(f"文件不存在：{path.name}")

    size_mb = path.stat().st_size / 1024 / 1024
    if size_mb > MAX_FILE_MB:
        raise DocLoadError(
            f"{path.name} 有 {size_mb:.1f} MB，超过 {MAX_FILE_MB} MB 上限。"
            "建议拆分后再上传，或者先转成 Markdown。"
        )

    suffix = path.suffix.lower()

    if suffix in {".md", ".txt"}:
        # 这两种直接读，不经过 LlamaIndex —— 没必要为纯文本多加一层
        return path.read_text(encoding="utf-8", errors="ignore")

    if suffix == ".pdf":
        return _load_pdf(path)

    if suffix == ".docx":
        return _load_docx(path)

    raise DocLoadError(
        f"不支持的格式：{suffix or '（无扩展名）'}。"
        f"目前支持 {', '.join(sorted(SUPPORTED_SUFFIXES))}"
    )


def _load_pdf(path: Path) -> str:
    """PDF → 文本。

    两种失败要分开报：

    - 依赖没装 → 提示装 llama-index-readers-file
    - 提取不出文字 → 大概率是扫描件（图片型 PDF），需要 OCR

    第二种最容易让人困惑：文件明明能打开，程序却说没内容。
    """
    try:
        from llama_index.readers.file import PDFReader
    except ImportError as exc:  # pragma: no cover
        raise DocLoadError(
            "缺少 PDF 解析依赖，执行：pip install llama-index-readers-file"
        ) from exc

    try:
        documents = PDFReader().load_data(file=str(path))
    except Exception as exc:  # noqa: BLE001
        raise DocLoadError(f"PDF 解析失败：{type(exc).__name__} - {exc}") from exc

    pages = [doc.text for doc in documents if getattr(doc, "text", "").strip()]
    if not pages:
        raise DocLoadError(
            f"{path.name} 解析后没有任何文字。"
            "如果这是扫描件（图片型 PDF），需要先做 OCR 再上传。"
        )

    text = "\n\n".join(pages)
    cleaned = _clean_extracted_text(text)

    logger.info(
        "PDF 解析完成：%s（%d 页，%d 字）", path.name, len(documents), len(cleaned)
    )
    return cleaned


def _load_docx(path: Path) -> str:
    """DOCX → 文本。"""
    try:
        from llama_index.readers.file import DocxReader
    except ImportError as exc:  # pragma: no cover
        raise DocLoadError(
            "缺少 DOCX 解析依赖，执行：pip install llama-index-readers-file"
        ) from exc

    try:
        documents = DocxReader().load_data(file=str(path))
    except Exception as exc:  # noqa: BLE001
        raise DocLoadError(f"DOCX 解析失败：{type(exc).__name__} - {exc}") from exc

    text = "\n".join(doc.text for doc in documents if getattr(doc, "text", "").strip())
    cleaned = _clean_extracted_text(text)

    if not cleaned.strip():
        raise DocLoadError(f"{path.name} 解析后没有文字，可能是空文档或全是图片")

    logger.info("DOCX 解析完成：%s（%d 字）", path.name, len(cleaned))
    return cleaned


# 整行只有一个页码，如 "12"、"- 12 -"、"第 12 页"、"12 / 30"
_PAGE_NUMBER_LINE = re.compile(
    r"^\s*(?:[-—–]\s*)?(?:第\s*)?\d{1,4}(?:\s*页)?(?:\s*[/／]\s*\d{1,4})?\s*(?:[-—–]\s*)?$"
)


def _clean_extracted_text(text: str) -> str:
    """清洗从 PDF/DOCX 里提取出来的文本。

    只做保守的三件事，不动可能的法条结构：

    1. 删掉整行只有页码的行（PDF 每页底部都有一行）
    2. 把 3 个以上连续空行压成一个空行
    3. 去掉不可见字符（PDF 提取常带 \\u200b、\\xa0）

    **不做**"合并断行" —— PDF 常把一句话折成多行，合并看起来更干净，
    但法律条文里"（一）……（二）……"这种列举会被误合并成一整段，
    破坏后续切分的边界。宁可留着换行，让 chunker 自己判断。
    """
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and _PAGE_NUMBER_LINE.match(stripped):
            continue                    # 页码行，丢掉
        # 去掉零宽字符和不换行空格
        cleaned = stripped.replace("\u200b", "").replace("\xa0", " ")
        lines.append(cleaned)

    joined = "\n".join(lines)
    # 连续空行压缩
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    return joined.strip()


def parse_plain_text(
    text: str,
    domain: str,
    filename: str,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[Chunk]:
    """把无结构的纯文本切成 chunk（只有 passage，没有法条）。

    和 `chunker.parse_markdown` 的区别：

        parse_markdown   依赖 `###` 标题边界，能产出 Article（进 MySQL 法条表）
        parse_plain_text 只按段落聚合，只产出 Chunk（进向量库）

    为什么要按"段落块"聚合而不是一段一个 chunk：

        PDF 提取出来的段落长则几百字，短则十几个字（表格单元格、列表项）。
        一段一个 chunk 会产生大量碎片，向量检索时语义不完整，
        而且切片数量会暴涨。所以先累积到接近 chunk_size 再切。

    Args:
        text: 已清洗的纯文本
        domain: 法律领域 key（决定进哪个 Milvus 集合）
        filename: 原始文件名，写进 chunk 用于溯源
        chunk_size / overlap: 不传就用配置里的默认值
    """
    chunk_size = chunk_size or settings.CHUNK_SIZE
    overlap = overlap or settings.CHUNK_OVERLAP

    # 按空行切段。PDF 的段落之间一定有空白行，这是最可靠的边界
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return []

    chunks: list[Chunk] = []
    buffer: list[str] = []
    buffer_len = 0

    def flush() -> None:
        """把缓冲区里的段落合成一个 chunk。"""
        nonlocal buffer, buffer_len
        if not buffer:
            return
        body = "\n".join(buffer).strip()
        buffer = []
        buffer_len = 0
        if not body:
            return

        # 单块超长时再细切（复用 chunker 的句子边界切分，避免截断词）
        for piece in _split_long_text(body, chunk_size, overlap):
            if not piece.strip():
                continue
            chunks.append(
                Chunk(
                    chunk_id=_make_chunk_id(domain, filename, len(chunks)),
                    # 纯文本没有书名号和条号，等价于"出处"只有文件名
                    text=f"《{Path(filename).stem}》\n{piece}",
                    content=piece,
                    domain=domain,
                    filename=filename,
                    law_name=Path(filename).stem,
                    law_short=Path(filename).stem,
                    article_no="",          # 没有条号 → 只进向量库
                    heading="",
                    chapter="",
                    kind="passage",
                )
            )

    for para in paragraphs:
        # 单段就超过 chunk_size 的，先冲掉缓冲，再单独处理这一段
        if len(para) >= chunk_size:
            flush()
            buffer = [para]
            buffer_len = len(para)
            flush()
            continue

        if buffer_len + len(para) > chunk_size and buffer:
            flush()

        buffer.append(para)
        buffer_len += len(para)

    flush()
    logger.info("纯文本切分完成：%s → %d 个切片", filename, len(chunks))
    return chunks
