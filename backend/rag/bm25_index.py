"""BM25 稀疏检索：补向量检索的短板。

## 为什么需要它

向量检索是"语义匹配"，擅长同义表达（"加班费"能匹配到"延长工作时间"），
但对**精确关键词**反而不敏感：

- 用户问"第四十四条"，向量可能召回相邻的第四十三条、第四十五条
- 用户问"竞业限制"，向量会把"竞业禁止""保密义务"一起捞上来，分不清
- 罕见专有名词（"DsPCBSD""格式条款"）在向量空间里没有稳定的邻域

BM25 是经典的稀疏检索算法，按词频 + 逆文档频率打分，对**字面精确匹配**很强。
两路互补，用 RRF 融合，是业界标准的混合检索做法。

## 语料从哪来

**直接解析 knowledge_base 下的 md 文件**，而不是去 Milvus 里 dump。

三个理由：

1. Milvus 的 query 需要 expr，对 varchar 主键不好写"全量拉取"的条件
2. 解析 32 个文件只要 1—2 秒，一次构建、进程内缓存，代价可接受
3. 不依赖向量库的可用性 —— 即使 Milvus 挂了，BM25 还能单独工作

代价是：如果 md 改了但没重建索引，BM25 和 Milvus 的内容会不一致。
正常流程下不会发生（改 md 就要跑 init_knowledge），而且重建后
`invalidate()` 会清掉缓存。

## 分词为什么用 jieba

中文没有空格，BM25 需要先分词。jieba 是事实标准，虽然对法律术语不完美
（"不安抗辩权"可能被切成"不安/抗辩/权"），但 BM25 靠的是词频统计，
切错了也只是降低一点召回，不会像向量那样彻底失配。

如果要更准，可以加载自定义词典把法律术语加进去 —— 这是后续可优化项。
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

import jieba
from rank_bm25 import BM25Okapi

from common.logger import get_logger
from config import LAW_DOMAINS, settings

logger = get_logger("bm25")

# jieba 首次加载词典会往 stderr 打一堆 "Building prefix dict..."，
# 对 MCP 的 stdio 传输是噪音（虽然走 stderr 不破坏协议，但日志太吵）
jieba.setLogLevel(logging.WARNING)

# 停用词表：口语问题里的虚词对 BM25 完全是噪音。
#
# 踩过的坑：不做过滤时，"老板一直不给我加班费怎么办" 会被切成
# 「老板 / 一直 / 不给 / 我 / 加班费 / 怎么办」。
# 其中「我」「怎么办」「不给」在几百条法条里都出现过，
# BM25 会给它们算上不低的 IDF 分，结果召回一堆含"我"字但不相关的条文
# （实测捞出了《治安管理处罚法》《消费者权益保护法》）。
# 过滤掉这些词之后，BM25 才真正聚焦在「加班费」「辞退」这类实体词上。
_STOPWORDS = set(
    """
    的 了 在 是 我 你 他 她 它 们 有 和 与 就 不 也 都 还 又 很 太 更 最
    一 个 上 下 里 中 外 前 后 这 那 哪 某 每 各 些 种
    什么 怎么 怎样 如何 为什么 啥 哪些 多少 多久 几年 几个 多大
    可以 能否 能不能 可不可以 能否 是否 应该 需要 要不要
    怎么办 怎么样 是不是 有没有 对不对 行不行 算不算
    吗 呢 吧 啊 呀 哦 嗯 么
    请问 帮我 想问 想知道 告诉我 介绍一下 说说
    现在 目前 一直 经常 已经 曾经 刚刚 马上
    """.split()
)

# 每个领域一份索引：(BM25 对象, 对应的 chunk 列表)
# 第一次检索时构建，之后常驻内存。845 条切片约占 2—3 MB，可以接受。
_cache: dict[str, tuple[BM25Okapi, list[dict]]] = {}
_lock = threading.Lock()


def _load_chunks(domain: str) -> list[dict]:
    """解析该领域的所有 md，产出和向量库结构一致的 chunk 列表。"""
    # 延迟导入：避免 bm25_index 和 indexer 之间形成循环依赖
    from rag.chunker import parse_markdown
    from rag.indexer import list_domain_files

    chunks: list[dict] = []
    for path in list_domain_files(domain):
        try:
            parsed = parse_markdown(
                path, domain, settings.CHUNK_SIZE, settings.CHUNK_OVERLAP
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("BM25 解析 %s 失败：%s", path.name, exc)
            continue

        for chunk in parsed.chunks:
            chunks.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "text": chunk.text,
                    "content": chunk.content,
                    "domain": chunk.domain,
                    "filename": chunk.filename,
                    "law_name": chunk.law_name,
                    "law_short": chunk.law_short,
                    "article_no": chunk.article_no,
                    "heading": chunk.heading,
                    "chapter": chunk.chapter,
                    "kind": chunk.kind,
                }
            )
    return chunks


def _build(domain: str) -> tuple[BM25Okapi, list[dict]]:
    """构建单个领域的索引。"""
    chunks = _load_chunks(domain)
    if not chunks:
        # 空语料也要给一个能调用的对象，避免上层到处判空
        return BM25Okapi([["_"]]), []

    # 用 text 而不是 content 建索引：text 带了《法名》第X条 的前缀，
    # 用户搜"劳动合同法"时能匹配上，召回更准
    corpus = [jieba.lcut(item["text"]) for item in chunks]
    return BM25Okapi(corpus), chunks


def _get(domain: str) -> tuple[BM25Okapi, list[dict]]:
    if domain in _cache:
        return _cache[domain]
    with _lock:
        # 双检锁：并发首次访问时避免重复构建
        if domain not in _cache:
            _cache[domain] = _build(domain)
            logger.info("BM25 索引就绪：%s（%d 条）", domain, len(_cache[domain][1]))
        return _cache[domain]


def search(
    query: str,
    domains: Optional[list[str]] = None,
    top_k: int = 8,
) -> list[dict]:
    """BM25 检索。

    Args:
        query: 用户问题（中文原文，内部会分词）
        domains: 限定检索的领域列表；None 表示全部六个领域
        top_k: 每个领域返回多少条

    Returns:
        和 `milvus_store.search` 同构的候选列表，额外带 `source="bm25"`。
        score 是 BM25 分（0 到几十，和余弦相似度不是一个量纲，
        上层融合时必须用 RRF，不能直接比大小）。
    """
    text = (query or "").strip()
    if not text:
        return []

    targets = domains or list(LAW_DOMAINS.keys())
    tokens = jieba.lcut(text)
    # 三重过滤：空白/单字标点、停用词、纯数字
    tokens = [
        t for t in (tok.strip() for tok in tokens)
        if t and len(t) > 1 and t not in _STOPWORDS and not t.isdigit()
    ]

    if not tokens:
        return []

    results: list[dict] = []
    for domain in targets:
        bm25, chunks = _get(domain)
        if not chunks:
            continue

        scores = bm25.get_scores(tokens)
        # 取分数最高的 top_k 个；BM25 分可能为 0（一个词都没命中），过滤掉
        ranked = sorted(
            ((score, idx) for idx, score in enumerate(scores) if score > 0),
            reverse=True,
        )[:top_k]

        for score, idx in ranked:
            item = dict(chunks[idx])
            item["score"] = float(score)
            item["source"] = "bm25"
            results.append(item)

    return results


def warmup(domains: Optional[list[str]] = None) -> int:
    """预热：提前把索引建好，避免第一个用户等 5 秒。

    jieba 首次加载词典要 3—5 秒，之后每个领域建索引只要几百毫秒。
    放在服务启动时做，用户感知不到。

    返回实际构建的领域数。
    """
    import time

    started = time.perf_counter()
    targets = domains or list(LAW_DOMAINS.keys())
    for domain in targets:
        _get(domain)
    logger.info(
        "BM25 预热完成：%d 个领域，耗时 %.1fs", len(targets), time.perf_counter() - started
    )
    return len(targets)


def invalidate(domain: Optional[str] = None) -> None:
    """清缓存。重建索引后必须调用，否则 BM25 用的还是旧语料。"""
    with _lock:
        if domain is None:
            _cache.clear()
            logger.info("BM25 缓存已全部清空")
        else:
            _cache.pop(domain, None)
            logger.info("BM25 缓存已清空：%s", domain)
