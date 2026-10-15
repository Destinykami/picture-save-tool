"""知乎解析器。

原理：知乎文章页（zhuanlan.zhihu.com/p/<id>）与回答页
（zhihu.com/question/<qid>/answer/<aid>）把完整内容数据序列化进
``<script id="js-initialData" type="text/json">{...}</script>``，其中：
- ``initialState.entities.articles[id].content`` 为文章 HTML；
- ``initialState.entities.answers[id].content`` 为回答 HTML；
- ``answer.author`` / ``answer.question`` 多为内联对象（直接带 name/title），
  也可能退化为 ID 字符串引用，两种形态都兼容；
- ``initialState.entities.videos[id]`` 为内嵌视频信息
  （play_url / stream / cover_url / duration）。

正文里每个原图 <img> 上有两类 URL：
- ``data-original-token="v2-<hash>"``：真正的无水印原图（独立 hash，
  手机端页内展示的就是它）；
- ``data-original`` / ``src``：带水印的显示版（``v2-<hash>_<尺寸后缀>.<ext>``）。
解析器逐 <img> 提取，优先用 token 构造无水印原图直链（扩展名沿用显示版），
无 token 才退回显示版并清理尺寸后缀，按 hash 去重。
知乎对匿名/数据中心 IP 有 JS 反爬挑战，建议配置 ZHIHU_COOKIE（登录 Cookie）。
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

# 知乎把 SSR 数据放进 <script id="js-initialData" type="text/json">{...}</script>。
# 兼容旧版 window.__INITIAL_DATA__ = {...};</script> 写法。
_INITIAL_DATA_SCRIPT_RE = re.compile(
    r"<script[^>]*id=[\"']js-initialData[\"'][^>]*>(.*?)</script>", re.DOTALL
)
_INITIAL_DATA_GLOBAL_RE = re.compile(
    r"window\.__INITIAL_DATA__\s*=\s*(\{.*?\})\s*;\s*</script>", re.DOTALL
)
_ARTICLE_RE = re.compile(r"/p/(\d+)")
_ANSWER_RE = re.compile(r"/(?:question/\d+/)?answer/(\d+)")
# 知乎内容图片：pic[0-9a-z]*.zhimg.com/...v2-<hex>...（跳过头像/图标等无 v2 的资源）
_ZHIMG_RE = re.compile(
    r"https?://pic[0-9a-z]*\.zhimg\.com/[^\s\"'\\)\]>]*?v2-[0-9a-fA-F]+[^\s\"'\\)\]>]*"
)
# v2 哈希是图片唯一标识（picx/pic1 等主机只是 CDN 镜像），用于跨主机去重
_V2_HASH_RE = re.compile(r"v2-([0-9a-fA-F]+)")
# 捕获组 1 保留扩展名：_r.jpg → .jpg
_SIZE_SUFFIX_RE = re.compile(
    r"_(?:original|lr|zw|xs|\d+w|r|b|s)(\.(?:jpg|jpeg|png|webp|gif))$", re.IGNORECASE
)
_RESIZE_SUFFIX_RE = re.compile(
    r"_\d+x\d+(?:q\d+)?\.(?:jpg|jpeg|png|webp|gif)$", re.IGNORECASE
)
_SIZE_PREFIX_DIR_RE = re.compile(r"^(https?://pic[0-9a-z]*\.zhimg\.com)/\d+/", re.IGNORECASE)


def _build_headers() -> dict[str, str]:
    headers = {
        "User-Agent": config.USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://www.zhihu.com/",
    }
    if config.ZHIHU_COOKIE:
        headers["Cookie"] = config.ZHIHU_COOKIE
    return headers


def _clean_zhimg_url(url: str) -> str:
    """把知乎缩略图 URL 还原为无水印原图直链。

    - ``v2-abc_r.jpg?size=large``  → ``v2-abc.jpg``
    - ``v2-abc.jpg_720x780q90.jpg`` → ``v2-abc.jpg``
    - ``/80/v2-abc_1440w.png``      → ``v2-abc.png``（图标尺寸前缀目录）
    """
    path = url.split("?", 1)[0].split("#", 1)[0]
    path = _SIZE_PREFIX_DIR_RE.sub(r"\1/", path)
    path = _RESIZE_SUFFIX_RE.sub("", path)
    path = _SIZE_SUFFIX_RE.sub(r"\1", path)
    return path.replace("http://", "https://", 1)


def _extract_initial_data(html: str) -> dict:
    m = _INITIAL_DATA_SCRIPT_RE.search(html) or _INITIAL_DATA_GLOBAL_RE.search(html)
    if not m:
        raise ParseError(
            "页面中未找到初始数据（js-initialData）。知乎对匿名访问有 JS 反爬挑战，"
            "请配置 ZHIHU_COOKIE（知乎网页版登录后的 Cookie）后重试。"
        )
    raw = m.group(1).replace("undefined", "null")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ParseError(f"知乎初始数据解析失败：{exc}") from exc


def _find_content_string(data: dict, url: str) -> str | None:
    """按 URL 特征定位正文（文章 HTML 或回答卡片 JSON 串）。"""
    entities = data.get("initialState", {}).get("entities", {})
    article_match = _ARTICLE_RE.search(url)
    if article_match:
        article = entities.get("articles", {}).get(article_match.group(1))
        if article and article.get("content"):
            return article["content"]
    answer_match = _ANSWER_RE.search(url)
    if answer_match:
        answer = entities.get("answers", {}).get(answer_match.group(1))
        if answer and answer.get("content"):
            return answer["content"]
    # 兜底：初始数据里唯一的文章 / 回答
    if len(entities.get("articles", {})) == 1:
        only = next(iter(entities["articles"].values()))
        if only.get("content"):
            return only["content"]
    if len(entities.get("answers", {})) == 1:
        only = next(iter(entities["answers"].values()))
        if only.get("content"):
            return only["content"]
    return None


def _resolve_name(value, users: dict) -> str | None:
    """author 字段可能是内联用户对象（含 name）或用户 ID 字符串引用。"""
    if isinstance(value, dict):
        return value.get("name")
    if isinstance(value, str):
        return users.get(value, {}).get("name")
    return None


def _resolve_question_title(value, questions: dict) -> str | None:
    """question 字段可能是内联问题对象（含 title）或问题 ID 字符串引用。"""
    if isinstance(value, dict):
        return value.get("title")
    if isinstance(value, str):
        return questions.get(value, {}).get("title")
    return None


def _extract_meta(data: dict, url: str) -> tuple[str | None, str | None]:
    """提取标题与作者。"""
    entities = data.get("initialState", {}).get("entities", {})
    users = entities.get("users", {})
    questions = entities.get("questions", {})
    title: str | None = None
    author: str | None = None

    article_match = _ARTICLE_RE.search(url)
    answer_match = _ANSWER_RE.search(url)
    if answer_match:
        answer = entities.get("answers", {}).get(answer_match.group(1), {})
        title = _resolve_question_title(answer.get("question"), questions)
        author = _resolve_name(answer.get("author"), users)
    elif article_match:
        article = entities.get("articles", {}).get(article_match.group(1), {})
        title = article.get("title")
        author = _resolve_name(article.get("author"), users)
    else:
        if len(entities.get("articles", {})) == 1:
            article = next(iter(entities["articles"].values()))
            title = article.get("title")
            author = _resolve_name(article.get("author"), users)
        elif len(entities.get("answers", {})) == 1:
            answer = next(iter(entities["answers"].values()))
            title = _resolve_question_title(answer.get("question"), questions)
            author = _resolve_name(answer.get("author"), users)
    return title or None, author or None


def _extract_images(content: str) -> list[ImageItem]:
    """从正文 HTML 提取图片，优先无水印原图。

    知乎每个原图 <img> 上有两类 URL：
    - ``data-original-token="v2-<hash>"``：真正的无水印原图（独立 hash，
      手机端页内展示用的就是它）；
    - ``data-original`` / ``src``：带水印的显示版。
    逐 <img> 提取，有 token 就用 token 构造无水印直链（扩展名沿用显示版），
    无 token 才退回显示版；按 hash 去重（<noscript> 与懒加载会重复出现）。
    """
    images: list[ImageItem] = []
    seen: set[str] = set()
    for tag in re.findall(r"<img[^>]*>", content):
        if "origin_image" not in tag and "zhimg.com" not in tag:
            continue
        # 1) 无水印原图 token
        token_m = re.search(r'data-original-token="v2-([0-9a-fA-F]+)"', tag)
        if token_m:
            key = "tok:" + token_m.group(1)
            if key in seen:
                continue
            seen.add(key)
            # 扩展名沿用显示版，找不到就默认 .jpg（知乎 CDN 按 hash 出图）
            ext_m = re.search(
                r'(?:data-original|src)="https?://pic[0-9a-z]*\.zhimg\.com/[^"]*\.([a-z0-9]+)"',
                tag,
            )
            ext = ("." + ext_m.group(1)) if ext_m else ".jpg"
            images.append(ImageItem(url=f"https://picx.zhimg.com/v2-{token_m.group(1)}{ext}"))
            continue
        # 2) 退回带水印显示版（清理尺寸后缀）
        disp_m = re.search(
            r'(?:data-original|src)="(https?://pic[0-9a-z]*\.zhimg\.com/[^"]+)"', tag
        )
        if not disp_m:
            continue
        clean = _clean_zhimg_url(disp_m.group(1))
        hash_m = _V2_HASH_RE.search(clean)
        key = hash_m.group(1) if hash_m else clean
        if key in seen:
            continue
        seen.add(key)
        images.append(ImageItem(url=clean))
    return images


def _extract_videos(entities: dict) -> list[VideoItem]:
    videos: list[VideoItem] = []
    for v in entities.get("videos", {}).values():
        play_url = v.get("play_url")
        if not play_url:
            stream = v.get("stream") or {}
            for codec in ("h264", "h265", "av1"):
                candidates = stream.get(codec) or []
                if candidates:
                    play_url = candidates[0]
                    break
        if not play_url:
            continue
        cover = v.get("cover_url") or None
        if cover and "zhimg.com" in cover:
            cover = _clean_zhimg_url(cover)
        videos.append(
            VideoItem(
                url=play_url.replace("http://", "https://", 1),
                cover=cover,
                duration=int(v["duration"]) if isinstance(v.get("duration"), (int, float)) else None,
            )
        )
    return videos


@register
class ZhihuParser(Parser):
    platform = "zhihu"
    url_markers = ("zhihu.com",)  # 覆盖 www / zhuanlan / link 等子域

    async def parse(self, url: str) -> ParseResult:
        headers = _build_headers()
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=config.HTTP_TIMEOUT
        ) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                raise ParseError(f"请求知乎页面失败（HTTP {resp.status_code}）。")
            data = _extract_initial_data(resp.text)
            final_url = str(resp.url)

        content = _find_content_string(data, final_url)
        title, author = _extract_meta(data, final_url)
        entities = data.get("initialState", {}).get("entities", {})
        videos = _extract_videos(entities)

        # 优先：逐 <img> 提取无水印原图（data-original-token）
        images: list[ImageItem] = []
        if content and "<img" in content:
            images = _extract_images(content)
        # 兜底：正文无 <img> 标签时（卡片 JSON / 其它形态），按 zhimg URL 全局扫描
        if not images:
            seen: set[str] = set()
            scan_text = content or json.dumps(data, ensure_ascii=False)
            for raw_url in _ZHIMG_RE.findall(scan_text):
                clean = _clean_zhimg_url(raw_url)
                hash_m = _V2_HASH_RE.search(clean)
                key = hash_m.group(1) if hash_m else clean
                if key not in seen:
                    seen.add(key)
                    images.append(ImageItem(url=clean))

        if not images and not videos:
            raise ParseError(
                "未提取到图片/视频，该内容可能为纯文字、已失效，或触发了登录墙。"
                "可配置 ZHIHU_COOKIE 后重试。"
            )
        media_type = (
            MediaType.video
            if videos and not images
            else MediaType.image
            if images and not videos
            else MediaType.mixed
        )
        return ParseResult(
            platform=Platform.zhihu,
            type=media_type,
            title=title,
            author=author,
            description=None,
            images=images,
            videos=videos,
        )
