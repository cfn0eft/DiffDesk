"""個人情報らしき列の検出(AIコピペ前のガード用)。

列名のヒューリスティック+値のパターンで、個人情報を含みそうな列を
検出する。検出は警告目的であり、完全性は保証しない。
"""
from __future__ import annotations

import re

from .model import DiffResult

_NAME_HINTS = (
    ("氏名", "氏名"), ("名前", "氏名"), ("カナ", "氏名(カナ)"), ("かな", "氏名(カナ)"),
    ("姓", "氏名"), ("name", "氏名"),
    ("住所", "住所"), ("address", "住所"),
    ("生年月日", "生年月日"), ("birth", "生年月日"),
    ("電話", "電話番号"), ("tel", "電話番号"), ("phone", "電話番号"),
    ("メール", "メールアドレス"), ("mail", "メールアドレス"),
)
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE = re.compile(r"^\+?[0-9][0-9\-() ]{8,14}$")


def _kind_by_name(column: str) -> str | None:
    low = column.lower()
    for hint, kind in _NAME_HINTS:
        if hint in low or hint in column:
            return kind
    return None


def _kind_by_values(values: list[str]) -> str | None:
    filled = [v for v in values if v.strip()][:200]
    if len(filled) < 3:
        return None
    if sum(1 for v in filled if _EMAIL.match(v.strip())) / len(filled) >= 0.5:
        return "メールアドレス"
    if sum(1 for v in filled if _PHONE.match(v.strip())) / len(filled) >= 0.5:
        return "電話番号"
    return None


def detect_pii_columns(columns: list[str], rows: list[list[str]]) -> list[dict]:
    """[{column, kind}] を返す(検出順は列順)。"""
    out = []
    for i, col in enumerate(columns):
        kind = _kind_by_name(col)
        if kind is None:
            kind = _kind_by_values([r[i] for r in rows])
        if kind:
            out.append({"column": col, "kind": kind})
    return out


def detect_pii_in_diff(diff: DiffResult) -> list[dict]:
    """差分結果のマッピング列から個人情報らしき列を検出する。

    AI用プロンプトには未対応行のA/B両方の値が含まれるため、
    列名はA側で代表し、値はA側→無ければB側を使う。
    """
    cols = [p.col_a for p in diff.mapping.pairs]
    rows = []
    for rd in diff.rows:
        row = rd.row_a or rd.row_b
        if row:
            rows.append(row)
        if len(rows) >= 500:
            break
    return detect_pii_columns(cols, rows)
