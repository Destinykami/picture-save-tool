# pic-save-tool

从小红书等平台提取**无水印原图 / 原视频**的小工具。
当前版本为 Web 网页端（Python + FastAPI + 原生 HTML），
后端为纯 REST API，后续可直接复用到微信小程序端。

## 功能

- **小红书**：粘贴分享链接（`xhslink.com` 短链或 `xiaohongshu.com` 笔记直链）
  - 图片笔记：返回无水印原图直链列表（支持批量复制链接）
  - 视频笔记：返回无水印视频直链 + 封面，页面内可直接预览
- **知乎**：粘贴文章（`zhuanlan.zhihu.com/p/<id>`）或回答（`zhihu.com/question/<qid>/answer/<aid>`）链接，
  从正文 HTML / 回答卡片 JSON 中提取图片，尺寸后缀（`_r` / `_b` / `_720x780q90` 等）还原为无水印原图，
  内嵌视频返回 `play_url` 直链；按 `v2-<hash>` 跨 CDN 镜像去重
- 多平台解析器注册机制，抖音等平台可即插即用

## 快速开始

```bash
./run.sh            # 自动创建 .venv、安装依赖并启动
# 或手动：
uv venv .venv
uv pip install -r requirements.txt --python .venv/bin/python
XHS_COOKIE="..." .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

打开浏览器访问 `http://127.0.0.1:8000`，粘贴链接即可。
若 8000 端口已被占用，可 `PORT=8100 ./run.sh` 换端口。

### 运行测试

```bash
uv venv .venv
uv pip install -r requirements-dev.txt --python .venv/bin/python
.venv/bin/python -m pytest tests/ -v
```

> 本机 uv 缓存默认在 `~/.cache/uv`，若被沙箱拦截可设置
> `UV_CACHE_DIR=$PWD/.uv-cache` 使用项目内缓存。

## API

| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| `POST` | `/api/parse` | 请求体 `{"url": "https://..."}`，返回无水印媒体直链 |
| `GET` | `/api/health` | 健康检查 |

`/api/parse` 返回示例：

```json
{
  "platform": "xiaohongshu",
  "type": "image",
  "title": "笔记标题",
  "author": "作者昵称",
  "description": "正文描述",
  "images": [{"url": "https://sns-webpic-qc.xhscdn.com/...", "width": 2478, "height": 3304}],
  "videos": []
}
```

解析失败返回 `422`，`detail` 为可直接展示的中文原因（如需要登录、链接失效）。

## 配置（环境变量）

| 变量 | 说明 |
| ---- | ---- |
| `XHS_COOKIE` | 可选。小红书网页版登录后的完整 Cookie 串。部分笔记 / 视频流需要登录态，配置后解析成功率更高。 |
| `ZHIHU_COOKIE` | 可选。知乎网页版登录后的完整 Cookie 串。知乎对匿名 / 数据中心 IP 有 JS 反爬挑战（返回 `zse-ck` 挑战页），配置登录后 Cookie 可跳过挑战并访问需登录的内容。 |
| `PORT` | 配合 `run.sh` 使用，默认 8000。 |

获取 Cookie：浏览器打开 xiaohongshu.com 并登录 → F12 → Network → 刷新 → 任意请求 → 复制 `Cookie` 请求头的值。

## 项目结构

```
app/
├── main.py            # FastAPI 入口：API + 静态前端
├── config.py          # 环境变量配置
├── schemas.py         # 请求 / 响应数据模型
├── parsers/
│   ├── base.py        # Parser 抽象 + 平台注册表（detect / register）
│   ├── xiaohongshu.py # 小红书解析器
│   └── zhihu.py       # 知乎解析器
└── static/
    └── index.html     # Web 前端（原生 HTML/CSS/JS，无构建）
tests/
├── test_xiaohongshu.py  # 小红书解析器单元测试（模拟 __INITIAL_STATE__ 页面）
└── test_zhihu.py        # 知乎解析器单元测试（模拟 __INITIAL_DATA__ 页面）
requirements.txt
requirements-dev.txt
run.sh
```

## 新增平台（以抖音为例）

1. 新建 `app/parsers/douyin.py`，实现 `DouyinParser(Parser)`，设置 `platform` 与 `url_markers`（如 `"douyin.com"`、`"v.douyin.com"`），在 `parse()` 中返回 `ParseResult`。
2. 在 `app/parsers/__init__.py` 中 import 新模块触发注册。
3. 前端无需改动，`/api/parse` 自动按链接特征路由。

## 解析原理

**小红书**：网页版笔记页把完整笔记数据序列化进 `window.__INITIAL_STATE__`，
其中 `imageList[].urlDefault` 为无水印原图 CDN 直链，
`video.media.stream.h264[0].masterUrl` 为无水印视频流。
解析器直接请求笔记页提取该 JSON，无需模拟 App 签名。

**知乎**：文章页 / 回答页把内容数据序列化进
`<script id="js-initialData" type="text/json">{...}</script>`（兼容旧版
`window.__INITIAL_DATA__` 写法）。正文为 HTML，解析器逐 `<img>` 提取图片。

**无水印原图的关键**：知乎每个原图 `<img>` 上同时挂了两个 hash——
- `data-original-token="v2-<hash>"`：**真正的无水印原图**（独立 hash，
  手机端页内展示用的就是它）；
- `data-original` / `src`（`v2-<hash>_<尺寸后缀>.<ext>`）：**带水印的显示版**。

解析器优先用 `data-original-token` 构造无水印直链（扩展名沿用显示版，默认 `.jpg`，
知乎 CDN 按 hash 出图），没有 token 才退回显示版并清理尺寸后缀
（`_r`/`_b`/`_s`/`_xs`/`_lr`/`_\d+w`/`_\d+x\d+q\d+` 及 `/80/` 前缀目录），按 hash 去重。
元信息 `answer.author` / `answer.question` 为内联对象（直接带 name/title），
也兼容退化为 ID 字符串引用的形态。内嵌视频取自 `entities.videos`
（play_url / stream / cover_url / duration）。
注意：知乎对匿名或数据中心 IP 会返回 `zse-ck` JS 反爬挑战页，
配置 `ZHIHU_COOKIE`（网页版登录 Cookie）可跳过挑战。
（以上结构已用真实回答页 + 登录 Cookie 端到端验证，确认 token 指向无水印原图。）

## 路线图

- [x] 小红书图片 / 视频解析（Web 端）
- [x] 知乎文章 / 回答解析（Web 端）
- [ ] 抖音平台解析器
- [ ] 批量链接解析、历史记录
- [ ] 微信小程序端（复用同一 REST API）

## 免责声明

本工具仅供个人学习与研究使用，请尊重原作者版权，勿用于商业用途或二次传播。
