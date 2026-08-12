"""比較用のセル値正規化。表示・出力には使わない。"""
from __future__ import annotations

import re
import unicodedata
from typing import Callable

from .model import DiffOptions

_WHITESPACE = " \t\r\n　"
# 小数点を含む純粋な数値だけを対象にする(先頭ゼロのID等は小数点が無いので触らない)
_DECIMAL = re.compile(r"[+-]?\d+\.\d*")


def _canon_decimal(s: str) -> str:
    """"1551.0"→"1551"、"1551.50"→"1551.5"。数値表記だけの差異を吸収する。

    ExcelやSalesforceのエクスポートは数値項目を小数点付きで出力することがある。
    小数点を含まない値("0001" 等のID)は一切変更しない。
    """
    if not _DECIMAL.fullmatch(s):
        return s
    s = s.rstrip("0").rstrip(".")
    if s in ("", "-", "+", "-0", "+0"):
        return "0"
    return s


def make_normalizer(opts: DiffOptions) -> Callable[[str], str]:
    """DiffOptionsに応じた正規化関数を合成して返す。"""

    def normalize(s: str) -> str:
        if opts.trim:
            s = s.strip(_WHITESPACE)
        if opts.normalize_width:
            # NFKC: 全角英数→半角、半角カナ→全角カナ、㈱→(株) 等の互換分解
            s = unicodedata.normalize("NFKC", s)
            if opts.trim:
                # NFKCで全角空白が半角空白になるため再トリム
                s = s.strip(_WHITESPACE)
        if opts.normalize_numeric:
            s = _canon_decimal(s)
        if opts.ignore_case:
            s = s.casefold()
        return s

    return normalize


def values_equal(a: str, b: str, normalizer: Callable[[str], str],
                 numeric_tolerance: float | None = None) -> bool:
    """正規化後の等価判定。numeric_tolerance指定時は数値として許容誤差比較も試みる。"""
    na, nb = normalizer(a), normalizer(b)
    if na == nb:
        return True
    if numeric_tolerance is not None:
        try:
            return abs(float(na) - float(nb)) <= numeric_tolerance
        except ValueError:
            return False
    return False
