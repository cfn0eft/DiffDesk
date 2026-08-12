"""ワークスペースの永続データ(既知差分・照合履歴・ユーザー辞書・手動紐づけ)。

保存先: ~/.diffdesk/ 配下(プロファイルと同じ場所)。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import profile as _profile
from .model import DiffDeskError

_HISTORY_LIMIT = 500


def _data_dir(directory: Path | None = None) -> Path:
    d = directory or _profile.DEFAULT_PROFILE_DIR.parent
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 既知差分
# エントリ形式:
#   {"type": "cell", "key": [...], "col_a": str, "value_a": str, "value_b": str,
#    "note": str, "added_at": iso8601}
#   {"type": "row", "key": [...], "status": "only_a"|"only_b", "note": ..., "added_at": ...}
#   {"type": "value", "col_a": str, "value_a": str, "value_b": str, ...}
#     — キー不問の値ルール: この列でこの値の組の差異は全行で既知(一括登録用)

def load_known_diffs(*, directory: Path | None = None) -> list[dict]:
    return _load_json(_data_dir(directory) / "known_diffs.json", [])


def add_known_diff(entry: dict, *, directory: Path | None = None) -> list[dict]:
    kind = entry.get("type")
    if kind == "cell":
        required = ("key", "col_a", "value_a", "value_b")
    elif kind == "row":
        required = ("key", "status")
        if entry.get("status") not in ("only_a", "only_b"):
            raise DiffDeskError("既知差分(行)のstatusは only_a / only_b のみです。")
    elif kind == "value":
        required = ("col_a", "value_a", "value_b")
    else:
        raise DiffDeskError(f"既知差分のtypeが不正です: {kind}(cell / row / value)")
    for f in required:
        if f not in entry:
            raise DiffDeskError(f"既知差分に {f} がありません。")
    entries = load_known_diffs(directory=directory)
    normalized = {k: entry[k] for k in ("type", *required)}
    if "key" in normalized:
        normalized["key"] = [str(k) for k in entry["key"]]
    if any({f: e.get(f) for f in normalized} == normalized for e in entries):
        return entries  # 重複登録は無視
    normalized["note"] = str(entry.get("note", ""))
    normalized["added_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    entries.append(normalized)
    _save_json(_data_dir(directory) / "known_diffs.json", entries)
    return entries


def remove_known_diff(index: int, *, directory: Path | None = None) -> list[dict]:
    entries = load_known_diffs(directory=directory)
    if 0 <= index < len(entries):
        entries.pop(index)
        _save_json(_data_dir(directory) / "known_diffs.json", entries)
    return entries


def clear_known_diffs(*, directory: Path | None = None) -> None:
    _save_json(_data_dir(directory) / "known_diffs.json", [])


# ---------------------------------------------------------------- 照合履歴
def append_history(record: dict, *, directory: Path | None = None) -> None:
    path = _data_dir(directory) / "history.json"
    history = _load_json(path, [])
    record = dict(record)
    record["at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    history.append(record)
    _save_json(path, history[-_HISTORY_LIMIT:])


def load_history(*, limit: int = 100, directory: Path | None = None) -> list[dict]:
    history = _load_json(_data_dir(directory) / "history.json", [])
    return history[-limit:][::-1]  # 新しい順


def clear_history(*, directory: Path | None = None) -> None:
    _save_json(_data_dir(directory) / "history.json", [])


# ---------------------------------------------------------------- 手動紐づけ
# 形式: {"key_a": [...], "key_b": [...], "note": str, "score": float|None,
#        "added_at": iso8601}
# キーの組で保存するため、同じファイルで差分を再実行しても自動で再適用される。

def load_manual_links(*, directory: Path | None = None) -> list[dict]:
    return _load_json(_data_dir(directory) / "manual_links.json", [])


def add_manual_link(entry: dict, *, directory: Path | None = None) -> list[dict]:
    key_a = entry.get("key_a")
    key_b = entry.get("key_b")
    for name, key in (("key_a", key_a), ("key_b", key_b)):
        if not isinstance(key, list) or not key:
            raise DiffDeskError(f"手動紐づけの {name} は文字列のリストで指定してください。")
    key_a = [str(k) for k in key_a]
    key_b = [str(k) for k in key_b]
    entries = load_manual_links(directory=directory)
    if any(e["key_a"] == key_a and e["key_b"] == key_b for e in entries):
        return entries  # 重複登録は無視
    score = entry.get("score")
    entries.append({
        "key_a": key_a, "key_b": key_b,
        "note": str(entry.get("note", ""))[:500],
        "score": round(float(score), 3) if isinstance(score, (int, float)) else None,
        "added_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    _save_json(_data_dir(directory) / "manual_links.json", entries)
    return entries


def remove_manual_link(index: int, *, directory: Path | None = None) -> list[dict]:
    entries = load_manual_links(directory=directory)
    if 0 <= index < len(entries):
        entries.pop(index)
        _save_json(_data_dir(directory) / "manual_links.json", entries)
    return entries


def clear_manual_links(*, directory: Path | None = None) -> None:
    _save_json(_data_dir(directory) / "manual_links.json", [])


# ---------------------------------------------------------------- ユーザー辞書
# 形式: [{"col_a": "検体番号", "col_b": "SampleNo__c"}, ...]

def load_user_dict(*, directory: Path | None = None) -> list[dict]:
    return _load_json(_data_dir(directory) / "user_dict.json", [])


def add_user_pairs(pairs: list[dict], *, directory: Path | None = None) -> list[dict]:
    entries = load_user_dict(directory=directory)
    existing = {(e["col_a"], e["col_b"]) for e in entries}
    added = 0
    for p in pairs:
        a, b = str(p.get("col_a", "")).strip(), str(p.get("col_b", "")).strip()
        if a and b and (a, b) not in existing:
            entries.append({"col_a": a, "col_b": b})
            existing.add((a, b))
            added += 1
    if added:
        _save_json(_data_dir(directory) / "user_dict.json", entries)
    return entries


def remove_user_pair(index: int, *, directory: Path | None = None) -> list[dict]:
    entries = load_user_dict(directory=directory)
    if 0 <= index < len(entries):
        entries.pop(index)
        _save_json(_data_dir(directory) / "user_dict.json", entries)
    return entries
