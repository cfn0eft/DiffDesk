"""FastAPIアプリ本体。静的ファイル(SPA)の配信とエラーハンドリング。"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..core import CsvToolError, EncodingWriteError
from .routes import router

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="csvtool", docs_url="/docs")
    app.include_router(router)

    @app.exception_handler(CsvToolError)
    async def handle_csvtool_error(request: Request, exc: CsvToolError):
        payload = {"error": {"code": getattr(exc, "code", "error"),
                             "message": exc.message}}
        if isinstance(exc, EncodingWriteError):
            payload["error"]["locations"] = exc.details.get("locations", [])
        elif exc.details:
            payload["error"]["details"] = {
                k: v for k, v in exc.details.items()
                if isinstance(v, (str, int, float, bool, list))
            }
        return JSONResponse(status_code=400, content=payload)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app
