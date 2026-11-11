"""二阶段精排（Reranker）。

为什么 RAG 一定要精排：
向量检索本质是"双塔模型"——问题和文档各自独立编码，再算余弦距离。
它快，但问题和文档之间没有细粒度交互，容易召回"主题相关但答非所问"的片段。

Reranker 是"交叉编码器"，把 (问题, 文档) 拼在一起过一遍模型，
能判断"这段话到底有没有回答问题"。代价是慢，所以只对粗排的前 N 条做。

法律问答对准确性要求极高，这一层几乎是必选项：
用户问"试用期最长多久"，粗排可能召回"劳动合同期限"和"试用期"两类条文，
精排能把真正讲期限的那一条顶上来。
"""
from __future__ import annotations

from typing import Optional

import httpx

from common.logger import get_logger
from config import settings

logger = get_logger("reranker")


class Reranker:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or settings.LLM_API_KEY
        self.model = model or settings.RERANK_MODEL
        self._client = httpx.Client(
            base_url=settings.LLM_BASE_URL.rstrip("/"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            trust_env=False,
            timeout=15,
        )

    def rerank(
        self, query: str, candidates: list[dict], top_n: int = 4
    ) -> list[dict]:
        """对候选切片重排，返回前 top_n 条。

        任何异常都降级为"保持粗排顺序"，绝不让检索链路整个挂掉 ——
        精排是锦上添花，不是单点依赖。
        """
        if not candidates:
            return []
        if len(candidates) <= 1:
            return candidates[:top_n]

        # ⚠️ 必须优先用 display（带「《法名》第X条【主旨】」前缀），而不是 text（纯正文）。
        #
        # 踩过的坑：一开始传的是 text，结果精排的 Recall@4 比纯向量还低 10 个点。
        # 原因是纯正文没有出处信息，rerank 只能按"内容读起来像不像答案"打分，
        # 于是把通俗的「要点」解读段落排到法条原文前面 ——
        # 用户问"醉驾怎么处罚"，正确答案是刑法第一百三十三条，
        # 但三条「要点」读了更像答案，把法条挤出了前 4。
        #
        # 带上出处之后，文档里出现了"第一百三十三条"这样的字面信号，
        # 和 query 里的实体能对上，排序才正常。
        documents = [c.get("display") or c.get("text") or "" for c in candidates]

        try:
            resp = self._client.post(
                "/rerank",
                json={
                    "model": self.model,
                    "query": query,
                    "documents": documents,
                    "top_n": min(top_n, len(documents)),
                },
            )
            if resp.status_code != 200:
                logger.warning(
                    "精排接口返回 HTTP %s，降级为向量粗排", resp.status_code
                )
                return candidates[:top_n]

            results = resp.json().get("results", [])
            if not results:
                return candidates[:top_n]

            reranked: list[dict] = []
            for item in results:
                idx = item.get("index")
                if idx is None or idx >= len(candidates):
                    continue
                hit = dict(candidates[idx])
                # 用精排分覆盖向量分，前端展示的相关度才是"真相关度"
                hit["vector_score"] = hit.get("score", 0.0)
                hit["score"] = float(item.get("relevance_score", 0.0))
                hit["reranked"] = True
                reranked.append(hit)

            return reranked[:top_n]

        except Exception as exc:  # noqa: BLE001
            logger.warning("精排调用异常，降级为向量粗排：%s", exc)
            return candidates[:top_n]


_reranker: Optional[Reranker] = None


def get_reranker(api_key: str | None = None) -> Reranker:
    global _reranker
    if _reranker is None or (api_key and api_key != _reranker.api_key):
        _reranker = Reranker(api_key=api_key)
    return _reranker
