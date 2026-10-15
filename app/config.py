"""运行时配置：全部来自环境变量，便于部署。"""
from __future__ import annotations

import os

# 请求小红书网页时使用的桌面端 UA（移动端 UA 拿到的页面结构不同）
USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 可选：部分笔记需要登录态才能访问，可在此填入浏览器里的完整 Cookie 串
# （小红书网页版登录后，F12 → Network → 任意请求 → 复制 Cookie 请求头）。
XHS_COOKIE: str = os.environ.get("XHS_COOKIE", "")

# 可选：知乎网页版登录后的完整 Cookie 串。知乎对匿名/数据中心 IP 有 JS 反爬
# 挑战，配置登录后 Cookie 可跳过挑战并访问需登录的内容。
ZHIHU_COOKIE: str = os.environ.get("ZHIHU_COOKIE", "")

HTTP_TIMEOUT: float = 20.0
