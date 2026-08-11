"""既知差分の適用: 「確認済み・問題なし」と登録された差異を照合結果から除外する。

毎回の照合で同じ差異を見直す無駄をなくし、「新しい差異ゼロ」を合格条件にできる。
元のDiffResultは変更せず、注釈付きの新しいDiffResultを返す。
"""
from __future__ import annotations

from .model import DiffResult, RowDiff


def apply_known_diffs(diff: DiffResult, entries: list[dict]) -> DiffResult:
    """既知差分エントリを適用したDiffResultを返す。

    - cell型: 一致するセル差分を known_diffs へ移動。全セル差分が既知になった行は
      status="same"・known=True(照合合格扱い)になる。
    - row型: only_a / only_b の該当行に known=True を付ける(欠落の容認)。
    """
    if not entries:
        return diff
    cell_set = {(tuple(e["key"]), e["col_a"], e["value_a"], e["value_b"])
                for e in entries if e.get("type") == "cell"}
    row_set = {(tuple(e["key"]), e["status"])
               for e in entries if e.get("type") == "row"}

    rows: list[RowDiff] = []
    for rd in diff.rows:
        if rd.status in ("only_a", "only_b") and (rd.key, rd.status) in row_set:
            rows.append(RowDiff(key=rd.key, status=rd.status, row_a=rd.row_a,
                                row_b=rd.row_b, known=True))
            continue
        if rd.status == "changed" and cell_set:
            known = [cd for cd in rd.cell_diffs
                     if (rd.key, cd.col_a, cd.value_a, cd.value_b) in cell_set]
            if known:
                remaining = [cd for cd in rd.cell_diffs if cd not in known]
                status = "changed" if remaining else "same"
                rows.append(RowDiff(key=rd.key, status=status, row_a=rd.row_a,
                                    row_b=rd.row_b, cell_diffs=remaining,
                                    known=not remaining, known_diffs=known,
                                    manual=rd.manual, key_b=rd.key_b))
                continue
        rows.append(rd)

    return DiffResult(
        mapping=diff.mapping, options=diff.options, rows=rows,
        duplicates_a=diff.duplicates_a, duplicates_b=diff.duplicates_b,
        empty_key_a=diff.empty_key_a, empty_key_b=diff.empty_key_b,
        name_a=diff.name_a, name_b=diff.name_b,
    )


def column_diff_summary(diff: DiffResult, *, limit: int = 30) -> list[dict]:
    """列(A側名)ごとの差異件数ランキングを返す(既知除外後のcell_diffsを使用)。"""
    counts: dict[str, int] = {}
    for rd in diff.rows:
        for cd in rd.cell_diffs:
            counts[cd.col_a] = counts.get(cd.col_a, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])[:limit]
    return [{"column": c, "count": n} for c, n in ranked]
