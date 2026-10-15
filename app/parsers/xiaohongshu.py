"""小红书解析器。

原理：小红书网页版（www.xiaohongshu.com）的笔记页会把完整笔记数据
序列化进 ``window.__INITIAL_STATE__`` 变量，其中包含原图 CDN 直链
（无水印）与视频 masterUrl（无水印流）。本解析器直接请求笔记页并
提取该 JSON，无需模拟 App 签名。
"""
from __future__ import annotations

import json
import re

import httpx

from .. import config
from ..schemas import (
    ImageItem,
    MediaType,
    ParseError,
    ParseResult,
    Platform,
    VideoItem,
)
from .base import Parser, register

# 分享短链域名与笔记页路径特征
_NOTE_ID_RE = re.compile(
    r"/(?:explore|discovery/item|item)/([0-9a-zA-Z]+)", re.IGNORECASE
)
_STATE_RE = re.compile(
    r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>", re.DOTALL
)


def _build_headers() -> dict[str, str]:
    headers = {
        "User-Agent": config.USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if config.XHS_COOKIE:
        headers["Cookie"] = config.XHS_COOKIE
    return headers


def _extract_state(html: str) -> dict:
    """从页面 HTML 中提取 __INITIAL_STATE__ JSON。"""
    m = _STATE_RE.search(html)
    if not m:
        raise ParseError(
            "页面中未找到笔记数据，可能触发了登录/验证码拦截。"
            "请在服务端配置 XHS_COOKIE（小红书网页版登录后的 Cookie）后重试。"
        )
    raw = m.group(1).replace("undefined", "null")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ParseError(f"笔记数据解析失败：{exc}") from exc


def _get_note(state: dict) -> dict:
    detail_map = state.get("note", {}).get("noteDetailMap") or {}
    if not detail_map:
        raise ParseError("未获取到笔记详情，链接可能已失效或需要登录。")
    entry = next(iter(detail_map.values()))
    note = (entry or {}).get("note")
    if not note:
        reason = (entry or {}).get("error", {}).get("errorDesc") if isinstance(entry, dict) else None
        raise ParseError(
            f"笔记详情为空{'（' + reason + '）' if reason else ''}，链接可能失效、已删除或需要登录。"
        )
    return note


def _clean_image_url(url: str) -> str:
    """规范化图片直链：强制 https；剔除已知的水印变体标记。"""
    url = url.replace("http://", "https://", 1)
    # 部分 CDN 路径用 -wm / _wm 后缀标识带水印版本，去掉即为原图
    url = re.sub(r"[-_]wm(?=[.\-_/])", "", url, count=1)
    return url


@register
class XiaohongshuParser(Parser):
    platform = "xiaohongshu"
    url_markers = ("xiaohongshu.com", "xhslink.com")

    async def parse(self, url: str) -> ParseResult:
        headers = _build_headers()
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=config.HTTP_TIMEOUT
        ) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                raise ParseError(f"请求笔记页失败（HTTP {resp.status_code}）。")
            state = _extract_state(resp.text)
            note = _get_note(state)

        note_type = note.get("type")
        title = note.get("title") or note.get("desc") or ""
        author = ((note.get("user") or {}).get("nickname")) or None
        description = note.get("desc") or None

        images: list[ImageItem] = []
        videos: list[VideoItem] = []

        if note_type == "video":
            video = note.get("video") or {}
            media = video.get("media") or {}
            stream = media.get("stream") or {}
            # h264 兼容性最好，优先取 h264 的 masterUrl（无水印）
            for codec in ("h264", "h265", "av1"):
                candidates = stream.get(codec) or []
                if candidates:
                    item = candidates[0]
                    play_url = item.get("masterUrl") or (item.get("backupUrls") or [None])[0]
                    if play_url:
                        play_url = play_url.replace("http://", "https://", 1)
                        duration_ms = video.get("duration")
                        videos.append(
                            VideoItem(
                                url=play_url,
                                cover=_clean_image_url(
                                    (video.get("cover") or {}).get("urlDefault", "")
                                )
                                or None,
                                duration=int(duration_ms // 1000)
                                if isinstance(duration_ms, (int, float))
                                else None,
                            )
                        )
                    break
            if not videos:
                raise ParseError("视频流地址获取失败，可尝试配置 Cookie 后重试。")
        else:
            for img in note.get("imageList") or []:
                raw_url = img.get("urlDefault") or ""
                if not raw_url:
                    # 兜底：从 infoList 里挑最大清晰度
                    info_list = img.get("infoList") or []
                    if info_list:
                        raw_url = info_list[-1].get("url", "")
                if raw_url:
                    images.append(
                        ImageItem(
                            url=_clean_image_url(raw_url),
                            width=img.get("width"),
                            height=img.get("height"),
                        )
                    )
            if not images:
                raise ParseError("未提取到图片，该笔记可能为视频、纯文字或需要登录。")

        media_type = (
            MediaType.video
            if videos and not images
            else MediaType.image
            if images and not videos
            else MediaType.mixed
        )
        return ParseResult(
            platform=Platform.xiaohongshu,
            type=media_type,
            title=title or None,
            author=author,
            description=description,
            images=images,
            videos=videos,
        )
