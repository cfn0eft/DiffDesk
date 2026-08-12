"""参照整合性チェック(汎用ルックアップ検証)。

「このファイルのこの列の値は、マスタ側のあの列に存在するか」を検証し、
Data Loaderの参照エラー(参照先が見つかりません)を投入前に予防する。
"""
from __future__ import annotations

import unicodedata

from .model import Table

_MAX_MISSING_VALUES = 50


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).strip()


def ref_check(child: Table, child_col: str, master: Table, master_col: str) -> dict:
    """childのchild_col の値が masterのmaster_col に存在するか検証する。

    比較は空白除去+全半角同一視(NFKC)で行う。空欄は別集計。
    """
    ci = child.col_index(child_col)
    mi = master.col_index(master_col)
    master_values = {_norm(row[mi]) for row in master.rows} - {""}

    matched = blank = 0
    missing_rows: list[int] = []
    missing_values: dict[str, int] = {}
    for idx, row in enumerate(child.rows):
        v = _norm(row[ci])
        if v == "":
            blank += 1
        elif v in master_values:
            matched += 1
        else:
            missing_rows.append(idx)
            missing_values[row[ci]] = missing_values.get(row[ci], 0) + 1

    top_missing = sorted(missing_values.items(), key=lambda kv: -kv[1])
    return {
        "total": len(child.rows),
        "matched": matched,
        "blank": blank,
        "missing": len(missing_rows),
        "missing_values": [{"value": v, "count": n}
                           for v, n in top_missing[:_MAX_MISSING_VALUES]],
        "distinct_missing": len(missing_values),
        "master_values": len(master_values),
        "_missing_rows": missing_rows,  # 内部用(行テーブル生成)
    }


def missing_rows_table(child: Table, child_col: str,
                       master: Table, master_col: str) -> Table:
    """参照先が見つからない行だけのテーブル(全列+理由列)。"""
    result = ref_check(child, child_col, master, master_col)
    rows = [list(child.rows[i]) + [f"{child_col}={child.rows[i][child.col_index(child_col)]} がマスタにありません"]
            for i in result["_missing_rows"]]
    return Table(columns=list(child.columns) + ["エラー理由"],
                 rows=rows, name="参照エラー行")
