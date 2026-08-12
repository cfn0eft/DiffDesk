"""照合結果のスナップショットと前回比較。

差分実行のたびに「問題行(一致以外・既知除く)」のスナップショットを
ファイルペアごとに保存し、次回実行時に前回と行レベルで比較する。
- 新規差異: 前回は問題なかったのに今回問題になった行(要調査)
- 解消:     前回問題だったが今回は問題でなくなった行
- 継続:     前回も今回も問題の行(放置されている差異)
保存先: 案件データフォルダ/snapshots/<A>__vs__<B>.json.gz(1世代前を .prev に保持)
"""
from __future__ import annotations

import gzip
import json
import re
from datetime import datetime
from pathlib import Path

from . import project as _project
from .model import DiffResult

_SAFE = re.compile(r'[\\/:*?"<>|\s.]+')
_MAX_LIST = 200  # 比較結果で返す行リストの上限(件数は全件)


def _snap_dir(directory: Path | None = None) -> Path:
    d = (directory or _project.data_dir()) / "snapshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe(name: str) -> str:
    s = _SAFE.sub("_", str(name)).strip("_")
    return (s or "file")[:60]


def _snap_path(name_a: str, name_b: str, directory: Path | None) -> Path:
    return _snap_dir(directory) / f"{_safe(name_a)}__vs__{_safe(name_b)}.json.gz"


def problems_snapshot(result: DiffResult) -> dict:
    """問題行(一致以外・既知除く)のスナップショット。key文字列→情報。"""
    rows: dict[str, dict] = {}
    for r in result.rows:
        if r.status == "same" or r.known:
            continue
        cols = {cd.col_a: [cd.value_a, cd.value_b] for cd in r.cell_diffs}
        rows["/".join(r.key)] = {"status": r.status, "cols": cols}
    return rows


def save_run_snapshot(result: DiffResult, *, directory: Path | None = None) -> None:
    """今回の結果を保存する(直前の保存分を1世代前として残す)。"""
    path = _snap_path(result.name_a, result.name_b, directory)
    prev_path = path.with_suffix(".gz.prev")
    if path.exists():
        prev_path.write_bytes(path.read_bytes())
    data = {
        "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "name_a": result.name_a, "name_b": result.name_b,
        "rows": problems_snapshot(result),
    }
    path.write_bytes(gzip.compress(
        json.dumps(data, ensure_ascii=False).encode("utf-8"), compresslevel=6))


def load_prev_snapshot(name_a: str, name_b: str, *,
                       directory: Path | None = None) -> dict | None:
    """1世代前(=前回実行時)のスナップショット。無ければNone。"""
    prev_path = _snap_path(name_a, name_b, directory).with_suffix(".gz.prev")
    if not prev_path.exists():
        return None
    try:
        return json.loads(gzip.decompress(prev_path.read_bytes()).decode("utf-8"))
    except Exception:
        return None


def compare_with_prev(result: DiffResult, *,
                      directory: Path | None = None) -> dict:
    """現在の結果を前回スナップショットと比較する。"""
    prev = load_prev_snapshot(result.name_a, result.name_b, directory=directory)
    if prev is None:
        return {"available": False}
    cur = problems_snapshot(result)
    prev_rows = prev.get("rows", {})

    def brief(key: str, info: dict) -> dict:
        cols = info.get("cols", {})
        first = next(iter(cols.items()), None)
        return {"key": key, "status": info.get("status", ""),
                "col": first[0] if first else "",
                "value_a": first[1][0] if first else "",
                "value_b": first[1][1] if first else ""}

    new = [brief(k, v) for k, v in cur.items() if k not in prev_rows]
    resolved = [brief(k, v) for k, v in prev_rows.items() if k not in cur]
    continuing = [brief(k, v) for k, v in cur.items() if k in prev_rows]
    return {
        "available": True,
        "prev_at": prev.get("at", ""),
        "counts": {"new": len(new), "resolved": len(resolved),
                   "continuing": len(continuing)},
        "new": new[:_MAX_LIST],
        "resolved": resolved[:_MAX_LIST],
        "continuing": continuing[:_MAX_LIST],
    }


def prev_key_sets(result: DiffResult, *,
                  directory: Path | None = None) -> dict | None:
    """行フィルタ用: 現在の問題行を new/continuing に分けたキー集合。"""
    prev = load_prev_snapshot(result.name_a, result.name_b, directory=directory)
    if prev is None:
        return None
    prev_rows = prev.get("rows", {})
    cur = problems_snapshot(result)
    return {
        "new": {k for k in cur if k not in prev_rows},
        "continuing": {k for k in cur if k in prev_rows},
    }
