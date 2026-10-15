"""FastAPI 入口：REST API + 静态前端。

启动：uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .parsers import detect
from .schemas import ParseError, ParseRequest, ParseResult

app = FastAPI(
    title="pic-save-tool",
    description="从小红书等平台提取无水印图片/视频的小工具",
    version="0.1.0",
)

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    """直接返回前端页面（静态文件根目录下的 index.html）。"""
    from fastapi.responses import FileResponse

    index_file = STATIC_DIR / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    return {"message": "前端未构建，请先创建 static/index.html"}


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/parse", response_model=ParseResult)
async def parse(req: ParseRequest) -> ParseResult:
    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="请输入以 http(s):// 开头的链接")
    try:
        parser = detect(url)  # 平台不匹配时抛 ParseError
        return await parser.parse(url)
    except ParseError as exc:
        raise HTTPException(status_code=422, detail=exc.msg) from exc
    except Exception as exc:  # 网络超时等兜底
        raise HTTPException(status_code=502, detail=f"解析出错：{exc}") from exc


# 统一 JSON 错误格式：{"detail": "中文原因"}
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):  # noqa: ANN001
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
