"""3ファイル比較(多段トレース)。

原本(A) → 加工済み(M) → 最終(B) の3ファイルを同じキーで突き合わせ、
値が「どの段階で変わったか」を特定する。列は名前(全半角・大小文字ゆれ吸収)で
3ファイル共通のものを自動対応させる。
"""
from __future__ import annotations

import unicodedata

from .model import DiffDeskError, DiffOptions, Table
from .normalize import make_normalizer

_MAX_ROWS = 1000

STAGE_JA = {
    "a_m": "A→M(加工時に変化)",
    "m_b": "M→B(投入時に変化)",
    "both": "両段階で変化",
    "revert": "Mだけ異なる(A=B)",
}


def _norm_name(s: str) -> str:
    return unicodedata.normalize("NFKC", s).casefold().strip()


def _index(table: Table, key_col: str, normalizer) -> tuple[dict, int, int]:
    """キー→行のマップ(初出のみ)。重複・空キーの件数も返す。"""
    ki = table.col_index(key_col)
    index: dict[str, list[str]] = {}
    dup = empty = 0
    for row in table.rows:
        k = normalizer(row[ki])
        if k == "":
            empty += 1
            continue
        if k in index:
            dup += 1
            continue
        index[k] = row
    return index, dup, empty


def trace_diff(a: Table, key_a: str, m: Table, key_m: str,
               b: Table, key_b: str,
               options: DiffOptions | None = None) -> dict:
    """3ファイルを突き合わせ、変化した段階を分類する。"""
    normalizer = make_normalizer(options or DiffOptions())

    # 3ファイル共通の列(名前ゆれ吸収)。キー列は除外
    def colmap(t: Table) -> dict[str, str]:
        return {_norm_name(c): c for c in t.columns}
    ca, cm, cb = colmap(a), colmap(m), colmap(b)
    excl = {_norm_name(key_a), _norm_name(key_m), _norm_name(key_b)}
    common = [n for n in (_norm_name(c) for c in a.columns)
              if n in cm and n in cb and n not in excl]
    if not common:
        raise DiffDeskError("3ファイルに共通する列(キー以外)がありません。列名を確認してください。")

    ia, dup_a, empty_a = _index(a, key_a, normalizer)
    im, dup_m, empty_m = _index(m, key_m, normalizer)
    ib, dup_b, empty_b = _index(b, key_b, normalizer)

    idx_a = {n: a.col_index(ca[n]) for n in common}
    idx_m = {n: m.col_index(cm[n]) for n in common}
    idx_b = {n: b.col_index(cb[n]) for n in common}

    rows = []
    by_stage: dict[str, int] = {}
    by_column: dict[str, int] = {}
    missing_m = missing_b = 0
    for key, row_a in ia.items():
        row_m = im.get(key)
        row_b = ib.get(key)
        if row_m is None:
            missing_m += 1
            continue
        if row_b is None:
            missing_b += 1
            continue
        for n in common:
            va, vm, vb = row_a[idx_a[n]], row_m[idx_m[n]], row_b[idx_b[n]]
            na, nm, nb = normalizer(va), normalizer(vm), normalizer(vb)
            if na == nm == nb:
                continue
            if na == nm:
                stage = "m_b"
            elif nm == nb:
                stage = "a_m"
            elif na == nb:
                stage = "revert"
            else:
                stage = "both"
            by_stage[stage] = by_stage.get(stage, 0) + 1
            col_label = ca[n]
            by_column[col_label] = by_column.get(col_label, 0) + 1
            rows.append({"key": key, "col": col_label,
                         "value_a": va, "value_m": vm, "value_b": vb,
                         "stage": stage, "stage_ja": STAGE_JA[stage]})

    return {
        "columns": [ca[n] for n in common],
        "keys_a": len(ia),
        "matched": len(ia) - missing_m - missing_b,
        "missing_m": missing_m,
        "missing_b": missing_b,
        "changed": len(rows),
        "by_stage": {s: by_stage.get(s, 0) for s in STAGE_JA},
        "by_column": by_column,
        "warnings": {
            "dup_a": dup_a, "dup_m": dup_m, "dup_b": dup_b,
            "empty_a": empty_a, "empty_m": empty_m, "empty_b": empty_b,
        },
        "rows": rows[:_MAX_ROWS],
        "rows_truncated": max(0, len(rows) - _MAX_ROWS),
        "_all_rows": rows,  # 内部用(CSV出力)
    }


def trace_table(result: dict) -> Table:
    """トレース結果のCSV出力用テーブル。"""
    rows = [[r["key"], r["col"], r["value_a"], r["value_m"], r["value_b"],
             r["stage_ja"]] for r in result.get("_all_rows", result.get("rows", []))]
    return Table(columns=["キー", "列", "原本(A)", "中間(M)", "最終(B)", "変化した段階"],
                 rows=rows, name="多段トレース")
