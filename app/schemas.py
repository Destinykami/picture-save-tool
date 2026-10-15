"""API 数据模型。"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Platform(str, Enum):
    xiaohongshu = "xiaohongshu"
    zhihu = "zhihu"
    douyin = "douyin"


class MediaType(str, Enum):
    image = "image"
    video = "video"
    mixed = "mixed"


class ImageItem(BaseModel):
    url: str = Field(..., description="无水印原图直链")
    width: Optional[int] = None
    height: Optional[int] = None


class VideoItem(BaseModel):
    url: str = Field(..., description="无水印视频直链")
    cover: Optional[str] = Field(None, description="封面图直链")
    duration: Optional[int] = Field(None, description="时长（秒）")


class ParseRequest(BaseModel):
    url: str = Field(..., description="分享链接，如 http://xhslink.com/xxxx")


class ParseResult(BaseModel):
    platform: Platform
    type: MediaType
    title: Optional[str] = None
    author: Optional[str] = None
    description: Optional[str] = None
    images: list[ImageItem] = []
    videos: list[VideoItem] = []


class ParseError(Exception):
    """解析失败，msg 为可直接展示给用户的中文原因。"""

    def __init__(self, msg: str) -> None:
        self.msg = msg
        super().__init__(msg)
