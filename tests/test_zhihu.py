"""知乎解析器单元测试。

夹具贴合线上真实结构（已用真实页面验证）：
- 数据在 <script id="js-initialData" type="text/json">{...}</script>；
- answer.author / answer.question 为内联对象（直接带 name/title）；
- 正文为 HTML（<p>/<img>），图片为 pic*.zhimg.com/v2-<hash>_<后缀>.<ext>。
"""
import asyncio
import json

import pytest

from app.parsers import zhihu as zh
from app.schemas import MediaType, Platform

# 构造真实 <img> 标签：data-original-token 是无水印原图，data-original/src 是带水印显示版
def _img(display_hash: str, token_hash: str | None, ext: str = "jpg") -> str:
    disp = f"https://pic1.zhimg.com/50/v2-{display_hash}_720w.{ext}?source=x"
    orig = f"https://picx.zhimg.com/v2-{display_hash}_r.{ext}?source=x"
    token = f' data-original-token="v2-{token_hash}"' if token_hash else ""
    return (
        f'<img src="{disp}"{token} class="origin_image zh-lightbox-thumb lazy" '
        f'data-original="{orig}" data-actualsrc="{disp}"/>'
    )


# ---- 真实结构的文章页夹具（含无水印 token）----
ARTICLE_STATE = {
    "initialState": {
        "entities": {
            "articles": {
                "108761079": {
                    "title": "一文讲清楚图片压缩",
                    "author": {"id": "u1", "name": "测试作者"},  # 内联用户对象
                    "content": (
                        '<p data-pid="a">正文</p>'
                        # 图1：有 token → 应取无水印原图
                        + _img("a1b2c3d4e5f60000", "11112222333344445555666677778888")
                        # 图2：无 token → 退回带水印显示版（清理后缀）
                        + _img("ffff00001111aaaa", None, ext="jpeg")
                    ),
                }
            },
            "videos": {
                "v999": {
                    "play_url": "http://api.zhihu.com/video/stream/abc_1080p.mp4",
                    "cover_url": "https://picx.zhimg.com/v2-cover0000_r.jpg",
                    "duration": 42,
                }
            },
        }
    }
}

# ---- 真实结构的回答页夹具：author/question 内联，两张图都有 token ----
ANSWER_STATE = {
    "initialState": {
        "entities": {
            "answers": {
                "2400000000000000000": {
                    "question": {"id": "1001", "title": "如何无损保存知乎图片？"},
                    "author": {"id": "u2", "name": "答主"},
                    "content": (
                        '<p data-pid="x">看图</p>'
                        + _img("aaaabbbbcccc", "aaaaaaaa111122223333444455556666")
                        # 同一 token 在 <noscript> 与懒加载重复出现，应去重
                        + _img("aaaabbbbcccc", "aaaaaaaa111122223333444455556666")
                        + _img("dddddddd9999", "bbbbbbbb111122223333444455556666")
                    ),
                }
            }
        }
    }
}


def _html_of(state: dict) -> str:
    """包装为线上真实的 js-initialData script 标签。"""
    raw = json.dumps(state, ensure_ascii=False)
    return (
        "<html><body>"
        f'<script id="js-initialData" type="text/json">{raw}</script>'
        "</body></html>"
    )


class _FakeResponse:
    def __init__(self, text: str, url: str) -> None:
        self.text = text
        self.url = url
        self.status_code = 200


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None):
        return _FakeResponse(_html_of(self.state), url)


@pytest.fixture
def _patch_httpx(monkeypatch):
    def _install(state: dict) -> None:
        fake_cls = type("FakeClient", (_FakeAsyncClient,), {"state": state})
        monkeypatch.setattr(zh.httpx, "AsyncClient", fake_cls)

    _install(ARTICLE_STATE)
    yield _install


def test_clean_zhimg_url_variants():
    assert (
        zh._clean_zhimg_url("http://picx.zhimg.com/v2-abc_r.jpg?size=large")
        == "https://picx.zhimg.com/v2-abc.jpg"
    )
    assert (
        zh._clean_zhimg_url("https://pic1.zhimg.com/v2-abc.jpg_720x780q90.jpg")
        == "https://pic1.zhimg.com/v2-abc.jpg"
    )
    assert (
        zh._clean_zhimg_url("https://pic1.zhimg.com/80/v2-abc_1440w.png")
        == "https://pic1.zhimg.com/v2-abc.png"
    )
    assert (
        zh._clean_zhimg_url("https://picx.zhimg.com/v2-abc.jpeg")
        == "https://picx.zhimg.com/v2-abc.jpeg"
    )


def test_extract_initial_data_script_tag():
    html = _html_of(ARTICLE_STATE)
    data = zh._extract_initial_data(html)
    assert "108761079" in data["initialState"]["entities"]["articles"]


def test_detect_routes_zhihu_links():
    from app.parsers import detect

    assert detect("https://zhuanlan.zhihu.com/p/108761079").platform == "zhihu"
    assert detect("https://www.zhihu.com/question/1001/answer/2400").platform == "zhihu"


def test_parse_article_inline_author(_patch_httpx):
    result = asyncio.run(zh.ZhihuParser().parse("https://zhuanlan.zhihu.com/p/108761079"))
    assert result.platform is Platform.zhihu
    assert result.type is MediaType.mixed  # 有图也有视频
    assert result.title == "一文讲清楚图片压缩"
    assert result.author == "测试作者"  # 内联 author 对象
    urls = [i.url for i in result.images]
    # 图1 有 token → 取无水印原图；图2 无 token → 退回带水印显示版（清理后缀）
    assert urls == [
        "https://picx.zhimg.com/v2-11112222333344445555666677778888.jpg",
        "https://pic1.zhimg.com/v2-ffff00001111aaaa.jpeg",
    ]
    v = result.videos[0]
    assert v.url == "https://api.zhihu.com/video/stream/abc_1080p.mp4"
    assert v.duration == 42
    assert v.cover and v.cover.endswith("v2-cover0000.jpg")


def test_parse_answer_inline_question(_patch_httpx):
    _patch_httpx(ANSWER_STATE)
    result = asyncio.run(
        zh.ZhihuParser().parse("https://www.zhihu.com/question/1001/answer/2400000000000000000")
    )
    assert result.type is MediaType.image
    assert result.title == "如何无损保存知乎图片？"  # 内联 question 对象
    assert result.author == "答主"
    # 三处 <img> 只有两个独立 token（一个重复出现被去重），全部取无水印原图
    assert [i.url for i in result.images] == [
        "https://picx.zhimg.com/v2-aaaaaaaa111122223333444455556666.jpg",
        "https://picx.zhimg.com/v2-bbbbbbbb111122223333444455556666.jpg",
    ]
    assert result.videos == []
