"""文本向量化客户端（智谱 embedding-2，OpenAI 兼容协议）。

为什么不用 llama-index 的 OpenAIEmbedding 包装：
1. 我们需要精确控制批量大小和重试策略（32 个文件、几千条切片，中途断一次很麻烦）；
2. 需要拿到真实的 HTTP 报错，而不是被 SDK 包一层"connection error"；
3. 后面要接别的厂商时，只改这一个文件。
"""
from __future__ import annotations

import time
from typing import Iterable

import httpx

from common.logger import get_logger
from config import settings

logger = get_logger("embedder")

# 单次请求最多带多少条文本。智谱上限 64，取 32 留余量，
# 既不容易触发限流，也不会让单次请求体过大。
BATCH_SIZE = 32
MAX_RETRY = 3


class Embedder:
    """线程安全的向量化客户端。httpx.Client 内部有连接池，可复用。"""

    def __init__(self) -> None:
        self._client = httpx.Client(
            base_url=settings.LLM_BASE_URL.rstrip("/"),
            headers={
                "Authorization": f"Bearer {settings.LLM_API_KEY}",
                "Content-Type": "application/json",
            },
            # trust_env=False：绕过系统代理。Windows 上经常开着全局代理，
            # openai/httpx 走代理访问国内接口反而会超时。
            trust_env=False,
            timeout=60,
        )
        self._cache: dict[str, list[float]] = {}

    # ------------------------------------------------------------------ 内部
    def _post(self, texts: list[str]) -> list[list[float]]:
        payload = {"model": settings.EMBED_MODEL, "input": texts}

        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRY + 1):
            try:
                resp = self._client.post("/embeddings", json=payload)
                if resp.status_code == 200:
                    data = resp.json().get("data", [])
                    # 接口不保证按输入顺序返回，index 字段才是权威顺序
                    data.sort(key=lambda item: item.get("index", 0))
                    vectors = [item["embedding"] for item in data]
                    if len(vectors) != len(texts):
                        raise ValueError(
                            f"向量条数不匹配：请求 {len(texts)} 条，返回 {len(vectors)} 条"
                        )
                    return vectors

                # 429 限流、5xx 服务端错误值得重试；4xx 参数错误重试也没用
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_error = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                else:
                    raise RuntimeError(
                        f"Embedding 接口返回 HTTP {resp.status_code}：{resp.text[:300]}"
                    )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc

            wait = 2 ** attempt
            logger.warning(
                "向量化失败（第 %d/%d 次），%ds 后重试：%s",
                attempt, MAX_RETRY, wait, last_error,
            )
            time.sleep(wait)

        raise RuntimeError(f"Embedding 调用失败，已重试 {MAX_RETRY} 次：{last_error}")

    # ------------------------------------------------------------------ 对外
    def embed_documents(self, texts: Iterable[str]) -> list[list[float]]:
        """批量向量化。自动分批 + 维度校验。"""
        items = [t if t.strip() else "空" for t in texts]
        vectors: list[list[float]] = []

        for start in range(0, len(items), BATCH_SIZE):
            batch = items[start: start + BATCH_SIZE]
            batch_vectors = self._post(batch)
            for vec in batch_vectors:
                if len(vec) != settings.EMBED_DIM:
                    raise ValueError(
                        f"向量维度 {len(vec)} 与配置 EMBED_DIM={settings.EMBED_DIM} 不一致。"
                        "换 embedding 模型后必须同步修改 .env，并重建全部索引。"
                    )
            vectors.extend(batch_vectors)
            logger.info(
                "向量化进度 %d/%d", min(start + BATCH_SIZE, len(items)), len(items)
            )

        return vectors

    def embed_query(self, text: str) -> list[float]:
        """查询向量。带一层小缓存：用户连点两次同样的问题不必花两次钱。"""
        key = text.strip()
        if key in self._cache:
            return self._cache[key]
        vec = self._post([key])[0]
        if len(self._cache) > 256:
            self._cache.clear()
        self._cache[key] = vec
        return vec


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    """全局单例。懒加载，避免 import 阶段就去连网。"""
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder
