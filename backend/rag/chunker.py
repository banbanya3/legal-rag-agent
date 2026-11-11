"""法律文档解析与切片。

普通 RAG 用固定窗口切文本，把一条法条拦腰截断是灾难：
"用人单位应当向劳动者支付经济补偿"被切成两半，后半句"按劳动者在本单位
工作的年限，每满一年支付一个月工资"跑到另一个 chunk 里，检索出来就是残缺的。

所以这里做的是**结构感知切分**：
1. 先用正则识别 `### 第十九条 【试用期期限】` 这样的法条标题；
2. 一条法条 = 一个 chunk，绝不拆开；
3. 法条之外的解读段落，才按句子边界滑动切分；
4. 每个 chunk 前面拼上"《法律简称》第X条【主旨】"的上下文前缀，
   这是提升法律问答召回率最省钱的技巧 —— 让向量本身携带出处信息。

输出两种东西：
- chunks：进 Milvus，负责模糊语义召回
- articles：进 MySQL，负责"第X条"的精确查询
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# 匹配 "### 第十九条 【试用期期限】"、"### 第 19 条"、"### 第一千零七十九条【离婚】"
ARTICLE_HEADING = re.compile(
    r"^###\s*(第[零一二三四五六七八九十百千万0-9]+条)\s*(?:[【\[]([^】\]]*)[】\]])?\s*$"
)
# 非条文的 ### 小节标题，如 "### 要点：什么是事实劳动关系"
SECTION_HEADING = re.compile(r"^###\s+(.+?)\s*$")
# 二级标题作为"章"的归属
CHAPTER_HEADING = re.compile(r"^##\s+(.+?)\s*$")
# 元信息行：> 法律名称：中华人民共和国劳动合同法
META_LINE = re.compile(r"^>\s*([^:：]+)[:：]\s*(.+?)\s*$")
# 中文元信息键 -> 内部英文字段名。不转换的话后面 meta.get("law_short") 永远取不到值。
META_KEYS = {
    "法律名称": "law_name",
    "简称": "law_short",
    "施行日期": "effective_date",
    "最近修正": "last_amended",
    "领域": "domain",
    "标签": "tags",
}
# 句子边界：中文句号、问号、叹号、分号，保留标点
SENTENCE_END = re.compile(r"(?<=[。！？；])")


@dataclass
class Chunk:
    """写入向量库的最小单元。"""

    chunk_id: str
    text: str          # 带上下文前缀、真正送去 embedding 的文本
    content: str       # 原文，展示给用户看
    domain: str
    filename: str
    law_name: str = ""
    law_short: str = ""
    article_no: str = ""
    heading: str = ""
    chapter: str = ""
    kind: str = "passage"  # article / passage


@dataclass
class Article:
    """写入 MySQL 法条表的结构化记录。"""

    law_name: str
    law_short: str
    domain: str
    chapter: str
    article_no: str
    article_index: int
    heading: str
    content: str
    effective_date: str
    source_file: str


@dataclass
class ParsedDoc:
    meta: dict = field(default_factory=dict)
    articles: list[Article] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)


def _cn_to_int(text: str) -> int:
    """中文数字转阿拉伯数字：一千零七十九 -> 1079。

    只处理到万位，法条条号不会更大，够用了。
    """
    text = text.strip().replace("第", "").replace("条", "")
    if text.isdigit():
        return int(text)

    digits = {
        "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
        "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
    }
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000}

    total, section, number = 0, 0, 0
    for ch in text:
        if ch in digits:
            number = digits[ch]
        elif ch in units:
            unit = units[ch]
            if unit == 10000:
                total = (total + section + number) * unit
                section, number = 0, 0
            else:
                if number == 0:
                    number = 1  # "十一" 里的 "十" 前面省略了一
                section += number * unit
                number = 0
        else:
            return 0
    return total + section + number


def _split_long_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """按句号切句，再贪心拼成不超过 chunk_size 的块。

    法律文本句子长、逻辑紧密，按句子拼比按字符硬切更能保住语义完整性。
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    sentences = [s for s in SENTENCE_END.split(text) if s.strip()]
    chunks: list[str] = []
    buffer = ""

    for sentence in sentences:
        # 单句就超长（法条里偶尔有），只能硬切
        if len(sentence) > chunk_size:
            if buffer:
                chunks.append(buffer)
                buffer = ""
            for i in range(0, len(sentence), chunk_size - overlap):
                chunks.append(sentence[i: i + chunk_size])
            continue

        if len(buffer) + len(sentence) <= chunk_size:
            buffer += sentence
        else:
            if buffer:
                chunks.append(buffer)
            # 重叠：把上一块的尾部接到新块开头，避免跨块信息断裂
            tail = buffer[-overlap:] if buffer and overlap else ""
            buffer = tail + sentence

    if buffer.strip():
        chunks.append(buffer)
    return chunks


def _make_chunk_id(domain: str, filename: str, index: int) -> str:
    """稳定的 chunk 主键。

    用 (领域 + 文件名 + 序号) 做哈希而不是 uuid4：
    重建索引时同一条内容会得到同一个 id，Milvus 里是覆盖而不是重复追加。
    """
    raw = f"{domain}::{filename}::{index}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:32]


def parse_markdown(
    path: Path,
    domain: str,
    chunk_size: int = 420,
    overlap: int = 60,
) -> ParsedDoc:
    """解析一份法律知识 markdown，产出 chunks + articles。

    文档约定（写知识库文件时按这个格式，解析才准）：

        # 文档标题
        > 法律名称：中华人民共和国劳动合同法
        > 简称：劳动合同法
        > 施行日期：2008-01-01
        > 领域：labor

        ## 一、劳动合同的订立
        ### 第十条 【建立劳动关系应当订立书面劳动合同】
        条文正文……

        ### 要点：什么是事实劳动关系
        解读文字……

    一个 `###` 小节 = 一个 chunk。是"第X条"的额外进 MySQL 法条表，
    不是法条的（如"要点："）只进向量库。
    """
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    filename = path.name

    meta: dict = {}
    articles: list[Article] = []
    chunks: list[Chunk] = []
    chapter = ""
    seq = 0

    # 当前小节：{"kind": "article"|"section", "article_no":..., "heading":..., "lines":[]}
    current: Optional[dict] = None
    paragraph_buffer: list[str] = []

    def _prefix(heading_text: str = "") -> str:
        """chunk 的上下文前缀。让向量自己带上出处，是提升法律检索召回最便宜的办法。"""
        parts = []
        if meta.get("law_short"):
            parts.append(f"《{meta['law_short']}》")
        if chapter:
            parts.append(f"{chapter} ")
        text = "".join(parts)
        if heading_text:
            text += heading_text
        return text.strip()

    def _emit(
        content: str,
        kind: str,
        article_no: str = "",
        heading: str = "",
        prefix_text: str = "",
    ) -> None:
        nonlocal seq
        if not content.strip():
            return
        chunks.append(
            Chunk(
                chunk_id=_make_chunk_id(domain, filename, seq),
                text=(prefix_text + "\n" + content).strip() if prefix_text else content,
                content=content,
                domain=domain,
                filename=filename,
                law_name=meta.get("law_name", ""),
                law_short=meta.get("law_short", ""),
                article_no=article_no,
                heading=heading,
                chapter=chapter,
                kind=kind,
            )
        )
        seq += 1

    def flush_paragraph() -> None:
        nonlocal paragraph_buffer
        text = "\n".join(paragraph_buffer).strip()
        paragraph_buffer = []
        if not text:
            return
        for piece in _split_long_text(text, chunk_size, overlap):
            _emit(piece, kind="passage", prefix_text=_prefix())

    def flush_section() -> None:
        """收尾当前 `###` 小节。"""
        nonlocal current
        if current is None:
            return
        section = current
        current = None
        content = "\n".join(section["lines"]).strip()
        if not content:
            return

        heading = section["heading"]
        article_no = section.get("article_no", "")

        if section["kind"] == "article":
            articles.append(
                Article(
                    law_name=meta.get("law_name", ""),
                    law_short=meta.get("law_short", ""),
                    domain=domain,
                    chapter=chapter,
                    article_no=article_no,
                    article_index=_cn_to_int(article_no),
                    heading=heading,
                    content=content,
                    effective_date=meta.get("effective_date", ""),
                    source_file=filename,
                )
            )
            label = f"《{meta['law_short']}》" if meta.get("law_short") else ""
            header = f"{label}{article_no}"
            if heading:
                header += f"【{heading}】"
            if chapter:
                header += f"（{chapter}）"
            _emit(content, kind="article", article_no=article_no,
                  heading=heading, prefix_text=header)
        else:
            # 非条文小节（要点、问答、案例），标题本身就是很好的检索信号
            header = _prefix()
            if heading:
                header = f"{header}{heading}"
            _emit(content, kind="passage", heading=heading, prefix_text=header)

    for line in lines:
        stripped = line.strip()

        # ---- 元信息块 ----
        if stripped.startswith(">"):
            match = META_LINE.match(stripped)
            key = match.group(1).strip() if match else ""
            if match and not articles and key in META_KEYS:
                meta[META_KEYS[key]] = match.group(2).strip()
                continue
            stripped = stripped.lstrip(">").strip()

        # ---- 一级标题：文档标题，不进正文 ----
        if stripped.startswith("# "):
            flush_section()
            flush_paragraph()
            continue

        # ---- 二级标题：切章 ----
        chapter_match = CHAPTER_HEADING.match(stripped)
        if chapter_match and not stripped.startswith("###"):
            flush_section()
            flush_paragraph()
            chapter = chapter_match.group(1).strip()
            continue

        # ---- 三级标题：开一个新小节 ----
        if stripped.startswith("### "):
            flush_section()
            flush_paragraph()

            article_match = ARTICLE_HEADING.match(stripped)
            if article_match:
                current = {
                    "kind": "article",
                    "article_no": article_match.group(1).strip(),
                    "heading": (article_match.group(2) or "").strip(),
                    "lines": [],
                }
            else:
                section_match = SECTION_HEADING.match(stripped)
                current = {
                    "kind": "section",
                    "article_no": "",
                    "heading": section_match.group(1).strip() if section_match else "",
                    "lines": [],
                }
            continue

        # ---- 正文 ----
        if current is not None:
            current["lines"].append(stripped)
        else:
            paragraph_buffer.append(stripped)

    flush_section()
    flush_paragraph()

    return ParsedDoc(meta=meta, articles=articles, chunks=chunks)


def file_fingerprint(path: Path) -> str:
    """文件内容 sha1，用于增量索引判断。"""
    return hashlib.sha1(path.read_bytes()).hexdigest()
