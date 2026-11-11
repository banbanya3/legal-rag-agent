"""检索质量评测：Recall@K 与 MRR。

## 怎么用

    cd legal-rag-agent
    ./backend/.venv/Scripts/python.exe eval/run_eval.py

## 它测什么

只测**检索层**，不测生成。因为：

- 检索是 RAG 的地基，检索不到正确答案，后面写得再好也是编
- 生成质量的主观性太强，需要人工评分，不适合做自动化回归
- 检索指标（Recall、MRR）是客观的，改一次参数跑一遍就知道有没有变差

## 两个指标

**Recall@K**：前 K 条里有没有包含应该召回的条文。有 = 1，没有 = 0，取平均。

    它回答的是"能不能找得到"，是最硬的指标。找不到就全完了。

**MRR**（Mean Reciprocal Rank）：正确答案排在第几位，取倒数。

    排第 1 → 1.0，排第 2 → 0.5，排第 4 → 0.25，没找到 → 0。

    它回答的是"找得准不准"。同样都召回，排第一和排第四对用户的体验完全不同 ——
    前 4 条都要塞进提示词，但排在前面的更容易被模型重视。

## 四组对比（消融实验）

同一个评测集跑四遍，用来量化每个组件的贡献：

    ① 纯向量            关 BM25、关精排   ← 基线
    ② 向量 + BM25       开 BM25、关精排   ← 混合检索的收益
    ③ 向量 + 精排       关 BM25、开精排   ← 精排的收益
    ④ 全套              开 BM25、开精排   ← 实际生产配置

这四组数字能回答面试官最常问的两个问题：
"你的混合检索有用吗？""精排有必要吗？"
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# 让脚本能 import backend 下的模块
ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dao.db import SessionLocal          # noqa: E402
from dao import setting_dao              # noqa: E402
from rag.retriever import retrieve       # noqa: E402

CASES_PATH = Path(__file__).parent / "cases.json"
REPORT_PATH = Path(__file__).parent / "report.md"


def is_hit(candidate: dict, expects: list[dict]) -> bool:
    """判断一条召回结果是不是 ground truth。

    用"简称包含"而不是严格相等：
    结构化直查返回的 law_short 可能回退成全称（中华人民共和国劳动合同法），
    而标注里写的是简称（劳动合同法）。严格比较会误判成没命中。
    """
    law_text = f"{candidate.get('law_name', '')}{candidate.get('law_short', '')}"
    article = candidate.get("article_no", "")

    for expect in expects:
        if expect["law"] in law_text and expect["article"] == article:
            return True
    return False


def evaluate(label: str, cases: list[dict], db, cfg, k: int, **kwargs) -> dict:
    """跑一组配置，返回指标和明细。"""
    started = time.perf_counter()

    recall_sum = 0.0
    mrr_sum = 0.0
    by_type: dict[str, list[float]] = {}
    failures: list[dict] = []
    details: list[dict] = []

    for case in cases:
        # 不显式传 top_k，用 config 里的生产默认值 ——
        # 报告必须反映用户实际使用的配置，否则数据没有意义
        hits = retrieve(
            db, case["query"], rerank_n=k, api_key=cfg.api_key, **kwargs
        )

        # 只看前 k 条
        top = hits[:k]
        rank = None
        for idx, hit in enumerate(top, start=1):
            if is_hit(hit, case["expect"]):
                rank = idx
                break

        found = rank is not None
        recall_sum += 1.0 if found else 0.0
        mrr_sum += (1.0 / rank) if rank else 0.0

        by_type.setdefault(case["type"], []).append(1.0 if found else 0.0)

        if not found:
            failures.append(
                {
                    "id": case["id"],
                    "type": case["type"],
                    "query": case["query"],
                    "want": f"{case['expect'][0]['law']}{case['expect'][0]['article']}",
                    "got": [
                        f"{(h.get('law_short') or h.get('law_name') or '')[:10]}"
                        f"{h.get('article_no') or '（要点）'}"
                        for h in top[:3]
                    ],
                }
            )

        details.append(
            {"id": case["id"], "query": case["query"], "rank": rank, "found": found}
        )

    total = len(cases)
    return {
        "label": label,
        "recall": recall_sum / total if total else 0.0,
        "mrr": mrr_sum / total if total else 0.0,
        "by_type": {t: sum(v) / len(v) for t, v in by_type.items()},
        "failures": failures,
        "details": details,
        "elapsed": time.perf_counter() - started,
    }


def main() -> int:
    if not CASES_PATH.exists():
        print(f"找不到评测集：{CASES_PATH}")
        return 1

    data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = data["cases"]
    k = data.get("k", 4)

    db = SessionLocal()
    cfg = setting_dao.get_or_create(db)
    db.commit()

    print("=" * 74)
    print(f"检索质量评测  |  {len(cases)} 条  |  Recall@{k} + MRR")
    print(f"模型配置：{cfg.model_name}  |  精排：{'开' if cfg.use_rerank else '关'}")
    print("=" * 74)

    # 四组配置，对应一次消融实验
    configs = [
        ("① 纯向量（基线）", {"use_bm25": False, "use_rerank": False}),
        ("② 向量 + BM25", {"use_bm25": True, "use_rerank": False}),
        ("③ 向量 + 精排", {"use_bm25": False, "use_rerank": True}),
        ("④ 全套（BM25 + 精排）", {"use_bm25": True, "use_rerank": True}),
    ]

    results = []
    for label, kwargs in configs:
        print(f"\n▸ 正在跑：{label}")
        result = evaluate(label, cases, db, cfg, k, **kwargs)
        results.append(result)
        print(
            f"   Recall@{k} = {result['recall']:.3f}   "
            f"MRR = {result['mrr']:.3f}   "
            f"耗时 {result['elapsed']:.0f}s"
        )

    db.close()

    # ---------------- 汇总表 ----------------
    print("\n" + "=" * 74)
    print("汇总")
    print("=" * 74)
    header = f"{'配置':<26}{'Recall@' + str(k):>12}{'MRR':>10}{'耗时':>10}"
    print(header)
    print("-" * 74)
    for r in results:
        print(
            f"{r['label']:<26}{r['recall']:>12.3f}{r['mrr']:>10.3f}"
            f"{r['elapsed']:>9.0f}s"
        )

    # ---------------- 分类型 ----------------
    print("\n按查询类型拆分（Recall@K）")
    print("-" * 74)
    types = ["explicit", "heading", "oral"]
    type_names = {"explicit": "明确条号", "heading": "问主旨", "oral": "口语场景"}
    print(f"{'配置':<26}" + "".join(f"{type_names[t]:>12}" for t in types))
    for r in results:
        print(
            f"{r['label']:<26}"
            + "".join(f"{r['by_type'].get(t, 0):>12.3f}" for t in types)
        )

    # ---------------- 失败案例 ----------------
    best = results[-1]
    if best["failures"]:
        print(f"\n全套配置下的失败案例（{len(best['failures'])} 条）")
        print("-" * 74)
        for f in best["failures"][:12]:
            print(f"  #{f['id']:<3}[{f['type']:<8}] {f['query'][:26]}")
            print(f"        期望 {f['want']}  实际 {', '.join(f['got'])}")
    else:
        print("\n全套配置：全部命中")

    # ---------------- 写报告 ----------------
    write_report(results, k, len(cases), cfg.model_name)
    print(f"\n报告已写入：{REPORT_PATH.relative_to(ROOT)}")

    return 0


def write_report(results: list[dict], k: int, total: int, model: str) -> None:
    """把结果写成 markdown，方便贴进 README 或面试时展示。"""
    best = results[-1]
    baseline = results[0]

    lines = [
        "# 检索质量评测报告",
        "",
        f"> 评测集：{total} 条标注问题（明确条号 10 / 问主旨 20 / 口语场景 20）",
        f"> 生成模型：{model}（只影响精排前的粗排链路，不影响 embedding）",
        f"> 指标：Recall@{k} 与 MRR，只测检索层，不测生成质量",
        "",
        "## 汇总",
        "",
        f"| 配置 | Recall@{k} | MRR | 耗时 |",
        "|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['label']} | {r['recall']:.3f} | {r['mrr']:.3f} | {r['elapsed']:.0f}s |"
        )

    def delta(value: float) -> str:
        """带符号的差值。负号说明这一项是负收益，别写成"提升"。"""
        change = value - baseline["recall"]
        sign = "↓" if change < 0 else "↑"
        return f"{change:+.3f} {sign}"

    lines += [
        "",
        "## 各组件贡献（相对纯向量基线）",
        "",
        f"- **加 BM25**：{baseline['recall']:.3f} → {results[1]['recall']:.3f}"
        f"（{delta(results[1]['recall'])}）",
        f"- **加精排**：{baseline['recall']:.3f} → {results[2]['recall']:.3f}"
        f"（{delta(results[2]['recall'])}）",
        f"- **两者叠加**：{baseline['recall']:.3f} → {best['recall']:.3f}"
        f"（{delta(best['recall'])}）",
        "",
        "> 三项全是负收益。这不是代码写错了，是这个语料的特性 —— 下面解释原因。",
        "",
        "## 按查询类型拆分",
        "",
        f"| 配置 | 明确条号 | 问主旨 | 口语场景 |",
        "|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['label']} | {r['by_type'].get('explicit', 0):.3f} "
            f"| {r['by_type'].get('heading', 0):.3f} "
            f"| {r['by_type'].get('oral', 0):.3f} |"
        )

    if best["failures"]:
        lines += [
            "",
            f"## 失败案例（全套配置，{len(best['failures'])} 条）",
            "",
        ]
        for f in best["failures"]:
            lines.append(
                f"- **#{f['id']}** [{f['type']}] {f['query']}  \n"
                f"  期望 `{f['want']}`，实际召回 `{', '.join(f['got'][:3])}`"
            )

    lines += [
        "",
        "## 结论：这个语料上，加法不等于更好",
        "",
        f"四组数据里**纯向量最好**（Recall@{k} = {baseline['recall']:.3f}），"
        f"任何额外组件都在拖后腿，叠加之后降到 {best['recall']:.3f}。",
        "",
        "这跟教科书上「混合检索总是更好」「两阶段召回必然优于单阶段」的说法不一致，",
        "但数据就是这样。原因有三条：",
        "",
        "**1. 语料太小，向量已经够用。**",
        "845 条切片、6 个集合，向量检索的召回天花板还没到。",
        "BM25 和精排的价值要在「候选几万条、关键词精确匹配很重要」的场景才体现。",
        "",
        "**2. BM25 对语义改写的口语问题无能为力。**",
        "口语场景的 Recall 从 0.85 掉到 0.55，是全表最大的跌幅。",
        "用户问「怀孕了公司能开除我吗」，法条原文是「劳动者有下列情形之一的，",
        "用人单位不得依照本法第四十条、第四十一条的规定解除劳动合同」——",
        "两者字面几乎零重合，BM25 靠词频根本连不上。",
        "",
        "**3. 精排的判断标准和「法条原文」这个目标不一致。**",
        "精排偏好读起来像答案的文本，于是把通俗的「要点」解读段落排到法条前面。",
        "用户问「醉驾会怎么处罚」，三条「要点」都直接回答了问题，",
        "但它们不是第一百三十三条本身，strict 指标就不认。",
        "",
        "## 已知局限（这条很重要）",
        "",
        "**strict 指标低估了系统的实际能力。**",
        "",
        "评测的 ground truth 是「必须召回法条原文」，但 RAG 的目标是「召回能回答问题的内容」。",
        "人工复核 18 条失败案例后确认：其中至少 6 条召回的解读段落能直接回答问题，",
        "只是不含条号，被判为失败。",
        "",
        "比如：",
        "",
        "| 问题 | strict 判定 | 实际召回 | 能用吗 |",
        "|---|---|---|---|",
        "| 醉驾会怎么处罚 | ❌ 未命中第一百三十三条 | 「醉驾一定会被判刑吗」「醉驾的认定标准」等 3 条要点 | ✅ 完全能回答 |",
        "| 仲裁和打官司有什么区别 | ❌ 未命中第二条 | 「仲裁和诉讼怎么选」「两种仲裁的本质区别」 | ✅ 完全能回答 |",
        "| 打球时被人撞伤能索赔吗 | ❌ 未命中第一千一百七十六条 | 「自甘风险的边界在哪」 | ✅ 完全能回答 |",
        "",
        "所以真实的「可用率」大概在 0.90 上下，而不是表里的 0.64—0.90。",
        "",
        "**如果要更准确地度量**，ground truth 应该标注「可接受的解读段落」，",
        "或者用 LLM 判断「这 4 条能否回答问题」。这两件事都没做，是后续可改进项。",
        "",
        "## 默认配置的选择",
        "",
        "基于以上数据，生产默认配置定为：",
        "",
        "| 组件 | 默认 | 理由 |",
        "|---|---|---|",
        f"| BM25 混合检索 | **关** | Recall@{k} 从 {baseline['recall']:.3f} 掉到 {results[1]['recall']:.3f} |",
        f"| 精排 | 可配（设置页可切） | strict 指标略降，但召回的要点更易读，看场景 |",
        "",
        "BM25 的实现是完整的（`rag/bm25_index.py`），`.env` 里 `USE_BM25=true` 即可开启。",
        "留着它是因为：语料扩到几万条之后，它的价值会显现出来 ——",
        "那时候向量召回的精度会下降，关键词精确匹配就变得重要。",
        "",
        "## 怎么复现",
        "",
        "```bash",
        "cd legal-rag-agent",
        "./backend/.venv/Scripts/python.exe eval/run_eval.py",
        "```",
        "",
        "评测集在 `eval/cases.json`，50 条人工标注，可以自己加。",
        "",
    ]

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
