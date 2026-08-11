"""投入ロールバックキット: アップサート投入の「取り消し」用CSV生成。

- 復元用CSV: 投入前のSalesforce側の値(B)をそのままupdate用に出力。
  アップサートで上書きした変更を、投入前の状態に戻せる。
- 取り消し用delete CSV: Data Loaderのsuccess.csv(insert結果)から
  新規作成されたレコードのIdを抜き出し、Delete操作用CSVを作る。
"""
from __future__ import annotations

from .model import DiffDeskError, DiffResult, Table

_SUCCESS_ID_NAMES = ("id", "sf_id")
_SUCCESS_STATUS_NAMES = ("status", "ステータス")
_CREATED_MARKERS = ("created", "作成")


def build_restore_table(diff: DiffResult) -> Table:
    """変更(changed)行について、投入前のB側の値を復元用update CSVとして返す。

    ヘッダーはアップサートCSVと同じ(sf_field優先)。値はBの現状値。
    アップサート投入前に出力しておけば、投入後にこのCSVをupdateすることで
    上書きした値を元に戻せる。
    """
    headers = [p.output_field for p in diff.mapping.pairs]
    if len(set(headers)) != len(headers):
        raise DiffDeskError("出力ヘッダー(Salesforce項目名)が重複しています。")
    rows = [list(rd.row_b) for rd in diff.rows
            if rd.status == "changed" and rd.row_b is not None]
    if not rows:
        raise DiffDeskError("変更(update対象)行がないため、復元用CSVは不要です。")
    return Table(columns=headers, rows=rows, name="復元用(投入前のSF値)")


def find_success_id_column(table: Table) -> str | None:
    for c in table.columns:
        if c.strip().casefold() in _SUCCESS_ID_NAMES:
            return c
    return None


def build_undo_delete_table(success: Table) -> tuple[Table, int]:
    """success.csv から新規作成(insert)されたレコードの削除用CSVを作る。

    STATUS列に「Item Created」等の作成マーカーがある行のみ対象
    (update成功行を誤って削除しないため)。STATUS列が無い場合は全Id行を対象とし、
    呼び出し側で件数を確認できるよう総数も返す。
    戻り値: (削除用Table, 対象外にしたupdate行数)
    """
    id_col = find_success_id_column(success)
    if id_col is None:
        raise DiffDeskError(
            "ID列が見つかりません。Data Loaderのsuccessファイル"
            "(ID/STATUS列付き)を読み込んでください。",
            columns=success.columns[:10],
        )
    ii = success.col_index(id_col)
    status_idx = None
    for c in success.columns:
        if c.strip().casefold() in _SUCCESS_STATUS_NAMES:
            status_idx = success.col_index(c)
            break

    rows: list[list[str]] = []
    skipped_updates = 0
    for row in success.rows:
        rid = row[ii].strip()
        if not rid:
            continue
        if status_idx is not None:
            status = row[status_idx].casefold()
            if not any(m in status for m in _CREATED_MARKERS):
                skipped_updates += 1
                continue
        rows.append([rid])
    if not rows:
        raise DiffDeskError(
            "削除対象(新規作成されたレコード)が見つかりませんでした。"
            "insertを含む投入のsuccessファイルか確認してください。")
    return Table(columns=["Id"], rows=rows, name="取り消し用delete"), skipped_updates
