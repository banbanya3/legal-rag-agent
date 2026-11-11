"""系统设置接口。"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import get_db
from common.result import Result
from schemas.common import ApiResponse
from schemas.settings_schema import (
    LLMSettingIn,
    LLMSettingOut,
    LLMTestRequest,
    LLMTestResult,
    ProviderPreset,
    SaveSettingsResult,
)
from service import settings_service

router = APIRouter(prefix="/api", tags=["系统设置"])


@router.get(
    "/settings",
    summary="读取当前模型与检索设置",
    response_model=ApiResponse[LLMSettingOut],
)
def read_settings(db: Session = Depends(get_db)):
    """密钥永远脱敏返回，浏览器拿不到明文。"""
    return Result.ok(settings_service.get(db))


@router.post(
    "/settings",
    summary="保存设置（立即生效，下一句对话就换模型）",
    response_model=ApiResponse[SaveSettingsResult],
)
def save_settings(payload: LLMSettingIn, db: Session = Depends(get_db)):
    """`api_key` 留空表示沿用已保存的，避免「打开设置直接保存」把 Key 清空。"""
    data = settings_service.save(db, payload.model_dump())
    return Result.ok(data, data["message"])


@router.post(
    "/settings/test",
    summary="测试模型连通性",
    response_model=ApiResponse[LLMTestResult],
)
async def test_settings(payload: LLMTestRequest, db: Session = Depends(get_db)):
    """真实发一次请求，把 HTTP 状态码和原始报错带回来。

    耗时最多 30 秒（模型超时），扔线程池避免卡住事件循环。
    """
    data = await asyncio.to_thread(
        settings_service.test_connection, db, payload.model_dump()
    )
    return Result.ok(data)


@router.get(
    "/models",
    summary="可选模型预设列表",
    response_model=ApiResponse[list[ProviderPreset]],
)
def model_presets():
    return Result.ok(settings_service.presets())
