"""監査ログ(追記専用)。

「いつ・何をしたか」を案件ごとに audit.jsonl へ記録する。
QA・CSV(Computer System Validation)的な作業証跡として、
検証パックにも同梱される。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import project as _project
from .model import Table

_MAX_DETAIL_CHARS = 500


def _audit_path(directory: Path | None = None) -> Path:
    d = directory or _project.data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / "audit.jsonl"


def audit(action: str, detail: str = "", *, directory: Path | None = None) -> None:
    """1操作を追記する。失敗しても本体処理は妨げない。"""
    try:
        rec = {
            "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": str(action),
            "detail": str(detail)[:_MAX_DETAIL_CHARS],
        }
        with _audit_path(directory).open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def load_audit(*, limit: int = 200, directory: Path | None = None) -> list[dict]:
    """新しい順に最大limit件。"""
    path = _audit_path(directory)
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records[-limit:][::-1]


def audit_table(*, limit: int = 1000, directory: Path | None = None) -> Table:
    """CSV出力用のTable(新しい順)。"""
    rows = [[r.get("at", ""), r.get("action", ""), r.get("detail", "")]
            for r in load_audit(limit=limit, directory=directory)]
    return Table(columns=["日時", "操作", "内容"], rows=rows, name="監査ログ")


def clear_audit(*, directory: Path | None = None) -> None:
    _audit_path(directory).unlink(missing_ok=True)
