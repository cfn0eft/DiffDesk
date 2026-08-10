"""Tableへの編集操作。webに依存せず単体で利用可能。"""
from __future__ import annotations

import re

from .model import CsvToolError, Table


def set_cell(table: Table, row: int, col: int, value: str) -> Table:
    if not (0 <= row < len(table.rows)) or not (0 <= col < len(table.columns)):
        raise CsvToolError(f"セル位置が範囲外です: 行{row + 1} 列{col + 1}")
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
        raise CsvToolError(f"列名が重複しています: {name}", column=name)
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
        raise CsvToolError("新しい列名が空です。")
    if new != old and new in table.columns:
        raise CsvToolError(f"列名が重複しています: {new}", column=new)
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
            raise CsvToolError(f"正規表現が不正です: {query} ({e})", pattern=query)
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
            raise CsvToolError(f"正規表現が不正です: {query} ({e})", pattern=query)
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
