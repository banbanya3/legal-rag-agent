"""法律问答 Agent 的编排层 —— 整个项目的中枢。

为什么不照搬"ReAct 多轮工具调用"：

    ReAct 的典型链路是 思考 -> 调工具 -> 观察 -> 再思考 -> 再调工具 -> 回答。
    在法律问答里这套东西代价很高：
      · 每多一轮就多一次完整的 LLM 调用，端到端从 3 秒涨到 10 秒以上；
      · 通用模型对"该查劳动合同法还是民法典"的判断本来就不稳定，
        让它自由探索反而容易绕圈；
      · 法律问题的工具选择空间其实很小 —— 无非"查哪个领域"。

所以这里用**三段式编排**替代自由 ReAct，本质上仍然是 Agent 的决策链：
    ① Router   一次 LLM 调用，判断意图（法条查询/法律咨询/闲聊）、
               锁定法律领域、改写检索式（消解多轮指代）；
    ② Retrieve 按路由结果执行混合检索（结构化直查 + 向量 + 词表扩展）+ 精排；
    ③ Generate 把法条按 [1][2][3] 编号注入，流式生成带引用的答案。

端到端固定 2 次 LLM 调用，延迟和成本都可预测；
而且每一段决策都能单独测试、单独打日志，出了错知道该改哪里。
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import AsyncGenerator, Optional

from sqlalchemy.orm import Session

from common.logger import get_logger
from config import DEFAULT_RERANK_N, DEFAULT_TOP_K, LAW_DOMAINS
from llm.client import LLMError, build_client
from llm.prompts import (
    CHITCHAT_SYSTEM,
    LEGAL_QA_NO_CONTEXT_SYSTEM,
    LEGAL_QA_SYSTEM,
    ROUTER_SYSTEM,
    build_router_user,
)
from rag.retriever import format_context, retrieve, to_source_payload

logger = get_logger("agent")

# 规则路由的关键词表。LLM 路由失败时用它兜底，也用于"明显是法条查询"时的快速通道。
DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "labor": ("劳动合同", "试用期", "加班", "工资", "辞退", "裁员", "工伤", "社保",
              "年假", "竞业", "劳动仲裁", "经济补偿", "产假", "拖欠"),
    "civil": ("离婚", "结婚", "彩礼", "抚养", "继承", "遗产", "遗嘱", "借款", "欠款",
              "房租", "房东", "租客", "邻居", "侵权", "赔偿", "定金", "违约金", "合同"),
    "criminal": ("犯罪", "判刑", "坐牢", "盗窃", "诈骗", "醉驾", "酒驾", "故意伤害",
                 "正当防卫", "缓刑", "取保候审", "治安", "拘留", "刑事"),
    "business": ("公司", "股东", "股权", "合伙", "消费者", "退货", "假货", "食品安全",
                 "产品质量", "个体户", "营业执照", "发票", "税"),
    "digital": ("著作权", "版权", "商标", "专利", "抄袭", "个人信息", "隐私", "数据",
                "网络", "电信诈骗", "平台", "算法"),
    "procedure": ("起诉", "立案", "管辖", "上诉", "诉讼时效", "行政复议", "行政诉讼",
                  "仲裁", "法律援助", "强制执行", "举证", "判决"),
}

# 明确指向"查某一条"的句式
STATUTE_LOOKUP_PATTERN = re.compile(r"第[零一二三四五六七八九十百千万0-9]{1,7}条")


# ===========================================================================
# 路由
# ===========================================================================
def _rule_route(query: str) -> dict:
    """纯规则的兜底路由。零延迟、零成本，LLM 挂了系统也能用。"""
    domain_scores = {}
    for key, words in DOMAIN_KEYWORDS.items():
        score = sum(1 for w in words if w in query)
        if score:
            domain_scores[key] = score

    domain = max(domain_scores, key=domain_scores.get) if domain_scores else "all"

    if STATUTE_LOOKUP_PATTERN.search(query) or "《" in query:
        intent = "statute"
    elif domain_scores:
        intent = "advice"
    elif len(query) <= 8 and not any(k in query for k in ("吗", "怎么", "什么", "如何")):
        intent = "chitchat"
    else:
        intent = "advice"

    return {
        "intent": intent,
        "domain": domain,
        "rewritten": query,
        "need_retrieval": intent != "chitchat",
        "by": "rule",
    }


def _parse_json_block(text: str) -> Optional[dict]:
    """从模型输出里抠出 JSON。

    即使加了"只输出 JSON"的约束，模型偶尔还是会裹一层 ```json 代码块
    或者前面加一句"好的"。这里用最宽松的方式取第一个 { 到最后一个 }。
    """
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start: end + 1])
    except json.JSONDecodeError:
        return None


async def route(
    cfg, query: str, history: list[dict], allow_llm: bool = True
) -> dict:
    """判断意图 + 锁定领域 + 改写查询。

    有两处刻意的优化：
    1. 问题里已经出现"第X条"或书名号法律名 —— 这是确定性极高的信号，
       直接走规则路由，省掉一次 LLM 调用（约 1.5 秒）；
    2. LLM 返回的 domain 如果不在注册表里，一律回退到 "all"，不让脏数据往下游传。
    """
    rule = _rule_route(query)

    if not allow_llm or (rule["intent"] == "statute" and rule["domain"] != "all"):
        logger.info("规则路由：%s", rule)
        return rule

    llm = build_client(cfg)
    try:
        raw = await llm.achat(
            [
                {"role": "system", "content": ROUTER_SYSTEM},
                {"role": "user", "content": build_router_user(query, history)},
            ],
            temperature=0.0,
            # 240 时偶尔会把 JSON 截断（rewritten 字段写太长），
            # 截断后解析失败会回退规则路由 —— 功能不坏，但白花一次调用。
            # 提到 400 留足余量，成本差异可以忽略。
            max_tokens=400,
            timeout=30,
        )
        parsed = _parse_json_block(raw)
        if not parsed:
            logger.warning("路由输出无法解析为 JSON，回退规则路由：%s", raw[:120])
            return rule

        domain = str(parsed.get("domain") or "all").strip().lower()
        if domain not in LAW_DOMAINS:
            domain = "all"
        intent = str(parsed.get("intent") or "advice").strip().lower()
        if intent not in ("statute", "advice", "chitchat"):
            intent = "advice"

        decision = {
            "intent": intent,
            "domain": domain,
            "rewritten": (parsed.get("rewritten") or query).strip() or query,
            "need_retrieval": bool(parsed.get("need_retrieval", intent != "chitchat")),
            "by": "llm",
        }
        logger.info("LLM 路由：%s", decision)
        return decision

    except LLMError as exc:
        logger.warning("路由调用失败，回退规则路由：%s", exc)
        return rule


# ===========================================================================
# 生成
# ===========================================================================
def _build_messages(
    cfg,
    decision: dict,
    query: str,
    context: str,
    history: list[dict],
) -> list[dict]:
    """组装最终送给大模型的 messages。

    历史只带最近 3 轮：法律问答里太早的上下文基本是干扰，
    而且会让模型把上一件事的细节套到这一件上。
    """
    if decision["intent"] == "chitchat":
        system = CHITCHAT_SYSTEM
    elif context:
        system = LEGAL_QA_SYSTEM.format(context=context)
    else:
        system = LEGAL_QA_NO_CONTEXT_SYSTEM

    messages = [{"role": "system", "content": system}]

    for msg in history[-6:]:
        role = msg.get("role")
        if role in ("user", "assistant") and msg.get("content"):
            messages.append({"role": role, "content": msg["content"][:1200]})

    # 送给模型的是改写后的检索式，但用户看到的原始问题要保留语义，
    # 所以把两者都给它，让它知道"用户原话"和"我理解的意思"
    if decision.get("rewritten") and decision["rewritten"] != query:
        messages.append(
            {
                "role": "user",
                "content": f"{query}\n\n（检索用的规范化表述：{decision['rewritten']}）",
            }
        )
    else:
        messages.append({"role": "user", "content": query})

    return messages


def _status(stage: str, message: str, **extra) -> dict:
    payload = {"type": "status", "stage": stage, "message": message}
    payload.update(extra)
    return payload


def _sanitize_answer(text: str) -> str:
    """清理模型输出里常见的两类"格式污染"。

    实测发现两件事，都靠提示词压不住，只能在生成后处理：

    1. 模型会在答案末尾复述"【参考资料】[1]《劳动合同法》第十九条……"。
       这属于把给它的元信息当成输出内容，前端已经有独立的"引用的法条"卡片，
       正文里再来一遍既冗余又难看。
    2. 模型偶尔会在正文里加 [1] [2] 角标，但前端并不渲染这种角标，
       留着只是干扰阅读。

    处理策略是保守的：只截断出现在后半段的参考资料列表，避免误伤正文。
    """
    text = (text or "").strip()
    if not text:
        return text

    # 1. 截掉尾部复述的参考资料
    for marker in ("【参考资料】", "【参考法条】", "参考资料：", "参考法条：", "（参考资料"):
        idx = text.rfind(marker)
        if idx > len(text) * 0.4:
            text = text[:idx].rstrip()
            break

    # 2. 去掉行内角标（只处理独立的 [数字]，不动 markdown 链接）
    text = re.sub(r"(?<!\\)\[\d{1,2}\]", "", text)

    # 3. 截断后可能留下孤零零的分隔符
    text = re.sub(r"[\s\-—]{2,}$", "", text)
    return text.strip()


async def stream_answer(
    db: Session,
    cfg,
    query: str,
    history: list[dict] | None = None,
    use_rerank: bool | None = None,
    top_k: int | None = None,
    rerank_n: int | None = None,
    direct: bool = False,
) -> AsyncGenerator[dict, None]:
    """核心链路，逐段产出事件。

    调用方（chat_api）只负责把事件转成 SSE，不需要懂内部逻辑。
    这样同一个生成器既能喂给 SSE 接口，也能在测试里直接遍历断言。

    `direct=True` 是「直聊模式」：跳过路由和检索，直接把问题交给模型。
    前端顶栏那个「直聊」开关走的就是这条路径 —— 用户明确想聊两句、
    不要法条依据时用，响应快（省掉一次路由调用 + 一次检索 + 一次精排）。
    """
    started = time.perf_counter()
    history = history or []
    query = (query or "").strip()

    top_k = top_k or getattr(cfg, "top_k", None) or DEFAULT_TOP_K
    rerank_n = rerank_n or getattr(cfg, "rerank_n", None) or DEFAULT_RERANK_N
    if use_rerank is None:
        use_rerank = bool(getattr(cfg, "use_rerank", True))

    # ---------------- ① 路由 ----------------
    if direct:
        # 直聊：不调路由器，直接给一个"不检索"的决策
        decision = {
            "intent": "advice",
            "domain": "all",
            "rewritten": query,
            "need_retrieval": False,
            "by": "direct",
        }
        yield _status(
            "routed", "直聊模式 · 跳过检索，由模型直接回答", intent="advice", domain="all"
        )
        domain_label = "全部法律领域"
        intent_label = "直聊"
    else:
        yield _status("route", "正在理解你的问题…")
        decision = await route(cfg, query, history)
        domain_label = (
            LAW_DOMAINS[decision["domain"]]["label"]
            if decision["domain"] in LAW_DOMAINS
            else "全部法律领域"
        )
        intent_label = {
            "statute": "法条查询",
            "advice": "法律咨询",
            "chitchat": "日常对话",
        }.get(decision["intent"], "法律咨询")
        yield _status(
            "routed",
            f"识别为{intent_label} · 检索范围：{domain_label}",
            intent=decision["intent"],
            domain=decision["domain"],
            rewritten=decision["rewritten"],
        )

    # ---------------- ② 检索 ----------------
    hits: list[dict] = []
    if decision["need_retrieval"]:
        yield _status("retrieve", f"正在检索{domain_label}相关条文…")
        try:
            # retrieve 内部是同步的（Milvus SDK、httpx 同步客户端、rerank 都是），
            # 扔到线程池执行，避免卡住事件循环。
            # 用标准库的 asyncio.to_thread 而不是 fastapi 的 run_in_threadpool，
            # 是为了让 service 层保持零框架依赖 —— 换 Web 框架时这里一行不用改。
            hits = await asyncio.to_thread(
                retrieve,
                db,
                decision["rewritten"] or query,
                domain=decision["domain"] if decision["domain"] != "all" else None,
                top_k=top_k,
                rerank_n=rerank_n,
                use_rerank=use_rerank,
                api_key=getattr(cfg, "api_key", None),
            )
        except Exception as exc:  # noqa: BLE001
            # 检索挂了也要继续答，只是答得保守一些。这是"降级"而不是"失败"。
            logger.error("检索失败：%s", exc)

        if hits:
            yield _status("retrieved", f"命中 {len(hits)} 条相关条文")
            yield {"type": "sources", "sources": to_source_payload(hits)}
        else:
            yield _status("retrieved", "未检索到直接对应的法条")

    # ---------------- ③ 生成 ----------------
    llm = build_client(cfg)
    if llm.is_reasoning:
        # 推理模型要先想几百字才吐第一个字，不提前说明的话用户会以为卡死了
        yield _status("generate", "推理模型正在思考，首字会比平时慢 5—10 秒…")
    else:
        yield _status("generate", "正在组织回答…")

    context = format_context(hits) if hits else ""
    messages = _build_messages(cfg, decision, query, context, history)

    answer_parts: list[str] = []
    try:
        # 不传 max_tokens，交给 LLMClient 按模型类型决定：
        # 普通模型 1600（法律回答要精准不要篇幅），推理模型 4096（思考过程要占一大半）。
        # 之前写死 1600，glm-5.3-flash 的思维链把它烧光，正文变空，
        # 兜底逻辑又把英文草稿当答案输出，整段回答全是"Let me draft…"。
        async for piece in llm.astream_chat(messages):
            answer_parts.append(piece)
            yield {"type": "delta", "text": piece}
    except LLMError as exc:
        yield {"type": "error", "message": str(exc)}
        return

    answer = _sanitize_answer("".join(answer_parts))
    if not answer:
        answer = "模型没有返回内容。请检查设置中的模型名称与 API Key 是否匹配。"

    elapsed = int((time.perf_counter() - started) * 1000)
    yield {
        "type": "answer",
        "answer": answer,
        "sources": to_source_payload(hits),
        "elapsed_ms": elapsed,
        "intent": decision["intent"],
        "domain": decision["domain"],
        "rewritten": decision["rewritten"],
    }


async def answer_once(
    db: Session,
    cfg,
    query: str,
    history: list[dict] | None = None,
    use_rerank: bool | None = None,
) -> dict:
    """非流式版本。

    直接复用 stream_answer 的事件流，把 delta 拼起来 ——
    保证流式和非流式走的是同一套逻辑，不会出现"接口 A 能答、接口 B 答不出来"。
    """
    final = {"answer": "", "sources": [], "elapsed_ms": 0}
    async for event in stream_answer(db, cfg, query, history, use_rerank):
        if event["type"] == "answer":
            final.update(event)
        elif event["type"] == "error":
            raise LLMError(event["message"])
    return final
