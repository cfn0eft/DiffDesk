"""ワークスペースの永続データ(既知差分・照合履歴・ユーザー辞書・手動紐づけ)。

保存先: 現在の案件のデータフォルダ(既定案件は ~/.diffdesk/ 直下、
その他は ~/.diffdesk/projects/<案件名>/)。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import project as _project
from .model import DiffDeskError

_HISTORY_LIMIT = 500
_UNDO_LIMIT = 30


def _data_dir(directory: Path | None = None) -> Path:
    d = directory or _project.data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------- 統一アンドゥ
# 変更前のファイル内容を undo.json に積み、「元に戻す」で1操作分を復元する。
# 対象: 既知差分・手動紐づけ・ユーザー辞書の追加/削除/全削除。

def _record_undo(directory: Path | None, label: str, filename: str) -> None:
    d = _data_dir(directory)
    path = d / "undo.json"
    stack = _load_json(path, [])
    target = d / filename
    stack.append({
        "label": label,
        "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "file": filename,
        "before": target.read_text(encoding="utf-8") if target.exists() else None,
    })
    _save_json(path, stack[-_UNDO_LIMIT:])


def peek_undo(*, directory: Path | None = None) -> dict:
    stack = _load_json(_data_dir(directory) / "undo.json", [])
    last = stack[-1] if stack else None
    return {"count": len(stack),
            "label": last["label"] if last else None,
            "at": last["at"] if last else None}


def undo_last(*, directory: Path | None = None) -> str:
    """直前の操作を取り消し、その操作のラベルを返す。"""
    d = _data_dir(directory)
    path = d / "undo.json"
    stack = _load_json(path, [])
    if not stack:
        raise DiffDeskError("元に戻せる操作がありません。")
    snap = stack.pop()
    target = d / snap["file"]
    if snap["before"] is None:
        target.unlink(missing_ok=True)
    else:
        target.write_text(snap["before"], encoding="utf-8")
    _save_json(path, stack)
    return snap["label"]


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
    kind_ja = {"cell": "セル", "row": "行", "value": "値ルール"}.get(kind, kind)
    _record_undo(directory, f"既知差分の追加({kind_ja})", "known_diffs.json")
    entries.append(normalized)
    _save_json(_data_dir(directory) / "known_diffs.json", entries)
    return entries


def add_known_diffs_bulk(new_entries: list[dict], label: str = "既知差分の一括登録",
                         *, directory: Path | None = None) -> int:
    """複数の既知差分を1操作として登録する(アンドゥ1回で全て戻る)。

    各エントリはadd_known_diffと同じ形式(検証もadd_known_diffに委譲したいが、
    アンドゥを1つにまとめるためここで直接追記する)。追加できた件数を返す。
    """
    entries = load_known_diffs(directory=directory)
    existing = [{k: e.get(k) for k in e if k not in ("note", "added_at")}
                for e in entries]
    added = 0
    recorded = False
    for entry in new_entries:
        kind = entry.get("type")
        required = {"cell": ("key", "col_a", "value_a", "value_b"),
                    "row": ("key", "status"),
                    "value": ("col_a", "value_a", "value_b")}.get(kind)
        if required is None or any(f not in entry for f in required):
            raise DiffDeskError(f"既知差分のエントリが不正です: {entry}")
        normalized = {k: entry[k] for k in ("type", *required)}
        if "key" in normalized:
            normalized["key"] = [str(k) for k in entry["key"]]
        if normalized in existing:
            continue
        if not recorded:
            _record_undo(directory, label, "known_diffs.json")
            recorded = True
        normalized["note"] = str(entry.get("note", ""))
        normalized["added_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        entries.append(normalized)
        existing.append({k: normalized[k] for k in normalized
                         if k not in ("note", "added_at")})
        added += 1
    if added:
        _save_json(_data_dir(directory) / "known_diffs.json", entries)
    return added


def remove_known_diff(index: int, *, directory: Path | None = None) -> list[dict]:
    entries = load_known_diffs(directory=directory)
    if 0 <= index < len(entries):
        _record_undo(directory, "既知差分の削除", "known_diffs.json")
        entries.pop(index)
        _save_json(_data_dir(directory) / "known_diffs.json", entries)
    return entries


def clear_known_diffs(*, directory: Path | None = None) -> None:
    _record_undo(directory, "既知差分の全削除", "known_diffs.json")
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
    _record_undo(directory, "手動紐づけの追加", "manual_links.json")
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
        _record_undo(directory, "手動紐づけの削除", "manual_links.json")
        entries.pop(index)
        _save_json(_data_dir(directory) / "manual_links.json", entries)
    return entries


def clear_manual_links(*, directory: Path | None = None) -> None:
    _record_undo(directory, "手動紐づけの全削除", "manual_links.json")
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
        _record_undo(directory, f"ユーザー辞書への追加({added}組)", "user_dict.json")
        _save_json(_data_dir(directory) / "user_dict.json", entries)
    return entries


def remove_user_pair(index: int, *, directory: Path | None = None) -> list[dict]:
    entries = load_user_dict(directory=directory)
    if 0 <= index < len(entries):
        _record_undo(directory, "ユーザー辞書の削除", "user_dict.json")
        entries.pop(index)
        _save_json(_data_dir(directory) / "user_dict.json", entries)
    return entries


# ---------------------------------------------------------------- 注釈(レビューメモ)
# 形式: [{"key": [...], "text": str, "added_at", "updated_at"}]
# 行キー基準なので、同じファイルで差分を再実行してもメモは残る。

def load_notes(*, directory: Path | None = None) -> list[dict]:
    return _load_json(_data_dir(directory) / "notes.json", [])


def set_note(key: list, text: str, *, directory: Path | None = None) -> list[dict]:
    """行キーへのメモを設定する(textが空なら削除)。"""
    if not isinstance(key, list) or not key:
        raise DiffDeskError("注釈のkeyは文字列のリストで指定してください。")
    key = [str(k) for k in key]
    text = str(text).strip()[:1000]
    entries = load_notes(directory=directory)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    existing = next((e for e in entries if e["key"] == key), None)
    if text == "":
        if existing is None:
            return entries
        _record_undo(directory, "注釈の削除", "notes.json")
        entries.remove(existing)
    elif existing is None:
        _record_undo(directory, "注釈の追加", "notes.json")
        entries.append({"key": key, "text": text,
                        "added_at": now, "updated_at": now})
    else:
        if existing["text"] == text:
            return entries
        _record_undo(directory, "注釈の変更", "notes.json")
        existing["text"] = text
        existing["updated_at"] = now
    _save_json(_data_dir(directory) / "notes.json", entries)
    return entries


def clear_notes(*, directory: Path | None = None) -> None:
    _record_undo(directory, "注釈の全削除", "notes.json")
    _save_json(_data_dir(directory) / "notes.json", [])
