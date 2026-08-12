"""エントリポイント。引数なしでWebアプリ起動、サブコマンド指定でCLI実行。"""
from __future__ import annotations

import socket
import sys
import threading
import webbrowser


def _find_free_port(host: str, port: int, tries: int = 10) -> int | None:
    """portから順に空きポートを探す。見つからなければNone。"""
    for p in range(port, port + tries):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host, p))
            return p
        except OSError:
            continue
    return None


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    import uvicorn

    from .web.app import create_app

    free = _find_free_port(host, port)
    if free is None:
        print(f"エラー: ポート {port}〜{port + 9} がすべて使用中です。"
              f"既に起動しているDiffDeskを閉じるか、--port で別番号を指定してください。",
              file=sys.stderr)
        sys.exit(1)
    if free != port:
        print(f"ポート {port} は使用中のため、代わりにポート {free} で起動します"
              f"(別のDiffDeskや他のアプリが {port} を使っています)。")
        port = free

    app = create_app()
    url = f"http://{host}:{port}"
    print(f"DiffDesk を起動します: {url}")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    except OSError as e:
        if getattr(e, "errno", None) in (48, 98, 10048):  # EADDRINUSE (mac/linux/win)
            print(f"エラー: ポート {port} は使用中です。別のDiffDeskが起動していないか"
                  f"確認するか、--port で別番号を指定してください。", file=sys.stderr)
            sys.exit(1)
        raise


def main() -> None:
    argv = sys.argv[1:]
    # 引数なし / serve / --port等のオプションのみ → Webアプリ起動
    if not argv or argv[0] in ("serve", "--serve") or argv[0].startswith("--"):
        rest = argv[1:] if argv and argv[0] in ("serve", "--serve") else argv
        port = 8765
        if "--port" in rest:
            try:
                port = int(rest[rest.index("--port") + 1])
            except (IndexError, ValueError):
                print("エラー: --port には番号を指定してください(例: --port 8770)",
                      file=sys.stderr)
                sys.exit(2)
        no_browser = "--no-browser" in rest
        serve(port=port, open_browser=not no_browser)
        return
    from .cli import run_cli
    sys.exit(run_cli(argv))


if __name__ == "__main__":
    main()
