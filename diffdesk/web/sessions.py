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


class SessionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._files: dict[str, FileEntry] = {}
        self._diffs: dict[str, DiffResult] = {}

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

    def delete_file(self, file_id: str) -> None:
        with self._lock:
            self._files.pop(file_id, None)

    def list_files(self) -> list[FileEntry]:
        return list(self._files.values())

    # ---- diffs
    def add_diff(self, result: DiffResult) -> str:
        diff_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._diffs[diff_id] = result
        return diff_id

    def get_diff(self, diff_id: str) -> DiffResult:
        result = self._diffs.get(diff_id)
        if result is None:
            raise DiffDeskError(f"差分結果が見つかりません(再実行してください): {diff_id}")
        return result


store = SessionStore()
