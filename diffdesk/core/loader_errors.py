"""Data Loader のエラーファイル(error.csv)分析と再投入用CSV生成。

Data Loader は投入後に success/error ファイルを出力する。error ファイルは
元の全列+「ERROR」列(失敗理由)という形式。ここでは:
- エラー理由をカテゴリ分類して集計する
- ERROR/STATUS 等の付加列を除いた「失敗行だけの再投入用CSV」を作る
"""
from __future__ import annotations

from dataclasses import dataclass

from .model import DiffDeskError, Table

# エラーコード(部分一致) → 日本語ラベルと対処ヒント
ERROR_CATEGORIES: list[tuple[str, str, str]] = [
    ("REQUIRED_FIELD_MISSING", "必須項目が未入力", "該当列の空欄を埋めてください"),
    ("FIELD_CUSTOM_VALIDATION_EXCEPTION", "入力規則違反", "Salesforce側の入力規則のメッセージを確認してください"),
    ("INVALID_OR_NULL_FOR_RESTRICTED_PICKLIST", "選択リストにない値", "許可値検証(検証パネル)で事前チェックできます"),
    ("DUPLICATE_VALUE", "重複値(外部ID等)", "キー重複チェックで事前検出できます"),
    ("DUPLICATES_DETECTED", "重複ルールで検出", "Salesforceの重複ルールに該当。既存レコードを確認してください"),
    ("UNABLE_TO_LOCK_ROW", "レコードロック競合", "時間を置いて再投入すれば解消することが多いエラーです"),
    ("STRING_TOO_LONG", "文字数超過", "検証パネルの最大文字数チェックで事前検出できます"),
    ("MALFORMED_ID", "ID形式が不正", "Id列の値(15桁/18桁)を確認してください"),
    ("INVALID_EMAIL_ADDRESS", "メール形式が不正", "検証パネルのメール形式チェックで事前検出できます"),
    ("INVALID_CROSS_REFERENCE_KEY", "参照先レコードが見つからない", "親レコードが先に投入されているか確認してください"),
    ("FIELD_INTEGRITY_EXCEPTION", "項目の整合性エラー", "項目型と値の組み合わせを確認してください"),
    ("INSUFFICIENT_ACCESS", "権限不足", "投入ユーザーのプロファイル権限を確認してください"),
    ("INVALID_TYPE_ON_FIELD_IN_RECORD", "項目の型と値が不一致", "日付・数値の形式を確認してください(クレンジングの日付統一が使えます)"),
]

_ERROR_COLUMN_NAMES = ("error", "エラー")
_DROP_COLUMNS = ("error", "エラー", "status", "ステータス")


@dataclass
class ErrorAnalysis:
    error_column: str
    total_rows: int
    categories: list[dict]  # {code, label, hint, count, example}

    def to_dict(self) -> dict:
        return {
            "error_column": self.error_column,
            "total_rows": self.total_rows,
            "categories": self.categories,
        }


def find_error_column(table: Table) -> str | None:
    for c in table.columns:
        if c.strip().casefold() in _ERROR_COLUMN_NAMES:
            return c
    return None


def analyze_errors(table: Table) -> ErrorAnalysis:
    """error.csv形式のTableを分析し、エラー理由の内訳を返す。"""
    col = find_error_column(table)
    if col is None:
        raise DiffDeskError(
            "ERROR列が見つかりません。Data Loaderが出力した error ファイル"
            "(元の列+ERROR列)を読み込んでください。",
            columns=table.columns[:10],
        )
    i = table.col_index(col)
    buckets: dict[str, dict] = {}
    for row in table.rows:
        message = row[i].strip()
        if not message:
            continue
        matched = None
        for code, label, hint in ERROR_CATEGORIES:
            if code.casefold() in message.casefold():
                matched = (code, label, hint)
                break
        if matched is None:
            matched = ("OTHER", "その他", "エラーメッセージ本文を確認してください")
        code, label, hint = matched
        b = buckets.setdefault(code, {"code": code, "label": label, "hint": hint,
                                      "count": 0, "example": message[:200]})
        b["count"] += 1
    categories = sorted(buckets.values(), key=lambda b: -b["count"])
    return ErrorAnalysis(error_column=col, total_rows=len(table.rows),
                         categories=categories)


def build_retry_table(table: Table) -> Table:
    """ERROR/STATUS等の付加列を除いた再投入用Tableを返す(行はそのまま)。"""
    if find_error_column(table) is None:
        raise DiffDeskError("ERROR列が見つかりません。errorファイルを読み込んでください。")
    drop_idx = [i for i, c in enumerate(table.columns)
                if c.strip().casefold() in _DROP_COLUMNS]
    keep_idx = [i for i in range(len(table.columns)) if i not in drop_idx]
    return Table(
        columns=[table.columns[i] for i in keep_idx],
        rows=[[row[i] for i in keep_idx] for row in table.rows],
        name="再投入用",
    )
