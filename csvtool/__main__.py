"""エントリポイント。引数なしでWebアプリ起動、サブコマンド指定でCLI実行。"""
from __future__ import annotations

import sys
import threading
import webbrowser


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    import uvicorn

    from .web.app import create_app

    app = create_app()
    url = f"http://{host}:{port}"
    print(f"csvtool を起動します: {url}")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")


def main() -> None:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("serve", "--serve"):
        port = 8765
        rest = argv[1:] if argv else []
        if "--port" in rest:
            port = int(rest[rest.index("--port") + 1])
        no_browser = "--no-browser" in rest
        serve(port=port, open_browser=not no_browser)
        return
    from .cli import run_cli
    sys.exit(run_cli(argv))


if __name__ == "__main__":
    main()
