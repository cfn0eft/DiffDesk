"""インメモリセッションストア(シングルユーザーのローカルツール用)。"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field

from ..core import DiffDeskError, DiffResult, Table

MAX_FILE_BYTES = 100 * 1024 * 1024  # 100MB


@dataclass
class FileEntry:
    file_id: str
    filename: str
    raw: bytes
    table: Table | None = None
    parse_params: dict = field(default_factory=dict)
    ops: list = field(default_factory=list)  # 適用した整形操作の履歴(レシピ用)


class SessionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._files: dict[str, FileEntry] = {}
        self._diffs: dict[str, DiffResult] = {}
        self._manual_pairs: dict[str, list[dict]] = {}  # diff_id -> 手動紐づけ

    # ---- files
    def add_file(self, filename: str, raw: bytes) -> FileEntry:
        if len(raw) > MAX_FILE_BYTES:
            raise DiffDeskError(
                f"ファイルが大きすぎます({len(raw) // (1024 * 1024)}MB)。上限は100MBです。")
        entry = FileEntry(file_id=uuid.uuid4().hex[:12], filename=filename, raw=raw)
        with self._lock:
            self._files[entry.file_id] = entry
        return entry

    def get_file(self, file_id: str) -> FileEntry:
        entry = self._files.get(file_id)
        if entry is None:
            raise DiffDeskError(f"ファイルが見つかりません(再アップロードしてください): {file_id}")
        return entry

    def get_table(self, file_id: str) -> Table:
        entry = self.get_file(file_id)
        if entry.table is None:
            raise DiffDeskError("ファイルが未パースです。先に読み込み設定を確定してください。")
        return entry.table

    def set_table(self, file_id: str, table: Table, params: dict | None = None) -> None:
        entry = self.get_file(file_id)
        with self._lock:
            entry.table = table
            if params is not None:
                entry.parse_params = params

    def add_table_as_file(self, filename: str, table: Table) -> FileEntry:
        """生成されたTable(結合結果・マージ結果等)を新しいファイルとして登録。"""
        entry = FileEntry(file_id=uuid.uuid4().hex[:12], filename=filename,
                          raw=b"", table=table)
        with self._lock:
            self._files[entry.file_id] = entry
        return entry

    def log_op(self, file_id: str, op: str, params: dict) -> None:
        """整形操作をファイルの履歴に記録する(レシピとして保存・再適用できる)。"""
        entry = self.get_file(file_id)
        with self._lock:
            entry.ops.append({"op": op, "params": params})

    def delete_file(self, file_id: str) -> None:
        with self._lock:
            self._files.pop(file_id, None)

    def list_files(self) -> list[FileEntry]:
        return list(self._files.values())

    MAX_DIFFS = 5  # 大規模データでのメモリ肥大防止(古い差分結果から破棄)

    # ---- diffs
    def add_diff(self, result: DiffResult) -> str:
        diff_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._diffs[diff_id] = result
            while len(self._diffs) > self.MAX_DIFFS:
                self._diffs.pop(next(iter(self._diffs)))
            for stale in set(self._manual_pairs) - set(self._diffs):
                self._manual_pairs.pop(stale, None)
        return diff_id

    def get_diff(self, diff_id: str) -> DiffResult:
        result = self._diffs.get(diff_id)
        if result is None:
            raise DiffDeskError(f"差分結果が見つかりません(再実行してください): {diff_id}")
        return result

    # ---- 手動紐づけ(差分結果ごと)
    def get_manual_pairs(self, diff_id: str) -> list[dict]:
        return list(self._manual_pairs.get(diff_id, []))

    def add_manual_pair(self, diff_id: str, pair: dict) -> list[dict]:
        self.get_diff(diff_id)  # 存在確認
        with self._lock:
            pairs = self._manual_pairs.setdefault(diff_id, [])
            if pair not in pairs:
                pairs.append(pair)
            return list(pairs)

    def remove_manual_pair(self, diff_id: str, index: int) -> list[dict]:
        with self._lock:
            pairs = self._manual_pairs.get(diff_id, [])
            if not 0 <= index < len(pairs):
                raise DiffDeskError(f"手動紐づけの番号が不正です: {index}")
            pairs.pop(index)
            return list(pairs)

    def clear_manual_pairs(self, diff_id: str) -> None:
        with self._lock:
            self._manual_pairs.pop(diff_id, None)


store = SessionStore()
