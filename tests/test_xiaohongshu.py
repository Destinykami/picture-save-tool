"""小红书解析器单元测试：用模拟的 __INITIAL_STATE__ 页面验证提取逻辑。"""
import json
import re

import pytest

from app.parsers import xiaohongshu as xhs
from app.schemas import MediaType, Platform

# ---- 模拟真实小红书笔记页的 __INITIAL_STATE__ 结构 ----

IMAGE_NOTE_STATE = {
    "note": {
        "noteDetailMap": {
            "665f0a1b000000001c00abcd": {
                "note": {
                    "type": "normal",
                    "title": "秋冬穿搭分享",
                    "desc": "几套入秋穿搭，图2最推荐！",
                    "user": {"nickname": "穿搭博主"},
                    "imageList": [
                        {
                            "width": 2478,
                            "height": 3304,
                            "urlDefault": "http://sns-webpic-qc.xhscdn.com/20250101-10/aaaa.jpg",
                            "infoList": [{"url": "http://sns-webpic-qc.xhscdn.com/20250101-10/aaaa-small.jpg"}],
                        },
                        {
                            "width": 1280,
                            "height": 1707,
                            "urlDefault": "http://sns-webpic-qc.xhscdn.com/20250101-10/bbbb_wm.jpg",
                            "infoList": [{"url": "http://sns-webpic-qc.xhscdn.com/20250101-10/bbbb-small.jpg"}],
                        },
                    ],
                }
            }
        }
    }
}

VIDEO_NOTE_STATE = {
    "note": {
        "noteDetailMap": {
            "665f0a1b000000001c00ef01": {
                "note": {
                    "type": "video",
                    "title": "",
                    "desc": "一条跳舞视频",
                    "user": {"nickname": "舞蹈博主"},
                    "video": {
                        "cover": {"urlDefault": "http://sns-webpic-qc.xhscdn.com/20250101-10/cover_wm.jpg"},
                        "duration": 15300,
                        "media": {
                            "stream": {
                                "h264": [
                                    {
                                        "masterUrl": "http://v26-web.douyinvod.com/xxx/video/tos/xxx.mp4",
                                        "backupUrls": ["http://v3-web.douyinvod.com/xxx.mp4"],
                                    }
                                ]
                            }
                        },
                    },
                }
            }
        }
    }
}


def _html_of(state: dict) -> str:
    raw = json.dumps(state, ensure_ascii=False)
    # 模拟页面中 undefined 直接写入 JSON 的情况
    raw = raw.replace('"cover": null', '"cover": undefined')
    return (
        "<html><head></head><body>"
        f"<script>window.__INITIAL_STATE__={raw}</script>"
        "</body></html>"
    )


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.status_code = 200


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs) -> None:
        self._text = _html_of(self.state)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None):
        return _FakeResponse(self._text)


@pytest.fixture(autouse=True)
def _patch_httpx(monkeypatch):
    """按被测笔记类型替换 httpx.AsyncClient。"""

    def _install(state: dict) -> None:
        fake_cls = type("FakeClient", (_FakeAsyncClient,), {"state": state})
        monkeypatch.setattr(xhs.httpx, "AsyncClient", fake_cls)

    # 默认图片笔记，单个测试内可调用 _install 覆盖
    _install(IMAGE_NOTE_STATE)
    yield _install


def test_extract_state_handles_undefined():
    state = json.loads(json.dumps(IMAGE_NOTE_STATE).replace('"cover": null', '"cover": undefined'))
    raw = json.dumps(state, ensure_ascii=False)
    html = f"<script>window.__INITIAL_STATE__={raw}</script>"
    parsed = xhs._extract_state(html)
    assert parsed["note"]["noteDetailMap"], "应解析出 noteDetailMap"


def test_clean_image_url_strips_watermark_markers():
    assert xhs._clean_image_url("http://a/b_wm.jpg") == "https://a/b.jpg"
    assert xhs._clean_image_url("https://a/b-wm/webp") == "https://a/b/webp"
    assert xhs._clean_image_url("http://a/ok.jpg") == "https://a/ok.jpg"


def test_parse_image_note(_patch_httpx):
    import asyncio

    result = asyncio.run(xhs.XiaohongshuParser().parse("https://xhslink.com/abc"))
    assert result.platform is Platform.xiaohongshu
    assert result.type is MediaType.image
    assert result.title == "秋冬穿搭分享"
    assert result.author == "穿搭博主"
    assert len(result.images) == 2
    assert result.images[0].url == "https://sns-webpic-qc.xhscdn.com/20250101-10/aaaa.jpg"
    assert result.images[1].url == "https://sns-webpic-qc.xhscdn.com/20250101-10/bbbb.jpg"  # _wm 被剥离
    assert result.images[0].width == 2478


def test_parse_video_note(_patch_httpx):
    import asyncio

    _patch_httpx(VIDEO_NOTE_STATE)
    result = asyncio.run(xhs.XiaohongshuParser().parse("https://www.xiaohongshu.com/explore/665f0a1b000000001c00ef01"))
    assert result.type is MediaType.video
    assert len(result.videos) == 1
    v = result.videos[0]
    assert v.url == "https://v26-web.douyinvod.com/xxx/video/tos/xxx.mp4"
    assert v.duration == 15
    assert v.cover and v.cover.endswith("cover.jpg")  # 封面 _wm 被剥离
