"""クロス集計(群構成チェック等)。

例: 投与群 × 性別 の個体数クロス表 → 「各群n=5♂5♀か」を一目で確認。
"""
from __future__ import annotations

from collections import Counter

from .model import Table


def crosstab(table: Table, row_col: str, col_col: str | None = None) -> Table:
    """クロス集計表を返す。col_col省略時は単純な度数集計。"""
    ri = table.col_index(row_col)
    if col_col is None:
        counter = Counter((row[ri] or "(空)") for row in table.rows)
        rows = [[k, str(v)] for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))]
        rows.append(["(合計)", str(len(table.rows))])
        return Table(columns=[row_col, "件数"], rows=rows, name="集計")

    ci = table.col_index(col_col)
    counter: Counter[tuple[str, str]] = Counter()
    for row in table.rows:
        counter[(row[ri] or "(空)", row[ci] or "(空)")] += 1
    row_keys = sorted({k[0] for k in counter})
    col_keys = sorted({k[1] for k in counter})
    columns = [f"{row_col}\\{col_col}"] + col_keys + ["(合計)"]
    rows = []
    col_totals = Counter()
    for rk in row_keys:
        line = [rk]
        total = 0
        for ck in col_keys:
            n = counter.get((rk, ck), 0)
            line.append(str(n) if n else "")
            total += n
            col_totals[ck] += n
        line.append(str(total))
        rows.append(line)
    rows.append(["(合計)"] + [str(col_totals[ck]) for ck in col_keys] + [str(len(table.rows))])
    return Table(columns=columns, rows=rows, name="クロス集計")
