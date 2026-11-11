"""系统状态接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import get_db
from common.result import Result
from schemas.common import ApiResponse
from schemas.system_schema import HealthResult, StatsResult
from service import system_service

router = APIRouter(prefix="/api", tags=["系统"])


@router.get(
    "/health",
    summary="健康检查（MySQL / Milvus / 存储）",
    response_model=ApiResponse[HealthResult],
)
def health(db: Session = Depends(get_db)):
    """MySQL 发 SELECT 1，Milvus 数集合行数 —— 都是真探活，不是看配置猜状态。"""
    return Result.ok(system_service.health(db))


@router.get(
    "/stats",
    summary="数据概览（会话量 / 消息量 / 知识库规模）",
    response_model=ApiResponse[StatsResult],
)
def stats(db: Session = Depends(get_db)):
    return Result.ok(system_service.stats(db))
