"""大模型客户端（智谱 GLM，OpenAI 兼容协议）。

这里没有走 openai SDK 的封装，而是直接 httpx 调 /chat/completions，原因有三：

1. 需要精确控制超时、重试和代理行为（trust_env=False 绕开 Windows 全局代理）；
2. 推理型模型（如 glm-5.x）会在 reasoning_content 里输出思维链，content 可能是空的，
   SDK 的强类型封装反而挡手；
3. 流式 SSE 需要拿到原始 chunk，自己解析 delta，避免中间层做缓冲。
"""
from __future__ import annotations

import json
import time
from typing import AsyncGenerator, Generator

import httpx

from common.logger import get_logger
from config import settings

logger = get_logger("llm")


class LLMError(RuntimeError):
    """大模型调用失败。带上原始状态码，方便前端直接把问题说清楚。"""


# 推理型模型的识别特征。这类模型会先把思考过程写进 reasoning_content，
# 再输出正式答案，两者是**两个独立字段**，绝不能混用。
REASONING_MODEL_HINTS = ("reasoner", "-r1", "thinking", "glm-5", "glm-z1", "o1-", "o3-")


def is_reasoning_model(model: str) -> bool:
    name = (model or "").lower()
    return any(hint in name for hint in REASONING_MODEL_HINTS)


# content 为空时的兜底文案。刻意写成"教用户怎么修"而不是"抱歉出错了" ——
# 这个错误有明确的成因和解法，藏着反而让人以为是随机故障。
REASONING_EMPTY_TEMPLATE = (
    "⚠️ 模型只输出了思考过程，没有给出正式回答。\n\n"
    "**原因**：`{model}` 是推理型模型，它把 {reasoning_len} 字的思考过程写在了 "
    "`reasoning_content` 里，token 预算被思考占满，正式答案（`content`）是空的。\n\n"
    "**这不是知识库或检索的问题**，换成非推理模型就能正常回答。\n\n"
    "**建议**：打开右上角「系统设置」，把模型换成 `glm-4-flash` 或 `glm-4-air`。"
    "法律问答要的是准确引用法条，不需要长链推理，换掉之后首字延迟还能快 3—5 倍。"
)


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        temperature: float = 0.1,
    ) -> None:
        self.api_key = api_key or settings.LLM_API_KEY
        self.base_url = (base_url or settings.LLM_BASE_URL).rstrip("/")
        self.model = model or settings.LLM_MODEL
        self.temperature = temperature

    @property
    def is_reasoning(self) -> bool:
        return is_reasoning_model(self.model)

    # ------------------------------------------------------------------ 内部
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _pick_content(message: dict) -> str:
        """只取正式答案，**绝不回退到 reasoning_content**。

        这里曾经写过"content 为空就取 reasoning_content"的兜底，结果很惨：
        推理模型的思维链被当成答案存进数据库，下一轮作为历史消息喂回去，
        模型看到"自己"写的英文草稿，继续用英文自言自语，还会自我纠正，
        整个会话越聊越乱。

        思维链是草稿，不是答案。拿不到正文就老实说拿不到，不能拿草稿充数。
        """
        return (message.get("content") or "").strip()

    def _build_payload(
        self,
        messages: list[dict],
        temperature: float | None,
        max_tokens: int,
        stream: bool,
    ) -> dict:
        """构造请求体。同步版和异步版共用，避免两边字段慢慢长歪。"""
        return {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

    @staticmethod
    def _parse_sse_line(line: str) -> dict | None:
        """把 SSE 的一行解析成 chunk 字典，解析不出来返回 None。

        同步的 iter_lines() 和异步的 aiter_lines() 都吐这种行，
        解析逻辑一样，抽出来共用。
        """
        line = line.strip()
        if not line:
            return None
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line or line == "[DONE]":
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None

    # ------------------------------------------------------------------ 非流式
    def chat(
        self,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int = 2048,
        json_mode: bool = False,
        timeout: float = 90,
    ) -> str:
        payload = self._build_payload(messages, temperature, max_tokens, stream=False)
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            with httpx.Client(trust_env=False, timeout=timeout) as client:
                resp = client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise LLMError(f"大模型响应超时（{timeout}s），请稍后重试") from exc
        except httpx.TransportError as exc:
            raise LLMError(f"无法连接大模型服务：{exc}") from exc

        if resp.status_code != 200:
            raise LLMError(f"大模型返回 HTTP {resp.status_code}：{resp.text[:300]}")

        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("大模型返回了空结果")
        return self._pick_content(choices[0].get("message") or {}).strip()

    # ------------------------------------------------------------------ 流式
    def stream_chat(
        self,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float = 240,
    ) -> Generator[str, None, None]:
        """逐 token 产出**正文**片段。

        实现要点：
        - 用 client.stream() 而不是 client.post()，否则会把整个响应读进内存再返回；
        - 手动按 \\n 切 SSE 帧，兼容 Windows 的 \\r\\n；
        - 推理模型的 reasoning_content 只统计不输出：它是思考草稿，
          含大量英文自语和"我应该……""控制在500字"这类元叙述，
          混进答案里会让整段回答变得又长又乱；
        - content 为空时给一段可操作的提示，而不是拿草稿充数。

        token 预算：推理模型的思考部分实测能吃掉 1000—3000 字符（约 700—2000 token），
        再叠加 400—600 字的正文，1600 会被截断。所以这里按模型类型自动放宽。
        """
        if max_tokens is None:
            max_tokens = 4096 if self.is_reasoning else 1600

        payload = self._build_payload(messages, temperature, max_tokens, stream=True)

        reasoning_chars = 0
        content_emitted = False

        try:
            with httpx.Client(trust_env=False, timeout=timeout) as client:
                with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                ) as resp:
                    if resp.status_code != 200:
                        body = resp.read().decode("utf-8", errors="ignore")
                        raise LLMError(
                            f"大模型返回 HTTP {resp.status_code}：{body[:300]}"
                        )

                    for line in resp.iter_lines():
                        if not line:
                            continue
                        line = line.strip()
                        if line.startswith("data:"):
                            line = line[5:].strip()
                        if not line or line == "[DONE]":
                            continue

                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}

                        # 思考过程只计数，不往外吐
                        reasoning = delta.get("reasoning_content")
                        if reasoning:
                            reasoning_chars += len(reasoning)

                        piece = delta.get("content")
                        if piece:
                            content_emitted = True
                            yield piece

                        if choices[0].get("finish_reason"):
                            break

        except httpx.TimeoutException as exc:
            raise LLMError(f"大模型响应超时（{timeout}s）") from exc
        except httpx.TransportError as exc:
            raise LLMError(f"无法连接大模型服务：{exc}") from exc

        if not content_emitted:
            if reasoning_chars:
                # 有思考没正文 —— 推理模型 token 被思考吃光的典型表现
                logger.warning(
                    "推理模型只产出思维链（%d 字），content 为空：model=%s",
                    reasoning_chars, self.model,
                )
                yield REASONING_EMPTY_TEMPLATE.format(
                    model=self.model, reasoning_len=reasoning_chars
                )
            else:
                raise LLMError("模型没有返回任何内容，请检查模型名称与 API Key")

    # ------------------------------------------------------------------ 连通性
    def test(self) -> tuple[bool, str, int | None, str]:
        """设置面板的【测试连接】。返回 (成功, 提示, 耗时ms, 模型回复)。

        两个坑：

        1. **推理模型的 token 预算**。原来写死 max_tokens=64，
           glm-5.3-flash 这类模型光思考就要几百 token，64 全被吃光，
           content 是空的，界面上就报"连接失败" —— 但接口其实是通的。

        2. **content 为空不等于连接失败**。只要 HTTP 返回 200，
           说明 Base URL、API Key、模型名三项都对，连接就是成功的，
           只是这个模型没给正文。原来返回 False 会误导用户去查配置。
        """
        # 侦查型模型给足预算，普通模型 64 够用（"收到"两个字）
        max_tokens = 2048 if self.is_reasoning else 64

        start = time.perf_counter()
        try:
            reply = self.chat(
                [{"role": "user", "content": "请只回复两个字：收到"}],
                max_tokens=max_tokens,
                timeout=90,
            )
            cost = int((time.perf_counter() - start) * 1000)

            if not reply:
                # 拿到 200 但没有正文 —— 连接是通的，只是模型只吐了思考过程
                return (
                    True,
                    "连接成功（该模型只输出思考过程，正文为空；"
                    "法律问答建议换 glm-4-flash）",
                    cost,
                    "",
                )
            return True, "连接成功，模型已正常响应", cost, reply[:60]
        except LLMError as exc:
            return False, str(exc), None, ""
        except Exception as exc:  # noqa: BLE001
            return False, f"连接失败：{type(exc).__name__} - {exc}", None, ""


    # ==================================================================
    # 异步版本（FastAPI 用）
    #
    # 为什么同步和异步两套都保留：
    #   - Web 请求走异步，SSE 长连接挂在事件循环上，不占线程
    #   - init_knowledge.py 建索引走同步，它是脚本、没有事件循环，
    #     而且要串行跑几十批 embedding，异步在这里没有收益只有复杂度
    #
    # 共用 _build_payload / _parse_sse_line / _pick_content / REASONING_EMPTY_TEMPLATE，
    # 但 HTTP 客户端没法共用（httpx.Client 和 AsyncClient 是两种对象）。
    # ==================================================================
    async def achat(
        self,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int = 2048,
        json_mode: bool = False,
        timeout: float = 90,
    ) -> str:
        """异步非流式。给路由器的意图分类用（那个调用只需要一句 JSON）。"""
        payload = self._build_payload(messages, temperature, max_tokens, stream=False)
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            async with httpx.AsyncClient(trust_env=False, timeout=timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise LLMError(f"大模型响应超时（{timeout}s），请稍后重试") from exc
        except httpx.TransportError as exc:
            raise LLMError(f"无法连接大模型服务：{exc}") from exc

        if resp.status_code != 200:
            raise LLMError(f"大模型返回 HTTP {resp.status_code}：{resp.text[:300]}")

        choices = resp.json().get("choices") or []
        if not choices:
            raise LLMError("大模型返回了空结果")
        return self._pick_content(choices[0].get("message") or {}).strip()

    async def astream_chat(
        self,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float = 240,
    ) -> AsyncGenerator[str, None]:
        """异步流式。行为和同步版 stream_chat 完全一致：

        - reasoning_content 只计数不输出（它是草稿，会污染答案）
        - 按模型类型给 token 预算（推理模型 4096，普通 1600）
        - 有思考没正文时给可操作提示，而不是拿草稿充数
        """
        if max_tokens is None:
            max_tokens = 4096 if self.is_reasoning else 1600

        payload = self._build_payload(messages, temperature, max_tokens, stream=True)
        reasoning_chars = 0
        content_emitted = False

        try:
            async with httpx.AsyncClient(trust_env=False, timeout=timeout) as client:
                # 注意：client.stream 返回的是异步上下文管理器，
                # 所以是 `async with client.stream(...)`，不是 `await client.stream(...)`
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                ) as resp:
                    if resp.status_code != 200:
                        body = (await resp.aread()).decode("utf-8", errors="ignore")
                        raise LLMError(
                            f"大模型返回 HTTP {resp.status_code}：{body[:300]}"
                        )

                    async for line in resp.aiter_lines():
                        chunk = self._parse_sse_line(line)
                        if chunk is None:
                            continue

                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}

                        # 思考过程只计数，不往外吐
                        reasoning = delta.get("reasoning_content")
                        if reasoning:
                            reasoning_chars += len(reasoning)

                        piece = delta.get("content")
                        if piece:
                            content_emitted = True
                            yield piece

                        if choices[0].get("finish_reason"):
                            break

        except httpx.TimeoutException as exc:
            raise LLMError(f"大模型响应超时（{timeout}s）") from exc
        except httpx.TransportError as exc:
            raise LLMError(f"无法连接大模型服务：{exc}") from exc

        if not content_emitted:
            if reasoning_chars:
                logger.warning(
                    "推理模型只产出思维链（%d 字），content 为空：model=%s",
                    reasoning_chars, self.model,
                )
                yield REASONING_EMPTY_TEMPLATE.format(
                    model=self.model, reasoning_len=reasoning_chars
                )
            else:
                raise LLMError("模型没有返回任何内容，请检查模型名称与 API Key")


def build_client(cfg) -> LLMClient:
    """从数据库配置行构造客户端。

    cfg 是 dao.models.SystemSetting 实例。每次对话都新建一个轻量对象，
    真正的开销在 HTTP 连接（httpx 每次新建，但单次对话只发 2-3 个请求，
    这点开销比维护连接池状态出错要划算）。
    """
    return LLMClient(
        api_key=cfg.api_key or settings.LLM_API_KEY,
        base_url=cfg.base_url or settings.LLM_BASE_URL,
        model=cfg.model_name or settings.LLM_MODEL,
        temperature=cfg.temperature if cfg.temperature is not None else 0.1,
    )
