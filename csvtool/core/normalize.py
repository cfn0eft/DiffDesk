"""比較用のセル値正規化。表示・出力には使わない。"""
from __future__ import annotations

import unicodedata
from typing import Callable

from .model import DiffOptions

_WHITESPACE = " \t\r\n　"


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
