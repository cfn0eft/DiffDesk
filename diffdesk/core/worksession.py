"""作業セッションの保存/復元。

読み込んだファイル(生バイト)・読込設定・A/B割当・マッピング・比較オプション・
行フィルタをまるごと1ファイルに保存し、翌日そのまま続きから再開できるようにする。
保存先: 現在の案件のデータフォルダ配下 sessions/<名前>.json.gz
"""
from __future__ import annotations

import base64
import gzip
import json
import re
from datetime import datetime
from pathlib import Path

from . import project as _project
from .model import DiffDeskError

_MAX_TOTAL_BYTES = 100 * 1024 * 1024  # 保存対象ファイル合計の上限(アップロード上限と同じ)
_SAFE = re.compile(r'[\\/:*?"<>|\s.]+')
VERSION = 1


def _sessions_dir(directory: Path | None = None) -> Path:
    d = (directory or _project.data_dir()) / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_name(name: str) -> str:
    name = str(name).strip()
    if not name:
        raise DiffDeskError("セッション名を入力してください。")
    if len(name) > 50:
        raise DiffDeskError("セッション名は50文字以内にしてください。")
    s = _SAFE.sub("_", name).strip("_")
    if not s:
        raise DiffDeskError("セッション名に使える文字がありません。")
    return s


def save_worksession(name: str, payload: dict, *,
                     directory: Path | None = None) -> dict:
    """セッションを保存してメタ情報を返す。payloadは routes 側で組み立てる。

    payload["files"] = [{"filename", "raw_b64", "parse_params", "role"}]
    payload["mapping" / "options" / "row_filter"] = そのままのdict
    """
    total = sum(len(f.get("raw_b64", "")) for f in payload.get("files", []))
    if total * 3 // 4 > _MAX_TOTAL_BYTES:
        raise DiffDeskError("保存対象のファイル合計が100MBを超えています。")
    if not payload.get("files"):
        raise DiffDeskError("保存するファイルがありません。先にファイルを読み込んでください。")
    data = dict(payload)
    data["version"] = VERSION
    data["name"] = str(name).strip()
    data["saved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    raw = gzip.compress(
        json.dumps(data, ensure_ascii=False).encode("utf-8"), compresslevel=6)
    path = _sessions_dir(directory) / f"{_safe_name(name)}.json.gz"
    path.write_bytes(raw)
    return _meta(path, data)


def _meta(path: Path, data: dict) -> dict:
    return {
        "name": data.get("name", path.stem),
        "saved_at": data.get("saved_at", ""),
        "files": [{"filename": f.get("filename", ""), "role": f.get("role")}
                  for f in data.get("files", [])],
        "size": path.stat().st_size,
    }


def list_worksessions(*, directory: Path | None = None) -> list[dict]:
    out = []
    for path in sorted(_sessions_dir(directory).glob("*.json.gz")):
        try:
            data = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
            out.append(_meta(path, data))
        except Exception:
            out.append({"name": path.stem, "saved_at": "(読込不可)",
                        "files": [], "size": path.stat().st_size})
    out.sort(key=lambda m: m.get("saved_at", ""), reverse=True)
    return out


def load_worksession(name: str, *, directory: Path | None = None) -> dict:
    path = _sessions_dir(directory) / f"{_safe_name(name)}.json.gz"
    if not path.exists():
        raise DiffDeskError(f"セッションがありません: {name}")
    try:
        return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    except Exception:
        raise DiffDeskError(f"セッションの読み込みに失敗しました: {name}")


def delete_worksession(name: str, *, directory: Path | None = None) -> None:
    path = _sessions_dir(directory) / f"{_safe_name(name)}.json.gz"
    if not path.exists():
        raise DiffDeskError(f"セッションがありません: {name}")
    path.unlink()


def encode_raw(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def decode_raw(raw_b64: str) -> bytes:
    return base64.b64decode(raw_b64.encode("ascii"))
