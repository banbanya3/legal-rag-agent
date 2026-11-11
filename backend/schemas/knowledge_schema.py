"""知识库管理模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class FileInfo(BaseModel):
    """知识库里的一个源文件。"""

    filename: str
    size_kb: float = Field(default=0, ge=0)


class DomainInfo(BaseModel):
    """一个法律领域的概况，知识库页面的卡片数据。"""

    domain: str
    label: str
    desc: str = ""
    color: str = Field(default="", description="主题色，前端渲染卡片图标底色")
    dir: str = Field(default="", description="knowledge_base 下的子目录名")
    collections: str = Field(default="", description="Milvus 集合名")
    vectors: int = Field(default=0, ge=0, description="向量切片数")
    docs: int = Field(default=0, ge=0, description="文档数")
    chunks: int = Field(default=0, ge=0, description="台账记录的切片数")
    articles: int = Field(default=0, ge=0, description="台账记录的法条数")
    statutes: int = Field(default=0, ge=0, description="法条表实际条数")
    chars: int = Field(default=0, ge=0, description="语料字符数")
    files: list[FileInfo] = Field(default_factory=list)


class UploadFileInfo(BaseModel):
    """用户上传的文档。"""

    filename: str
    size_kb: float = Field(default=0, ge=0)
    modified_at: str = Field(default="", description="格式 YYYY-MM-DD HH:MM")


class UploadResult(BaseModel):
    """上传后的处理结果。"""

    filename: str
    chunks: int = Field(default=0, ge=0, description="切分出的可检索片段数")
    chars: int = Field(default=0, ge=0)


class RebuildRequest(BaseModel):
    """POST /api/knowledge/rebuild 的请求体。"""

    domain: str | None = Field(
        default=None, description="只重建某个领域；留空表示全量"
    )
    force: bool = Field(
        default=False,
        description="true 会先删集合再重建（改了切分参数时用）；false 走增量",
    )


class RebuildDomainResult(BaseModel):
    """单个领域的重建结果。"""

    domain: str
    label: str
    files: int = Field(default=0, ge=0)
    chunks: int = Field(default=0, ge=0)
    articles: int = Field(default=0, ge=0)
    failed: list[dict] = Field(default_factory=list, description="失败的文件与原因")


class RebuildResult(BaseModel):
    """POST /api/knowledge/rebuild 的返回。"""

    domains: list[RebuildDomainResult] = Field(default_factory=list)
    total_chunks: int = Field(default=0, ge=0)
    total_articles: int = Field(default=0, ge=0)
    message: str = ""
