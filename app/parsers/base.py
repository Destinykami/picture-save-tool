"""解析器抽象与注册表。

新增平台时只需实现一个 Parser 并调用 register()，
API 层无需任何改动，后续接入抖音/知乎即插即用。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..schemas import ParseResult


class Parser(ABC):
    platform: str
    # 用于从分享链接识别平台的特征子串
    url_markers: tuple[str, ...] = ()

    @abstractmethod
    async def parse(self, url: str) -> ParseResult:
        """解析分享链接，返回无水印媒体直链。失败抛 ParseError。"""

    def matches(self, url: str) -> bool:
        return any(marker in url for marker in self.url_markers)


_REGISTRY: list[Parser] = []


def register(parser_cls: type[Parser]) -> type[Parser]:
    """类装饰器：注册解析器类的**实例**，按注册顺序参与匹配。"""
    _REGISTRY.append(parser_cls())
    return parser_cls


def detect(url: str) -> Parser:
    """按注册顺序匹配平台；匹配不到则抛 ParseError。"""
    lowered = url.lower()
    for parser in _REGISTRY:
        if parser.matches(lowered):
            return parser
    from ..schemas import ParseError

    raise ParseError(
        "暂不支持的链接。目前支持：小红书（xiaohongshu.com / xhslink.com）、"
        "知乎（zhuanlan.zhihu.com / zhihu.com）。"
    )
