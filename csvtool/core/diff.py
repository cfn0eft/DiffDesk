"""キー結合ベースの差分エンジンと行フィルタ。"""
from __future__ import annotations

import re

from .model import (
    CellDiff,
    CsvToolError,
    DiffOptions,
    DiffResult,
    FilterCondition,
    MappingConfig,
    RowDiff,
    RowFilter,
    Table,
)
from .normalize import make_normalizer, values_equal


def _match_condition(value: str, cond: FilterCondition) -> bool:
    v, target = value, cond.value
    if cond.op == "eq":
        return v == target
    if cond.op == "ne":
        return v != target
    if cond.op == "contains":
        return target in v
    if cond.op == "not_contains":
        return target not in v
    if cond.op == "starts_with":
        return v.startswith(target)
    if cond.op == "ends_with":
        return v.endswith(target)
    if cond.op == "empty":
        return v.strip() == ""
    if cond.op == "not_empty":
        return v.strip() != ""
    if cond.op == "regex":
        try:
            return re.search(target, v) is not None
        except re.error as e:
            raise CsvToolError(f"正規表現が不正です: {target} ({e})", pattern=target)
    raise CsvToolError(f"不明なフィルタ条件です: {cond.op}", op=cond.op)


def apply_filter(table: Table, conditions: list[FilterCondition]) -> Table:
    """条件(AND)に合致する行のみ残したTableを返す。条件が空ならそのまま。"""
    if not conditions:
        return table
    idx = {c.column: table.col_index(c.column) for c in conditions}
    kept = [row for row in table.rows
            if all(_match_condition(row[idx[c.column]], c) for c in conditions)]
    out = table.copy()
    out.rows = kept
    return out


def _project(table: Table, columns: list[str]) -> list[list[str]]:
    indices = [table.col_index(c) for c in columns]
    return [[row[i] for i in indices] for row in table.rows]


def diff_tables(table_a: Table, table_b: Table, mapping: MappingConfig,
                options: DiffOptions | None = None,
                row_filter: RowFilter | None = None) -> DiffResult:
    """A・Bをマッピングに従ってキー結合し差分を分類する。O(n+m)。

    - 重複キー(同一正規化キーが2回以上出現)の行は照合から除外し、警告として報告。
    - キーが全て空の行も除外して件数を報告。
    - rows の順序: Aの行順(only_a/changed/same) → Bのみの行(B順)。
    """
    options = options or DiffOptions()
    if row_filter is not None:
        table_a = apply_filter(table_a, row_filter.conditions_a)
        table_b = apply_filter(table_b, row_filter.conditions_b)
    mapping.validate(table_a.columns, table_b.columns)

    normalizer = make_normalizer(options)
    cols_a = [p.col_a for p in mapping.pairs]
    cols_b = [p.col_b for p in mapping.pairs]
    key_idx = [i for i, p in enumerate(mapping.pairs) if p.is_key]
    val_idx = [i for i, p in enumerate(mapping.pairs) if not p.is_key]

    proj_a = _project(table_a, cols_a)
    proj_b = _project(table_b, cols_b)

    def build_index(rows: list[list[str]]):
        index: dict[tuple[str, ...], list[int]] = {}
        empty = 0
        for i, row in enumerate(rows):
            key = tuple(normalizer(row[k]) for k in key_idx)
            if all(v == "" for v in key):
                empty += 1
                continue
            index.setdefault(key, []).append(i)
        dups = sorted(k for k, v in index.items() if len(v) > 1)
        uniq = {k: v[0] for k, v in index.items() if len(v) == 1}
        return uniq, dups, empty

    uniq_a, dups_a, empty_a = build_index(proj_a)
    uniq_b, dups_b, empty_b = build_index(proj_b)

    rows: list[RowDiff] = []
    matched_b_keys: set[tuple[str, ...]] = set()

    order_a = sorted(uniq_a.items(), key=lambda kv: kv[1])
    for key, ia in order_a:
        row_a = proj_a[ia]
        if key in uniq_b:
            matched_b_keys.add(key)
            row_b = proj_b[uniq_b[key]]
            cell_diffs = []
            for vi in val_idx:
                if not values_equal(row_a[vi], row_b[vi], normalizer,
                                    options.numeric_tolerance):
                    cell_diffs.append(CellDiff(
                        col_a=cols_a[vi], col_b=cols_b[vi],
                        value_a=row_a[vi], value_b=row_b[vi],
                    ))
            status = "changed" if cell_diffs else "same"
            rows.append(RowDiff(key=key, status=status, row_a=row_a,
                                row_b=row_b, cell_diffs=cell_diffs))
        else:
            rows.append(RowDiff(key=key, status="only_a", row_a=row_a, row_b=None))

    order_b = sorted(uniq_b.items(), key=lambda kv: kv[1])
    for key, ib in order_b:
        if key not in matched_b_keys:
            rows.append(RowDiff(key=key, status="only_b", row_a=None,
                                row_b=proj_b[ib]))

    return DiffResult(
        mapping=mapping, options=options, rows=rows,
        duplicates_a=dups_a, duplicates_b=dups_b,
        empty_key_a=empty_a, empty_key_b=empty_b,
        name_a=table_a.name, name_b=table_b.name,
    )
