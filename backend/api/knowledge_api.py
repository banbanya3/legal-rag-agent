"""知识库管理接口。"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from api.deps import get_db
from common.result import BizError, Result
from schemas.common import ApiResponse
from schemas.knowledge_schema import (
    DomainInfo,
    RebuildRequest,
    RebuildResult,
    UploadFileInfo,
    UploadResult,
)
from service import knowledge_service

router = APIRouter(prefix="/api/knowledge", tags=["知识库"])


@router.get(
    "/domains",
    summary="六大法律领域概况",
    response_model=ApiResponse[list[DomainInfo]],
)
def domains(db: Session = Depends(get_db)):
    """知识库页面的卡片数据源：文档数、切片数、法条数。"""
    return Result.ok(knowledge_service.domain_overview(db))


@router.get(
    "/documents",
    summary="用户上传的文档列表",
    response_model=ApiResponse[list[UploadFileInfo]],
)
def list_documents():
    return Result.ok(knowledge_service.list_uploads())


@router.post(
    "/upload",
    summary="上传文档并建立索引",
    response_model=ApiResponse[UploadResult],
)
async def upload(file: UploadFile = File(...)):
    """上传 .txt / .md，落盘后立刻切分进 law_upload 集合。

    上传的文件不会进 MySQL 法条表 —— 它没有规范的法条结构，
    强行解析只会产生脏数据。它只作为"语义检索的补充语料"存在。

    注意这里必须 `async def`：`UploadFile.read()` 是异步方法。
    而落盘和向量化是同步的（要调 embedding 接口，耗时几十秒），
    所以用 `asyncio.to_thread` 包起来，避免阻塞事件循环。
    """
    if not file.filename:
        raise BizError("没有收到文件")

    content = await file.read()

    saved = await asyncio.to_thread(
        knowledge_service.save_upload, file.filename, content
    )
    indexed = await asyncio.to_thread(knowledge_service.index_upload, saved)

    return Result.ok(indexed, f"已上传 {saved}，切分为 {indexed['chunks']} 条可检索片段")


@router.delete("/documents/{filename:path}", summary="删除上传的文档")
def delete_document(filename: str):
    """只删 storage/uploads 下的文件，内置知识库文件不在此列。

    路径参数用 `{filename:path}` 是为了让文件名里的斜杠也能匹配上
    （Flask 版对应的是 `<path:filename>`）。
    """
    data = knowledge_service.delete_upload(filename)
    return Result.ok(data, f"已删除 {data['filename']}")


@router.post(
    "/rebuild",
    summary="重建索引",
    response_model=ApiResponse[RebuildResult],
)
async def rebuild(payload: RebuildRequest):
    """重建向量索引。

    耗时可能几分钟（要调 embedding 接口），扔线程池避免阻塞事件循环。
    `force=true` 会先删集合再重建，用在改了切分参数的时候。
    """
    data = await asyncio.to_thread(
        knowledge_service.build, payload.domain, payload.force
    )
    return Result.ok(data, data["message"])
