"""解析器包：导入即完成各平台解析器注册。"""
from . import xiaohongshu, zhihu  # noqa: F401  (导入触发 register)
from .base import Parser, detect, register  # noqa: F401

__all__ = ["Parser", "detect", "register"]
