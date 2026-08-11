"""Tableへの編集操作。webに依存せず単体で利用可能。"""
from __future__ import annotations

import re

from .model import DiffDeskError, Table


def set_cell(table: Table, row: int, col: int, value: str) -> Table:
    if not (0 <= row < len(table.rows)) or not (0 <= col < len(table.columns)):
        raise DiffDeskError(f"セル位置が範囲外です: 行{row + 1} 列{col + 1}")
    table.rows[row][col] = str(value)
    return table


def insert_row(table: Table, at: int | None = None) -> Table:
    row = [""] * len(table.columns)
    if at is None or at >= len(table.rows):
        table.rows.append(row)
    else:
        table.rows.insert(max(at, 0), row)
    return table


def delete_rows(table: Table, indices: list[int]) -> Table:
    drop = set(indices)
    table.rows = [r for i, r in enumerate(table.rows) if i not in drop]
    return table


def insert_column(table: Table, name: str, at: int | None = None) -> Table:
    name = name.strip() or f"列{len(table.columns) + 1}"
    if name in table.columns:
        raise DiffDeskError(f"列名が重複しています: {name}", column=name)
    pos = len(table.columns) if at is None else min(max(at, 0), len(table.columns))
    table.columns.insert(pos, name)
    for row in table.rows:
        row.insert(pos, "")
    return table


def delete_column(table: Table, name: str) -> Table:
    i = table.col_index(name)
    table.columns.pop(i)
    for row in table.rows:
        row.pop(i)
    return table


def rename_column(table: Table, old: str, new: str) -> Table:
    new = new.strip()
    if not new:
        raise DiffDeskError("新しい列名が空です。")
    if new != old and new in table.columns:
        raise DiffDeskError(f"列名が重複しています: {new}", column=new)
    table.columns[table.col_index(old)] = new
    return table


def search_cells(table: Table, query: str, *, columns: list[str] | None = None,
                 regex: bool = False, case_sensitive: bool = True,
                 limit: int = 500) -> list[dict]:
    """該当セルの位置リスト [{row, col, column, value}] を返す。"""
    if not query:
        return []
    indices = ([table.col_index(c) for c in columns]
               if columns else list(range(len(table.columns))))
    if regex:
        try:
            pattern = re.compile(query, 0 if case_sensitive else re.IGNORECASE)
        except re.error as e:
            raise DiffDeskError(f"正規表現が不正です: {query} ({e})", pattern=query)
        match = lambda v: pattern.search(v) is not None
    elif case_sensitive:
        match = lambda v: query in v
    else:
        q = query.casefold()
        match = lambda v: q in v.casefold()
    hits = []
    for ri, row in enumerate(table.rows):
        for ci in indices:
            if match(row[ci]):
                hits.append({"row": ri, "col": ci,
                             "column": table.columns[ci], "value": row[ci]})
                if len(hits) >= limit:
                    return hits
    return hits


def replace_all(table: Table, query: str, replacement: str, *,
                columns: list[str] | None = None, regex: bool = False,
                case_sensitive: bool = True) -> tuple[Table, int]:
    """検索置換。置換したセル数を返す。"""
    if not query:
        return table, 0
    indices = ([table.col_index(c) for c in columns]
               if columns else list(range(len(table.columns))))
    if regex:
        try:
            pattern = re.compile(query, 0 if case_sensitive else re.IGNORECASE)
        except re.error as e:
            raise DiffDeskError(f"正規表現が不正です: {query} ({e})", pattern=query)
        replace = lambda v: pattern.sub(replacement, v)
    elif case_sensitive:
        replace = lambda v: v.replace(query, replacement)
    else:
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        replace = lambda v: pattern.sub(replacement.replace("\\", "\\\\"), v)
    count = 0
    for row in table.rows:
        for ci in indices:
            new = replace(row[ci])
            if new != row[ci]:
                row[ci] = new
                count += 1
    return table, count


def split_column(table: Table, column: str, delimiter: str,
                 *, max_parts: int = 10) -> tuple[Table, int]:
    """列を区切り文字で分割し、「列名_1」「列名_2」…に置き換える(Power QueryのSplit Column相当)。

    分割数は実データの最大分割数(上限max_parts)。分割された列数を返す。
    """
    if not delimiter:
        raise DiffDeskError("区切り文字を指定してください。")
    i = table.col_index(column)
    n_parts = 1
    for row in table.rows:
        n = min(row[i].count(delimiter) + 1, max_parts)
        if n > n_parts:
            n_parts = n
    if n_parts == 1:
        raise DiffDeskError(
            f"区切り文字 {delimiter!r} が列「{column}」のどの値にも含まれていません。")
    new_names = []
    existing = set(table.columns) - {column}
    for k in range(1, n_parts + 1):
        name = f"{column}_{k}"
        while name in existing:
            name += "_x"
        existing.add(name)
        new_names.append(name)
    table.columns[i:i + 1] = new_names
    for row in table.rows:
        parts = row[i].split(delimiter, n_parts - 1)
        parts += [""] * (n_parts - len(parts))
        row[i:i + 1] = parts
    return table, n_parts


def _new_column_name(table: Table, name: str) -> str:
    name = name.strip()
    if not name:
        raise DiffDeskError("新しい列名を指定してください。")
    if name in table.columns:
        raise DiffDeskError(f"列名が重複しています: {name}", column=name)
    return name


def concat_columns(table: Table, columns: list[str], new_name: str,
                   separator: str = "") -> Table:
    """複数列を区切り文字で結合した新しい列を末尾に追加する。"""
    if len(columns) < 2:
        raise DiffDeskError("結合する列を2つ以上選択してください。")
    idx = [table.col_index(c) for c in columns]
    name = _new_column_name(table, new_name)
    table.columns.append(name)
    for row in table.rows:
        row.append(separator.join(row[i] for i in idx))
    return table


def substring_column(table: Table, column: str, new_name: str,
                     start: int = 1, length: int | None = None) -> Table:
    """列の一部を切り出した新しい列を末尾に追加する(startは1始まり)。"""
    if start < 1:
        raise DiffDeskError("開始位置は1以上で指定してください。")
    i = table.col_index(column)
    name = _new_column_name(table, new_name)
    table.columns.append(name)
    begin = start - 1
    end = None if length is None else begin + int(length)
    for row in table.rows:
        row.append(row[i][begin:end])
    return table


_COND_OPS = ("eq", "ne", "contains", "not_contains", "gte", "lte", "empty", "not_empty")


def conditional_column(table: Table, column: str, op: str, value: str,
                       new_name: str, then_value: str, else_value: str) -> Table:
    """条件分岐(IF)で新しい列を末尾に追加する。

    then/else の値に「{値}」と書くと元の列の値がそのまま入る。
    """
    if op not in _COND_OPS:
        raise DiffDeskError(f"不明な条件です: {op}", op=op)
    i = table.col_index(column)
    name = _new_column_name(table, new_name)
    table.columns.append(name)

    def test(v: str) -> bool:
        if op == "eq":
            return v == value
        if op == "ne":
            return v != value
        if op == "contains":
            return value in v
        if op == "not_contains":
            return value not in v
        if op == "empty":
            return v.strip() == ""
        if op == "not_empty":
            return v.strip() != ""
        try:  # gte / lte
            n, target = float(v), float(value)
        except ValueError:
            return False
        return n >= target if op == "gte" else n <= target

    for row in table.rows:
        v = row[i]
        out = then_value if test(v) else else_value
        row.append(out.replace("{値}", v))
    return table


def dedupe_rows(table: Table) -> tuple[Table, int]:
    """完全一致の重複行を削除し、削除件数を返す(最初の1件を残す)。"""
    seen: set[tuple[str, ...]] = set()
    kept = []
    for row in table.rows:
        key = tuple(row)
        if key not in seen:
            seen.add(key)
            kept.append(row)
    removed = len(table.rows) - len(kept)
    table.rows = kept
    return table, removed
