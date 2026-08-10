"""バージョン完全固定+SHA256ハッシュ付き requirements.txt を生成する。

インストール済み環境から依存クロージャを解決し、各パッケージの
配布ファイルハッシュを PyPI JSON API から取得する。

実行: python scripts/make_requirements.py
生成: requirements.txt (実行用) / requirements-dev.txt (開発用追加分)

利用側は以下でハッシュ検証付きインストールができる:
    pip install --require-hashes --only-binary :all: -r requirements.txt
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from importlib import metadata
from pathlib import Path

RUNTIME = ["openpyxl", "charset-normalizer", "fastapi", "uvicorn", "python-multipart"]
DEV = ["pytest", "httpx"]

ROOT = Path(__file__).resolve().parent.parent


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def closure(roots: list[str]) -> dict[str, str]:
    """依存クロージャを {正規化名: バージョン} で返す(環境マーカーは無視して全部含める)。"""
    result: dict[str, str] = {}
    queue = [normalize(r) for r in roots]
    while queue:
        name = queue.pop()
        if name in result:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            # win32専用等でこの環境に無いもの(colorama等)はPyPIから最新を引かない。
            # クロスプラットフォーム用に明示リストで対応する。
            print(f"  注意: {name} は未インストールのためスキップ", file=sys.stderr)
            continue
        result[name] = dist.version
        for req in dist.requires or []:
            m = re.match(r"^\s*([A-Za-z0-9._-]+)", req)
            if not m:
                continue
            if "extra ==" in req:
                continue  # extrasは含めない(uvicornはstandardなしで使う)
            queue.append(normalize(m.group(1)))
    return result


# 特定環境でのみ必要になる既知の依存(マーカー付きで固定する)。
# この環境には無いためバージョンはPyPIの最新安定版を使う。
RUNTIME_PLATFORM_EXTRAS = {
    "colorama": 'sys_platform == "win32"',          # click依存(Windowsのみ)
    "exceptiongroup": 'python_version < "3.11"',    # anyio依存(3.10のみ)
}
DEV_PLATFORM_EXTRAS = {
    "tomli": 'python_version < "3.11"',             # pytest依存(3.10のみ)
}


def pypi_hashes(name: str, version: str) -> list[str]:
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    with urllib.request.urlopen(url, timeout=30) as res:
        data = json.load(res)
    hashes = [f["digests"]["sha256"] for f in data["urls"]]
    if not hashes:
        raise RuntimeError(f"{name}=={version} の配布ファイルが見つかりません")
    return hashes


def pypi_latest(name: str) -> str:
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/json", timeout=30) as res:
        return json.load(res)["info"]["version"]


def emit(pins: dict[str, str], extra_markers: dict[str, str]) -> str:
    lines = []
    for name in sorted(pins):
        version = pins[name]
        hashes = pypi_hashes(name, version)
        marker = extra_markers.get(name, "")
        head = f"{name}=={version}" + (f" ; {marker}" if marker else "")
        lines.append(head + " \\")
        for i, h in enumerate(hashes):
            tail = " \\" if i < len(hashes) - 1 else ""
            lines.append(f"    --hash=sha256:{h}{tail}")
        print(f"  {name}=={version} ({len(hashes)} hashes)")
    return "\n".join(lines) + "\n"


def main() -> None:
    print("実行用依存を解決中...")
    runtime = closure(RUNTIME)
    markers: dict[str, str] = {}
    for name, marker in RUNTIME_PLATFORM_EXTRAS.items():
        if name not in runtime:
            runtime[name] = pypi_latest(name)
            markers[name] = marker

    header = (
        "# このファイルは scripts/make_requirements.py で生成(バージョン固定+SHA256ハッシュ付き)。\n"
        "# インストール: pip install --require-hashes --only-binary :all: -r requirements.txt\n"
    )
    (ROOT / "requirements.txt").write_text(header + emit(runtime, markers), encoding="utf-8")

    print("開発用依存を解決中...")
    dev_all = closure(RUNTIME + DEV)
    dev_only = {k: v for k, v in dev_all.items() if k not in runtime}
    dev_markers: dict[str, str] = {}
    for name, marker in DEV_PLATFORM_EXTRAS.items():
        if name not in dev_only:
            dev_only[name] = pypi_latest(name)
            dev_markers[name] = marker
    header_dev = (
        "# 開発用の追加依存(テスト実行に必要)。requirements.txt と併せてインストールする。\n"
        "# pip install --require-hashes --only-binary :all: -r requirements.txt -r requirements-dev.txt\n"
    )
    (ROOT / "requirements-dev.txt").write_text(header_dev + emit(dev_only, dev_markers), encoding="utf-8")
    print("完了: requirements.txt / requirements-dev.txt")


if __name__ == "__main__":
    main()
