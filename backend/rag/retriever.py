"""混合检索层：把"结构化精确查询"和"向量语义召回"揉在一起。

这是整个 RAG 里最值得讲的一层，核心是一个判断：

    法律问答有两种截然不同的问题形态。
    A 类："劳动合同法第十九条怎么规定" —— 有明确的法名和条号，答案是唯一的。
    B 类："公司不给我加班费怎么办"     —— 口语化，没有关键词，只能靠语义理解。

    纯向量检索在 A 类上会翻车：它能召回"相邻的几条法条"，但未必正好是第十九条。
    纯数据库查询在 B 类上完全无能为力。

所以这里做三路召回 + 一次重排：
    第 1 路  结构化信号直查（法名 + 条号命中 MySQL）  —— 精确，权重最高
    第 2 路  向量语义检索（跨领域，可指定 domain）    —— 覆盖面
    第 3 路  领域词表扩展后的二次检索                  —— 补召回（口语 -> 法言法语）
    最后用 Reranker 统一重排，用原始问题（不是扩展后的）作为 query。
"""
from __future__ import annotations

import re
from typing import Optional

from sqlalchemy.orm import Session

from common.logger import get_logger
from config import (
    BM25_TOP_K,
    DEFAULT_RERANK_N,
    DEFAULT_TOP_K,
    LAW_DOMAINS,
    RRF_K,
    USE_BM25,
    collection_name,
)
from dao import statute_dao
from rag import bm25_index, milvus_store
from rag.embedder import get_embedder
from rag.reranker import get_reranker

logger = get_logger("retriever")

# 条号正则：第十九条 / 第19条 / 一千零七十九条
ARTICLE_PATTERN = re.compile(r"第[零一二三四五六七八九十百千万0-9]{1,7}条")
# 书名号里的法律名：《劳动合同法》
LAW_IN_BOOK_MARKS = re.compile(r"《([^》]{2,30})》")

# ---------------------------------------------------------------------------
# 领域词表：把老百姓的口语映射到法言法语。
# 这一步零成本（不调用 LLM），但能明显改善短问题的召回。
# 只做"一词多表"的补充，不替换原问题。
# ---------------------------------------------------------------------------
DOMAIN_LEXICON: dict[str, list[tuple[str, str]]] = {
    "labor": [
        ("辞退", "用人单位单方解除劳动合同 经济补偿"),
        ("开除", "用人单位解除劳动合同 赔偿金"),
        ("裁员", "经济性裁员 二十人以上 提前三十日"),
        ("加班费", "延长工作时间 加班工资 百分之一百五十"),
        ("试用期", "试用期期限 最长六个月"),
        ("不签合同", "未订立书面劳动合同 二倍工资"),
        ("工伤", "工伤认定 工伤保险待遇"),
        ("社保", "社会保险 用人单位缴纳"),
        ("竞业", "竞业限制 经济补偿"),
        ("产假", "女职工产假 生育津贴"),
    ],
    "civil": [
        ("离婚", "离婚 感情破裂 子女抚养 夫妻共同财产"),
        ("彩礼", "彩礼返还 未办理结婚登记"),
        ("借钱不还", "民间借贷 借款合同 利息 诉讼时效"),
        ("遗产", "继承 法定继承 遗嘱"),
        ("房东", "房屋租赁 承租人 押金 优先购买权"),
        ("被打", "人身损害 侵权责任 赔偿"),
        ("定金", "定金罚则 违约金"),
        ("合同违约", "违约责任 继续履行 赔偿损失"),
    ],
    "criminal": [
        ("被骗", "诈骗罪 数额较大 电信网络诈骗"),
        ("酒驾", "危险驾驶罪 醉酒驾驶 血液酒精含量"),
        ("打架", "故意伤害罪 寻衅滋事 治安管理处罚"),
        ("偷东西", "盗窃罪 数额较大 多次盗窃"),
        ("正当防卫", "正当防卫 防卫过当 特殊防卫"),
        ("坐牢", "有期徒刑 量刑 缓刑"),
    ],
    "business": [
        ("退钱", "消费者权益 七日无理由退货 三倍赔偿"),
        ("假货", "销售假冒伪劣商品 惩罚性赔偿"),
        ("开公司", "有限责任公司 设立 股东出资"),
        ("股权", "股权转让 股东权利 优先购买权"),
        ("吃坏肚子", "食品安全 十倍赔偿 不符合食品安全标准"),
        ("个体户", "个体工商户 登记 经营"),
    ],
    "digital": [
        ("抄袭", "著作权 复制权 侵权赔偿"),
        ("盗图", "信息网络传播权 侵权"),
        ("商标", "商标注册 近似 侵权"),
        ("个人信息", "个人信息处理 告知同意 敏感个人信息"),
        ("诈骗电话", "电信网络诈骗 防范 举报"),
        ("表情包", "著作权 合理使用"),
    ],
    "procedure": [
        ("起诉", "民事起诉 管辖 立案 起诉状"),
        ("告状", "民事诉讼 第一审普通程序"),
        ("上诉", "第二审程序 上诉期限 十五日"),
        ("告政府", "行政诉讼 行政复议 受案范围"),
        ("仲裁", "劳动仲裁 仲裁时效 一裁终局"),
        ("请律师", "法律援助 申请条件"),
        ("过期", "诉讼时效 三年 中止 中断"),
    ],
}


# 从问题里抠法律名的模式：以"法"或"法典"结尾的中文片段
# {1,8} 而不是 {2,8}，因为"民法典"要拆成「民」+「法典」
_LAW_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fa5]{1,8}(?:法典|法)")

# 这些是"法"字结尾但显然不是法律名的词，避免把"有什么办法"识别成法律
_LAW_TOKEN_STOPWORDS = {
    "办法", "方法", "做法", "说法", "看法", "想法", "手法", "合法", "违法", "司法", "执法",
}


def _detect_structured_signals(query: str, known_laws: list[str]) -> dict:
    """从问题里抠出"法名 + 条号"这种可以精确查询的结构化信号。

    返回的 `law_names` 是**候选列表**，不是一个确定值 —— 这一点很关键。

    踩过的坑：用户问"民法典第一千零四十七条"，库里 6 个民法典分编
    （总则编/婚姻家庭编/合同编/物权编/侵权责任编/继承编）名字里都含"民法典"，
    只取第一个会查到错误的编，然后查不到条号就放弃了。

    正确做法是把 6 个候选都返回，上层按顺序逐个精确查询，
    谁的条号对得上就用谁 —— 条号本身就能区分是哪一编。
    """
    article_match = ARTICLE_PATTERN.search(query)
    article_no = article_match.group(0) if article_match else ""

    candidates: list[str] = []

    # ① 优先认书名号里的法名：《劳动合同法》
    for mark in LAW_IN_BOOK_MARKS.findall(query):
        for law in known_laws:
            if mark in law or law in mark or law.replace("中华人民共和国", "") in mark:
                if law not in candidates:
                    candidates.append(law)
        if candidates:
            break

    # ② 没写书名号：从问题里抠"XX法/XX法典"，反向看哪部法律的名称包含它。
    #    只在有明确条号时才做，否则"有什么办法"这种会被误识别。
    if not candidates and article_no:
        for token in _LAW_TOKEN_PATTERN.findall(query):
            if token in _LAW_TOKEN_STOPWORDS:
                continue
            for law in known_laws:
                if token in law and law not in candidates:
                    candidates.append(law)

    return {
        "law_name": candidates[0] if candidates else "",
        "law_names": candidates,
        "article_no": article_no,
    }


def _normalize_article_no(raw: str) -> str:
    """把"第19条"统一成"第十九条"，去匹配数据库里的写法。"""
    digits = {
        "0": "零", "1": "一", "2": "二", "3": "三", "4": "四",
        "5": "五", "6": "六", "7": "七", "8": "八", "9": "九",
    }
    if raw.isdigit():
        return "".join(digits[d] for d in raw)
    return raw


def _expand_query(query: str, domain: Optional[str]) -> str:
    """领域词表扩展。只在问题较短（<24 字）时启用 —— 长问题本身信息已经足够，
    再塞词反而会把语义拉偏。"""
    if len(query) > 24:
        return query

    domains = [domain] if domain and domain in DOMAIN_LEXICON else list(DOMAIN_LEXICON)
    hits = []
    for key in domains:
        for colloquial, formal in DOMAIN_LEXICON[key]:
            if colloquial in query:
                hits.append(formal)
    if not hits:
        return query
    return f"{query} {' '.join(dict.fromkeys(hits))}"
def _rrf_key(hit: dict) -> str:
    """融合时的去重键。三级优先，每一级都解决一个具体的坑：

    1. **法条 → (法律名, 条号)**
       结构化直查的 chunk_id 是 `sql_123`，向量召回的是 md5 哈希，
       同一个法条在两路的 id 完全不同，只能靠业务字段识别。

    2. **解读段落 → chunk_id**
       这里踩过一个很隐蔽的坑：同一条 passage 经 BM25 和向量两路召回时，
       `text` 字段是不一样的 ——
         向量路返回 content（纯正文，213 字）
         BM25 路返回 text（带「《法名》章 标题」前缀，244 字）
       所以按 text[:60] 去重根本合并不了，上下文里同一条内容会出现两遍，
       白烧 token 还让模型以为有两份依据。
       chunk_id 是建索引时算的 md5，两路一致，用它才可靠。

    3. **兜底 → 文本前缀**
       理论上走不到，留着防止 chunk_id 缺失时崩溃。
    """
    if hit.get("article_no"):
        return f"a::{hit.get('law_name', '')}::{hit['article_no']}"
    if hit.get("chunk_id"):
        return f"c::{hit['chunk_id']}"
    return f"p::{(hit.get('text') or '')[:60]}"


def _rrf_fuse(
    *rankings: list[dict], k: int = 60, weights: list[float] | None = None
) -> list[dict]:
    """Reciprocal Rank Fusion，融合多路异量纲的检索结果。

    公式：

        score(d) = Σ  1 / (k + rank_i(d))

    为什么必须用它，而不是继续加权求和：

        向量路的分数是余弦相似度，范围 [-1, 1]；
        BM25 路的分数是 0 到几十的词频加权。
        两者直接相加，BM25 的分数会把向量分完全压过去 —— 这是量纲问题，
        不是调权重能解决的。

    RRF 只看排名，不看绝对分数，天然免疫量纲差异。
    k 取 60 是论文里的经验值：k 越大，排名靠前的优势越平缓。

    传入的每个 ranking 内部必须已经按各自分数降序排好 —— RRF 只认顺序。

    weights 允许给不同路不同权重。本项目的用法：

        向量路   1.0    ← 主力
        BM25 路  1.0    ← 互补
        扩展路   0.6    ← 它是"猜你想问"，排名可信度低于原查询，必须降权

    不降权的后果实测过：问"老板不给加班费怎么办"，
    扩展路把"仲裁与法律援助""家务劳动补偿"顶到了前面。
    """
    fused: dict[str, dict] = {}

    for idx, ranking in enumerate(rankings):
        weight = weights[idx] if weights and idx < len(weights) else 1.0
        for rank, item in enumerate(ranking, start=1):
            key = _rrf_key(item)
            contribution = weight / (k + rank)

            if key in fused:
                # 同一条被多路命中，分数累加 —— 这正是 RRF 的语义：
                # 多个检索器都认为相关，可信度更高
                fused[key]["_rrf"] += contribution
                # 保留信息更全的那条（结构化命中带 chapter，向量命中可能没有）
                if item.get("source") == "structured":
                    rrf_score = fused[key]["_rrf"]
                    fused[key] = {**item, "_rrf": rrf_score}
            else:
                fused[key] = {**item, "_rrf": contribution}

    return sorted(fused.values(), key=lambda x: x["_rrf"], reverse=True)


def _ensure_article_quota(
    final: list[dict], shortlist: list[dict], rerank_n: int, minimum: int = 1
) -> list[dict]:
    """兜底：上下文里至少有 N 条法条原文，不能全是解读段落。

    这里踩过一个坑，值得记下来：

        最初写成"解读段落最多 1 条、其余全给法条原文"，想的是让模型少看二手信息。
        结果问"离婚时彩礼需要返还吗"时翻车了 —— 彩礼返还的核心规则本来就在
        司法解释里，我的语料把它写成了「要点：彩礼在什么情况下要返还」这种解读段落；
        强行换成《民法典》第 1087 条（离婚财产分割）、第 1091 条（离婚损害赔偿）
        这些"看起来有法条"的内容，反而把真正有用的答案挤掉了，模型只能硬着头皮
        讲财产分割和损害赔偿，完全跑题。

        所以配额只能做兜底，不能做强约束。排序交给 rerank，配额只在
        "一条法条原文都没有"时补一条，保证上下文里至少有个权威依据。
    """
    article_count = sum(
        1 for h in final if h.get("kind") == "article" and h.get("article_no")
    )
    if article_count >= minimum:
        return final

    need = minimum - article_count
    chosen = {
        (h.get("law_name"), h.get("article_no")) for h in final if h.get("article_no")
    }
    pool = [
        h
        for h in shortlist
        if h.get("kind") == "article"
        and h.get("article_no")
        and (h.get("law_name"), h.get("article_no")) not in chosen
    ]
    if not pool:
        return final

    extras = pool[:need]
    return final[: rerank_n - len(extras)] + extras


def retrieve(
    db: Session,
    query: str,
    domain: Optional[str] = None,
    top_k: int = DEFAULT_TOP_K,
    rerank_n: int = DEFAULT_RERANK_N,
    use_rerank: bool = True,
    api_key: str | None = None,
    use_bm25: bool | None = None,
) -> list[dict]:
    """执行三路召回 + 重排，返回最终上下文切片。"""
    query = (query or "").strip()
    if not query:
        return []

    known_laws = [item["law_name"] for item in statute_dao.list_laws(db)]
    signals = _detect_structured_signals(query, known_laws)

    # 四个容器：结构化 / 向量 / 扩展 / BM25。
    # 分开放是因为融合时权重不同 —— 见 _rrf_fuse 的说明。
    structured_hits: list[dict] = []
    vector_hits: list[dict] = []
    expanded_hits: list[dict] = []
    bm25_hits: list[dict] = []

    # ---------------- 第 1 路：结构化直查 ----------------
    if signals["article_no"] and signals["law_names"]:
        article_no = signals["article_no"]
        # 用户可能写的是"第19条"，数据库里是"第十九条"
        inner = article_no.replace("第", "").replace("条", "")
        normalized = f"第{_normalize_article_no(inner)}条"

        # 候选法律名可能有多个（6 个民法典分编都含"民法典"），
        # 逐个试，谁的条号对得上就用谁
        row = None
        for law in signals["law_names"]:
            row = statute_dao.find_by_article(db, law, article_no)
            if row is None and normalized != article_no:
                row = statute_dao.find_by_article(db, law, normalized)
            if row is not None:
                break

        if row is not None:
            structured_hits.append(
                {
                    "chunk_id": f"sql_{row.id}",
                    "text": f"《{row.law_short or row.law_name}》{row.article_no}"
                    f"{'【' + row.heading + '】' if row.heading else ''}\n{row.content}",
                    "display": row.content,
                    "domain": row.domain,
                    "filename": row.source_file or "",
                    "law_name": row.law_name,
                    "law_short": row.law_short or row.law_name,
                    "article_no": row.article_no,
                    "heading": row.heading or "",
                    "chapter": row.chapter or "",
                    "kind": "article",
                    "score": 1.0,          # 精确命中，直接给满分
                    "source": "structured",
                }
            )
            logger.info("结构化直查命中：%s %s", row.law_name, row.article_no)

    # ---------------- 第 2 路：向量语义检索 ----------------
    embedder = get_embedder()
    domains = [domain] if domain and domain in LAW_DOMAINS else list(LAW_DOMAINS)

    # 跨域检索时每个域少取一点，总候选数控制在 top_k 的 2 倍左右，
    # 否则 6 个域 × 8 条 = 48 条候选，Reranker 的费用和延迟都会上去
    per_domain = top_k if len(domains) == 1 else max(2, top_k // 2)

    vector = embedder.embed_query(query)
    for item in domains:
        hits = milvus_store.search(
            collection_name(item), vector, top_k=per_domain
        )
        for hit in hits:
            hit["source"] = "vector"
        vector_hits.extend(hits)

    # ---------------- 第 3 路：词表扩展补召回 ----------------
    expanded = _expand_query(query, domain)
    if expanded != query:
        logger.info("查询扩展：%s -> %s", query, expanded)
        expanded_vector = embedder.embed_query(expanded)
        for item in domains:
            for hit in milvus_store.search(
                collection_name(item), expanded_vector, top_k=max(2, per_domain // 2)
            ):
                # 扩展召回的分数打个折，避免它盖过原始问题的命中
                hit["score"] = hit.get("score", 0.0) * 0.92
                hit["source"] = "expanded"
                expanded_hits.append(hit)

    # ---------------- 第 4 路：BM25 稀疏检索 ----------------
    # 补向量检索的短板：精确关键词、罕见专有名词、条号字面匹配。
    # 语料从 md 直接解析并常驻内存，不依赖 Milvus 的可用性。
    # ⚠️ 明确条号的查询不跑 BM25。
    # 实测："劳动法第四十四条"会让 BM25 把《行政处罚法》第四十四条、
    # 《民法典》第四十四条全捞上来 —— 条号在 BM25 眼里只是两个词，
    # 它分不清是哪部法律的第几条。这类查询结构化直查已经 100% 准确，
    # 再多一路纯属噪音。
    explicit_article = bool(signals["article_no"] and signals["law_name"])
    # use_bm25 参数允许逐次调用覆盖全局开关 —— 评测脚本靠它做消融实验，
    # 对比"纯向量"和"向量+BM25"两组的指标差异
    bm25_enabled = USE_BM25 if use_bm25 is None else use_bm25
    if bm25_enabled and not explicit_article:
        bm25_hits = bm25_index.search(query, domains, top_k=BM25_TOP_K)
        if bm25_hits:
            logger.info("BM25 补召回 %d 条", len(bm25_hits))

    if not structured_hits and not vector_hits and not expanded_hits and not bm25_hits:
        return []

    # ---------------- 融合与重排 ----------------
    # 每路内部先按各自分数排（RRF 只认顺序）
    vector_hits.sort(key=lambda h: h.get("score", 0.0), reverse=True)
    expanded_hits.sort(key=lambda h: h.get("score", 0.0), reverse=True)
    bm25_hits.sort(key=lambda h: h.get("score", 0.0), reverse=True)

    # RRF 融合三路异量纲结果，按路给权重。
    # 为什么不能直接加权求和：余弦相似度在 [-1, 1]，BM25 在 0—几十，
    # 直接相加 BM25 会把向量分完全压过去。RRF 只看排名，免疫量纲差异。
    # 权重是实测调出来的，不是拍的：
    # BM25 权重 1.0 时，口语场景的 Recall@4 从 0.80 掉到 0.55 ——
    # 因为口语问句分词后有一堆虚词（怎么办/可以吗/我），BM25 靠这些词
    # 匹配到一堆含相同虚词但不相关的条文，把向量的好结果挤掉了。
    # 降到 0.5 后 BM25 只作为"补充信号"，不再主导排序。
    fused = _rrf_fuse(
        vector_hits, bm25_hits, expanded_hits,
        k=RRF_K, weights=[1.0, 0.5, 0.6],
    )

    # 结构化命中插到最前面 —— 它代表"用户明确问了这一条"，
    # 不该参与 RRF 的排名竞争（RRF 里它只有一路贡献，很容易被两路都命中的条目压过）
    if structured_hits:
        struct_keys = {_rrf_key(h) for h in structured_hits}
        fused = structured_hits + [h for h in fused if _rrf_key(h) not in struct_keys]

    # 送进精排的候选池大小。
    # 之前是 max(rerank_n*3, 12) = 12 条，实测太小 ——
    # 精排只在 12 条里挑 4 条，选择空间不足，判断偏差会直接丢答案。
    # 经典的 RAG 两阶段是粗排 50—100 条再精排 5 条，这里折中到 30。
    shortlist = fused[: max(rerank_n * 8, 30)]

    if use_rerank:
        final = get_reranker(api_key).rerank(query, shortlist, top_n=rerank_n)
    else:
        final = shortlist[:rerank_n]

    # 精排可能把结构化命中挤出去，这里做一次兜底：只要直查命中了，
    # 就一定放在第一位。"用户明确问第X条"的场景不该有第二种答案，
    # 哪怕 rerank 认为另一段解读文字更贴题 —— 用户要的是条文原文本身。
    structured = [c for c in fused if c.get("source") == "structured"]
    if structured:
        wanted = structured[0]
        rest = [
            item
            for item in final
            if not (
                item.get("article_no")
                and item.get("article_no") == wanted.get("article_no")
                and item.get("law_name") == wanted.get("law_name")
            )
        ]
        final = ([wanted] + rest)[:rerank_n]

    # 最后一道保险：确保上下文里至少有两条法条原文，不能全是解读段落
    final = _ensure_article_quota(final, shortlist, rerank_n)

    return final


def format_context(hits: list[dict], max_chars: int = 6000) -> str:
    """把检索结果拼成给大模型看的参考资料。

    每个片段都带 [编号] + 【类型】+ 出处，这里有个刻意的设计：

        给每条打上"条文原文"或"解读（非条文原文）"的类型标签。
        原因是实测发现，模型会把解读段落里的结论"就近归因"到上下文里
        另一条法条上 —— 比如把"试用期最长六个月"这段解读，说成是
        《劳动合同法》第二十条的规定（第二十条其实讲的是试用期工资）。

        加了类型标签之后，模型能看出哪段是条文、哪段是我们的解读，
        串条号的概率明显下降。这也是前端展示"依据"的数据基础。
    """
    if not hits:
        return "（未检索到相关法条）"

    blocks = []
    total = 0
    for idx, hit in enumerate(hits, start=1):
        law = hit.get("law_short") or hit.get("law_name") or "相关资料"
        article = hit.get("article_no") or ""
        heading = hit.get("heading") or ""

        if article:
            tag = "条文原文"
            title = f"《{law}》{article}"
            if heading:
                title += f"【{heading}】"
            # 不把章节（"一、工作时间"）写进给模型看的标题：
            # 章节信息对向量召回有用（已写进 chunk 前缀），但对生成没用，
            # 模型会把它当出处一起抄进答案，变成"《劳动法》第三十八条（一、工作时间）规定…"
        else:
            tag = "解读（非条文原文）"
            # 章节序号（"五、"）对模型没用，反而会被抄进答案变成
            # "《劳动法》五、实务问答·要点指出…"，去掉序号只留章节名
            chapter = re.sub(
                r"^[一二三四五六七八九十百]+、", "", hit.get("chapter") or ""
            ).strip()
            title = f"《{law}》{chapter or '相关解读'}"
            if heading:
                title += f"· {heading}"

        block = f"[{idx}]（{tag}）{title}\n{hit.get('text') or hit.get('display') or ''}"
        if total + len(block) > max_chars:
            break
        blocks.append(block)
        total += len(block)

    return "\n\n".join(blocks)


def to_source_payload(hits: list[dict]) -> list[dict]:
    """转成前端"参考依据"卡片需要的结构。

    关于 score 用哪一个，这里有个刻意的选择：

        智谱 rerank 的 relevance_score 在短文本上区分度很差 —— 一批语义相关的
        法条经常全是 0.99—1.0，前端显示"相关度 100%"反而不可信。

        所以前端展示用**余弦相似度**（vector_score，0.5—0.8 区间，有区分度），
        精排分只用于内部排序。两个分都返回，需要时可以对比着看。
    """
    payload = []
    for hit in hits:
        shown = hit.get("vector_score", hit.get("score"))
        payload.append(
            {
                "title": (
                    f"《{hit.get('law_short') or hit.get('law_name') or '资料'}》"
                    f"{hit.get('article_no') or ''}"
                    f"{'【' + hit['heading'] + '】' if hit.get('heading') else ''}"
                ).strip(),
                "text": (hit.get("display") or hit.get("text") or "")[:500],
                "score": round(float(shown), 4) if shown is not None else None,
                "rerank_score": (
                    round(float(hit["score"]), 4)
                    if hit.get("reranked") and hit.get("score") is not None
                    else None
                ),
                "law_name": hit.get("law_name", ""),
                "article_no": hit.get("article_no", ""),
                "domain": hit.get("domain", ""),
                "domain_label": LAW_DOMAINS.get(hit.get("domain", ""), {}).get(
                    "label", ""
                ),
                "filename": hit.get("filename", ""),
                "kind": hit.get("kind", "passage"),
                "reranked": bool(hit.get("reranked")),
                "source": hit.get("source", "vector"),
            }
        )
    return payload
