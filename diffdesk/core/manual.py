"""手動紐づけ: Aのみ行とBのみ行をユーザー操作でペアにする。

キーが一致しなかったレコード同士(例: 移行でIDが振り直された、キーの表記が
違う)を「同じレコード」として突き合わせたいときに使う。ペアにした行は
全列(キー列含む)を比較し、changed/same の通常行として扱われる。
元の DiffResult は変更せず、適用済みのコピーを返す。
"""
from __future__ import annotations

from dataclasses import replace

from .model import CellDiff, DiffDeskError, DiffResult, RowDiff
from .normalize import make_normalizer, values_equal


def validate_manual_pair(pair: dict) -> dict:
    """{"key_a": [...], "key_b": [...]} を検証して正規形にする。"""
    key_a = pair.get("key_a")
    key_b = pair.get("key_b")
    if (not isinstance(key_a, list) or not key_a
            or not all(isinstance(v, str) for v in key_a)):
        raise DiffDeskError("key_a は文字列のリストで指定してください。")
    if (not isinstance(key_b, list) or not key_b
            or not all(isinstance(v, str) for v in key_b)):
        raise DiffDeskError("key_b は文字列のリストで指定してください。")
    return {"key_a": list(key_a), "key_b": list(key_b)}


def apply_manual_pairs(diff: DiffResult, pairs: list[dict]) -> DiffResult:
    """手動ペアを適用したDiffResultのコピーを返す。

    各ペアの key_a に一致する only_a 行と key_b に一致する only_b 行を
    1件のペア行(manual=True)に統合する。該当行が見つからないペアは無視
    (差分の再実行で行が消えた場合など)。
    """
    if not pairs:
        return diff
    normalizer = make_normalizer(diff.options)
    cols_a = [p.col_a for p in diff.mapping.pairs]
    cols_b = [p.col_b for p in diff.mapping.pairs]

    by_key_a = {r.key: r for r in diff.rows if r.status == "only_a"}
    by_key_b = {r.key: r for r in diff.rows if r.status == "only_b"}
    merged: dict[tuple[str, ...], RowDiff] = {}  # key_a -> ペア行
    consumed_b: set[tuple[str, ...]] = set()

    for p in pairs:
        ka, kb = tuple(p["key_a"]), tuple(p["key_b"])
        ra, rb = by_key_a.get(ka), by_key_b.get(kb)
        if ra is None or rb is None or ka in merged or kb in consumed_b:
            continue
        cell_diffs = [
            CellDiff(col_a=cols_a[i], col_b=cols_b[i],
                     value_a=ra.row_a[i], value_b=rb.row_b[i])
            for i in range(len(cols_a))
            if not values_equal(ra.row_a[i], rb.row_b[i], normalizer,
                                diff.options.numeric_tolerance)
        ]
        merged[ka] = RowDiff(
            key=ka, status="changed" if cell_diffs else "same",
            row_a=ra.row_a, row_b=rb.row_b, cell_diffs=cell_diffs,
            manual=True, key_b=kb,
        )
        consumed_b.add(kb)

    if not merged:
        return diff

    rows: list[RowDiff] = []
    for r in diff.rows:
        if r.status == "only_a" and r.key in merged:
            rows.append(merged[r.key])
        elif r.status == "only_b" and r.key in consumed_b:
            continue
        else:
            rows.append(r)
    return replace(diff, rows=rows)


def list_unmatched(diff: DiffResult, side: str, limit: int = 1000) -> list[dict]:
    """紐づけ相手の候補(未対応の only_a / only_b 行)を返す。

    side="a" なら only_a 行、side="b" なら only_b 行。既知(容認済み)の行は除く。
    各要素は {"key": [...], "label": "キー | 先頭の値…"}。
    """
    if side not in ("a", "b"):
        raise DiffDeskError("side は a または b を指定してください。")
    status = f"only_{side}"
    key_flags = [p.is_key for p in diff.mapping.pairs]
    out = []
    for r in diff.rows:
        if r.status != status or r.known:
            continue
        vals = r.row_a if side == "a" else r.row_b
        preview = [v for f, v in zip(key_flags, vals) if not f and v][:2]
        label = " / ".join(r.key)
        if preview:
            label += " | " + "、".join(x[:20] for x in preview)
        out.append({"key": list(r.key), "label": label})
        if len(out) >= limit:
            break
    return out
