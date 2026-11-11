"""MCP 服务：把法律知识库暴露给 Claude Desktop / Cursor 等 AI 客户端。

## 这是什么

MCP（Model Context Protocol）是 Anthropic 提出的开放协议，
让 AI 客户端能以标准方式连接外部工具和数据源。

平时我们的知识库只服务自己的 Vue 前端。加上这一层之后，
Claude Desktop、Cursor 这类支持 MCP 的客户端配置一下，
就能直接查这 462 条法条 —— 同一套检索能力，两个入口。

## 为什么走 HTTP 而不是直连 Milvus

MCP 服务是**独立进程**，由客户端（比如 Claude Desktop）拉起。
如果它自己去打开 `storage/milvus_lite/legal_law.db`，
会和正在运行的 FastAPI 抢库锁（Milvus Lite 单进程独占），
报 `DataDirLockedError`。

所以分工是：

    search_law   → HTTP 调 FastAPI 的 /api/statutes/semantic
                   （语义检索需要向量库，只能由主服务代劳）
    get_article  → 直接查 MySQL
    list_laws    → 直接查 MySQL
                   （MySQL 支持多连接，不需要经过主服务）

好处是**后端没启动时，精确查条和清单查询仍然可用**，
只有语义检索会降级成 MySQL 关键词匹配。

## 启动

    cd backend
    python mcp_server.py          # 走 stdio，供客户端拉起

配置示例见 docs/08-MCP服务接入.md。

## 一个必须知道的坑

stdio 传输用 **stdout** 传 JSON-RPC 帧。任何 print 到 stdout 的内容
（包括日志）都会把协议冲坏，客户端报"无法解析响应"。

所以 `common/logger.py` 和 `config.py` 的输出都改成 stderr 了。
如果你要在工具里调试，也用 `print(..., file=sys.stderr)`。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 允许直接 `python mcp_server.py` 运行（客户端拉起时 cwd 不一定在 backend）
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import httpx
from mcp.server.mcpserver import MCPServer

from common.logger import get_logger
from config import LAW_DOMAINS, settings
from dao import statute_dao
from dao.db import SessionLocal

logger = get_logger("mcp")

# 主服务的地址。MCP 只做协议转换，检索逻辑全在后端。
BACKEND_URL = f"http://{settings.HOST}:{settings.PORT}"
DOCS_HINT = "（提示：语义检索需要主服务在跑，执行 `cd backend && python main.py`）"

mcp = MCPServer(
    "legal-kb",
    instructions=(
        "中国法律知识库。收录 32 部法律、462 条法条，覆盖民事、劳动、刑事、"
        "商事、数字与知产、程序救济六个领域。\n\n"
        "回答法律问题时，优先用 search_law 检索相关条文，"
        "引用时标明《法律名称》第X条。用户明确问某一条时用 get_article 精确查询。"
    ),
)


# ===========================================================================
# 内部工具
# ===========================================================================
def _resolve_domain(domain: str) -> str:
    """把用户可能传的中文领域名转成内部 key。

    模型有时会传 "劳动法" 或 "劳动与社会保障"，也可能传 "labor"。
    统一兼容一下，免得因为参数格式直接失败。
    """
    if not domain:
        return ""
    text = domain.strip()
    if text in LAW_DOMAINS:
        return text

    for key, meta in LAW_DOMAINS.items():
        if text == meta["label"] or text in meta["label"] or meta["label"] in text:
            return key
    return ""


def _fallback_keyword_search(keyword: str, domain: str, limit: int) -> str:
    """后端不可用时的降级：MySQL 关键词匹配。

    只认字面，召回质量比语义检索差一截，但至少能用。
    """
    db = SessionLocal()
    try:
        data = statute_dao.search(
            db,
            keyword=keyword,
            law_name="",
            domain=_resolve_domain(domain),
            page=1,
            page_size=limit,
        )
    finally:
        db.close()

    if not data["items"]:
        return f"没查到包含「{keyword}」的条文。换个关键词试试，或者用更宽泛的说法。"

    lines = [f"关键词匹配到 {data['total']} 条（后端未启动，已降级为字面检索）：\n"]
    for i, item in enumerate(data["items"], 1):
        lines.append(f"### [{i}] 《{item['law_short']}》{item['article_no']}")
        if item["heading"]:
            lines.append(f"主旨：{item['heading']}")
        lines.append(item["content"])
        lines.append("")
    return "\n".join(lines)


# ===========================================================================
# 工具 1：语义检索
# ===========================================================================
@mcp.tool()
def search_law(query: str, domain: str = "", top_k: int = 5) -> str:
    """按语义检索法条，能处理口语化的问题。

    什么时候用：用户描述了一个处境，想知道法律怎么规定。
    比如「老板不给加班费怎么办」「离婚彩礼要退吗」「被狗咬了谁赔」。
    这类问题没有明确的法条编号，靠语义匹配才能召回对的条文。

    什么时候不用：用户已经在问某一条的具体内容，用 get_article 更准。

    Args:
        query: 自然语言描述的问题或关键词，中文。
        domain: 限定检索范围。可传领域 key（civil/labor/criminal/business/
            digital/procedure）或中文名（民事/劳动/刑事/商事/数字/程序）。
            留空表示六个领域全搜。
        top_k: 返回几条，1—12，默认 5。一般 3—5 条足够。

    Returns:
        按相关度排序的法条列表，含出处、条号、原文和相似度。
    """
    payload = {"query": query, "domain": _resolve_domain(domain), "top_k": top_k}

    try:
        resp = httpx.get(
            f"{BACKEND_URL}/api/statutes/semantic",
            params=payload,
            timeout=60,
            trust_env=False,
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("语义检索失败，降级为关键词检索：%s", exc)
        return _fallback_keyword_search(query, domain, top_k)

    if body.get("code") != 0:
        return _fallback_keyword_search(query, domain, top_k)

    items = body["data"].get("items") or []
    if not items:
        return (
            f"知识库中没有找到与「{query}」相关的条文。\n"
            "可以换个说法再试，或者用 list_laws 看看收录了哪些法律。"
        )

    lines = [f"检索「{query}」命中 {len(items)} 条：\n"]
    for i, item in enumerate(items, 1):
        score = f"{item['score']:.2f}" if item.get("score") is not None else "-"
        lines.append(f"### [{i}] {item['title']}")
        lines.append(f"相关度 {score}｜{item.get('domain_label', '')}")
        lines.append(item["text"])
        lines.append("")

    lines.append("引用时请标明出自哪部法律的第几条；标「要点」的是解读段落，不是条文原文。")
    return "\n".join(lines)


# ===========================================================================
# 工具 2：按条号精确查询
# ===========================================================================
@mcp.tool()
def get_article(law_name: str, article_no: str) -> str:
    """按法律名称和条号精确查询条文原文。

    什么时候用：用户明确说了「第几条」。比如「劳动合同法第十九条」
    「民法典第1047条」「刑法第二十条」。这种情况用精确查询，
    不要用语义检索 —— 向量检索可能召回相邻的条文，未必是用户问的那一条。

    Args:
        law_name: 法律名称，全称或简称都行。如「劳动合同法」
            「中华人民共和国劳动合同法」「民法典」。
        article_no: 条号，中文数字。如「第十九条」「第一千零七十九条」。
            传阿拉伯数字（19）也会自动转换。

    Returns:
        条文原文，附带所属章节和施行日期。没收录时返回提示。
    """
    # 允许传阿拉伯数字
    if article_no.strip().isdigit():
        article_no = f"第{_digits_to_cn(article_no.strip())}条"
    elif not article_no.startswith("第"):
        article_no = f"第{article_no}条"

    db = SessionLocal()
    try:
        row = statute_dao.find_by_article(db, law_name, article_no)
        if row is None:
            return (
                f"知识库里没有收录《{law_name}》{article_no}。\n"
                "可能是这部法律不在收录范围内（目前 32 部），或者条号写错了。\n"
                "可以用 list_laws 查看完整清单。"
            )
        data = statute_dao.to_dict(row)
    finally:
        db.close()

    lines = [
        f"《{data['law_name']}》{data['article_no']}"
        + (f"【{data['heading']}】" if data["heading"] else ""),
        "",
    ]
    meta = []
    if data["chapter"]:
        meta.append(f"所属：{data['chapter']}")
    if data["effective_date"]:
        meta.append(f"施行：{data['effective_date']}")
    if meta:
        lines.append("｜".join(meta))
        lines.append("")
    lines.append(data["content"])
    return "\n".join(lines)


def _digits_to_cn(text: str) -> str:
    """阿拉伯数字条号转中文：19 -> 十九，1079 -> 一千零七十九。

    法条最大到一千二百六十条，但按位权写通用一点，以后加司法解释也用得上。
    """
    digits = "零一二三四五六七八九"
    units = ["", "十", "百", "千"]

    number = int(text)
    if number == 0:
        return "零"

    if number >= 10000:
        high, low = divmod(number, 10000)
        result = _digits_to_cn(str(high)) + "万"
        if low:
            if low < 1000:
                result += "零"      # 一万零二十 这种中间要补零
            result += _digits_to_cn(str(low))
        return result

    raw = str(number)
    length = len(raw)
    result = ""

    for i, ch in enumerate(raw):
        digit = int(ch)
        pos = length - 1 - i          # 位权：1079 的首位是千位

        if digit == 0:
            # 只有「后面还有非零数字」时才补零，避免 100 变成「一百零」
            if result and any(c != "0" for c in raw[i:]):
                if not result.endswith("零"):
                    result += "零"
            continue

        # 「十九」而不是「一十九」：首位是十位且值为 1 时省略「一」
        if not (digit == 1 and pos == 1 and i == 0):
            result += digits[digit]
        result += units[pos]

    return result


# ===========================================================================
# 工具 3：法律清单
# ===========================================================================
@mcp.tool()
def list_laws(domain: str = "") -> str:
    """列出知识库里收录的所有法律，以及每部的条数。

    什么时候用：用户问「你都收录了哪些法律」「有没有公司法」，
    或者你需要确认某部法律在不在收录范围内。

    Args:
        domain: 只看某个领域。可传 key 或中文名，留空看全部。

    Returns:
        Markdown 表格，含法律名、条数、所属领域。
    """
    db = SessionLocal()
    try:
        laws = statute_dao.list_laws(db)
    finally:
        db.close()

    target = _resolve_domain(domain)
    if target:
        laws = [law for law in laws if law["domain"] == target]

    if not laws:
        return "这个领域下没有收录任何法律。"

    lines = [f"共收录 {len(laws)} 部法律：\n"]
    lines.append("| 法律 | 条数 | 领域 |")
    lines.append("|---|---|---|")
    for law in laws:
        label = LAW_DOMAINS.get(law["domain"], {}).get("label", law["domain"])
        lines.append(f"| {law['law_short']} | {law['article_count']} | {label} |")
    lines.append("")
    lines.append("需要看具体条文时，用 get_article 传法律名和条号。")
    return "\n".join(lines)


if __name__ == "__main__":
    logger.info("MCP 服务启动（stdio），主服务地址 %s", BACKEND_URL)
    mcp.run(transport="stdio")
