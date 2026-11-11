"""模型配置数据访问。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from config import settings
from dao.models import SystemSetting


def get_or_create(db: Session) -> SystemSetting:
    """取全局唯一配置行。不存在就按 .env 的默认值创建。

    注意 api_key 的兜底：如果数据库里被清空了，自动回退到环境变量，
    避免"某次保存把 Key 存成空字符串"导致整个系统瘫痪。
    """
    cfg = db.get(SystemSetting, 1)
    if cfg is None:
        cfg = SystemSetting(
            id=1,
            provider="zhipu",
            model_name=settings.LLM_MODEL,
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            temperature=0.1,
            top_k=settings.DEFAULT_TOP_K,
            rerank_n=settings.DEFAULT_RERANK_N,
            use_rerank=True,
            strict_mode=True,
        )
        db.add(cfg)
        db.flush()

    if not cfg.api_key:
        cfg.api_key = settings.LLM_API_KEY
        db.flush()

    return cfg


def update(db: Session, cfg: SystemSetting, payload: dict) -> SystemSetting:
    """只更新前端真正传了的字段，没传的保持原值。"""
    editable = (
        "provider",
        "model_name",
        "base_url",
        "temperature",
        "top_k",
        "rerank_n",
        "use_rerank",
        "strict_mode",
    )
    for field in editable:
        if field in payload and payload[field] is not None:
            setattr(cfg, field, payload[field])

    # 密钥特殊处理：空字符串表示"沿用旧的"，不允许被覆盖成空
    api_key = (payload.get("api_key") or "").strip()
    if api_key:
        cfg.api_key = api_key

    db.flush()
    return cfg
