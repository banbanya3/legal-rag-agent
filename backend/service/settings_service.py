"""系统设置业务层：模型切换、参数调整、连通性测试。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from config import settings
from dao import setting_dao
from llm.client import LLMClient

# 前端下拉框的候选列表。放后端的好处是加模型不用发版，
# 而且 base_url 和模型名的对应关系只有一处维护。
MODEL_PRESETS = [
    {
        "provider": "zhipu",
        "label": "智谱 AI",
        "base_url": "https://open.bigmodel.cn/api/paas/v4/",
        "models": [
            {"name": "glm-4-flash", "label": "GLM-4-Flash（推荐 · 快、成本低）", "recommended": True},
            {"name": "glm-4-air", "label": "GLM-4-Air（均衡）"},
            {"name": "glm-4-plus", "label": "GLM-4-Plus（能力强，较慢）"},
            {"name": "glm-5.3-flash", "label": "GLM-5.3-Flash（推理型 · 首字慢 3—5 倍）", "reasoning": True},
        ],
    },
    {
        "provider": "deepseek",
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1/",
        "models": [
            {"name": "deepseek-chat", "label": "DeepSeek-Chat"},
            {"name": "deepseek-reasoner", "label": "DeepSeek-Reasoner（推理型）"},
        ],
    },
    {
        "provider": "qwen",
        "label": "阿里通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/",
        "models": [
            {"name": "qwen-plus", "label": "Qwen-Plus"},
            {"name": "qwen-max", "label": "Qwen-Max"},
        ],
    },
    {
        "provider": "custom",
        "label": "自定义（任意 OpenAI 兼容接口）",
        "base_url": "",
        "models": [],
    },
]


def _mask(key: str) -> str:
    """密钥脱敏。前端只用于展示"已经配过了"，不需要看到明文。"""
    if not key:
        return ""
    if len(key) <= 12:
        return "*" * len(key)
    return f"{key[:6]}{'*' * 10}{key[-4:]}"


def to_payload(cfg) -> dict:
    return {
        "provider": cfg.provider,
        "model_name": cfg.model_name,
        "api_key_masked": _mask(cfg.api_key or ""),
        "has_api_key": bool(cfg.api_key),
        "base_url": cfg.base_url,
        "temperature": cfg.temperature,
        "top_k": cfg.top_k,
        "rerank_n": cfg.rerank_n,
        "use_rerank": bool(cfg.use_rerank),
        "strict_mode": bool(cfg.strict_mode),
        "updated_at": cfg.updated_at.strftime("%Y-%m-%d %H:%M") if cfg.updated_at else "",
    }


def get(db: Session) -> dict:
    cfg = setting_dao.get_or_create(db)
    db.commit()
    return to_payload(cfg)


def save(db: Session, payload: dict) -> dict:
    cfg = setting_dao.get_or_create(db)
    setting_dao.update(db, cfg, payload)
    db.commit()
    db.refresh(cfg)
    return {
        "message": f"已切换到 {cfg.model_name}",
        "settings": to_payload(cfg),
    }


def test_connection(db: Session, payload: dict) -> dict:
    """真实发一次请求验证 key / base_url / 模型名三者是否匹配。

    密钥留空表示"用已保存的那个"，避免用户打开设置面板直接点测试时
    因为前端没回显明文 key 而误判失败。
    """
    api_key = (payload.get("api_key") or "").strip()
    if not api_key:
        cfg = setting_dao.get_or_create(db)
        db.commit()
        api_key = cfg.api_key

    client = LLMClient(
        api_key=api_key or settings.LLM_API_KEY,
        base_url=payload.get("base_url") or settings.LLM_BASE_URL,
        model=payload.get("model_name") or settings.LLM_MODEL,
        temperature=payload.get("temperature", 0.1),
    )
    ok, message, latency, reply = client.test()
    return {
        "success": ok,
        "message": message,
        "latency_ms": latency,
        "model_reply": reply,
    }


# 模型选择提示。推理型模型能用，但法律问答里性价比不高 ——
# 它擅长多步推理，而这个场景的难点在"检索准不准"，不在"想得深不深"。
MODEL_NOTICE = (
    "法律问答建议用 glm-4-flash 或 glm-4-air：首字延迟 1—2 秒，答案更紧凑。"
    "推理型模型（带 reasoning 字段的）会先生成几百到上千字思考过程，"
    "首字延迟 8—15 秒，且思考过程会占用大量 token 预算。"
)


def presets() -> list[dict]:
    return MODEL_PRESETS
