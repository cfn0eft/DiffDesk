"""FastAPIアプリ本体。静的ファイル(SPA)の配信とエラーハンドリング。"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..core import DiffDeskError, EncodingWriteError
from .routes import router

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


class NoCacheStaticFiles(StaticFiles):
    """毎回サーバーに確認させる(ETag再検証)。

    アップデート後にブラウザが古いJS/CSSを使い続けて「新機能が出ない」
    事故を防ぐ。ローカルツールなので再検証コストは無視できる。
    """

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


def create_app() -> FastAPI:
    app = FastAPI(title="diffdesk", docs_url="/docs")
    app.include_router(router)

    @app.exception_handler(DiffDeskError)
    async def handle_diffdesk_error(request: Request, exc: DiffDeskError):
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

    app.mount("/static", NoCacheStaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        html = html.replace("{{V}}", __version__)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    @app.get("/compare", include_in_schema=False)
    def compare():
        """見比べビューア(照合なし・確認専用の別ウィンドウ)。"""
        html = (STATIC_DIR / "compare.html").read_text(encoding="utf-8")
        html = html.replace("{{V}}", __version__)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    @app.get("/help", include_in_schema=False)
    def help_page():
        """ヘルプ(目次・検索付きの使い方ガイド)。"""
        html = (STATIC_DIR / "help.html").read_text(encoding="utf-8")
        html = html.replace("{{V}}", __version__)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    return app
