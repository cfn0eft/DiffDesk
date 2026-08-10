"""一括クレンジング(列単位の変換)。"""
from __future__ import annotations

import re
import unicodedata
from typing import Callable

from .model import CsvToolError, Table

# 半角カナ→全角カナはNFKCで統一されるため、専用テーブルは全角ASCII変換のみ持つ
_HAN_TO_ZEN_ASCII = {i: i + 0xFEE0 for i in range(0x21, 0x7F)}
_HAN_TO_ZEN_ASCII[0x20] = 0x3000

_DATE_PATTERNS = [
    re.compile(r"^(?P<y>\d{4})[/\-.年](?P<m>\d{1,2})[/\-.月](?P<d>\d{1,2})日?$"),
    re.compile(r"^(?P<y>\d{4})(?P<m>\d{2})(?P<d>\d{2})$"),
]


def op_trim(v: str) -> str:
    return v.strip(" \t\r\n　")


def op_zen2han(v: str) -> str:
    """全角英数記号・スペースを半角に。カタカナはNFKCで全角に統一。"""
    return unicodedata.normalize("NFKC", v)


def op_han2zen(v: str) -> str:
    """半角英数記号を全角に(半角カナも全角に統一してから変換)。"""
    return unicodedata.normalize("NFKC", v).translate(_HAN_TO_ZEN_ASCII)


def op_kana_zenkaku(v: str) -> str:
    """半角カナのみ全角化(英数はそのまま)。"""
    out = []
    for ch in v:
        if "｡" <= ch <= "ﾟ":  # 半角カナブロック
            out.append(unicodedata.normalize("NFKC", ch))
        else:
            out.append(ch)
    return unicodedata.normalize("NFC", "".join(out))


def op_upper(v: str) -> str:
    return v.upper()


def op_lower(v: str) -> str:
    return v.lower()


def op_date_iso(v: str) -> str:
    """よくある日付表記を Salesforce が受け付ける yyyy-MM-dd に統一。

    解釈できない値はそのまま返す(壊さない)。
    """
    s = unicodedata.normalize("NFKC", v.strip(" \t\r\n　"))
    if not s:
        return v
    for pat in _DATE_PATTERNS:
        m = pat.match(s)
        if m:
            y, mo, d = int(m.group("y")), int(m.group("m")), int(m.group("d"))
            if 1 <= mo <= 12 and 1 <= d <= 31:
                return f"{y:04d}-{mo:02d}-{d:02d}"
    return v


CLEAN_OPS: dict[str, tuple[str, Callable[[str], str]]] = {
    "trim": ("前後の空白を除去", op_trim),
    "zen2han": ("全角英数→半角・半角カナ→全角(NFKC)", op_zen2han),
    "han2zen": ("半角英数→全角", op_han2zen),
    "kana_zenkaku": ("半角カナ→全角カナ", op_kana_zenkaku),
    "upper": ("大文字に統一", op_upper),
    "lower": ("小文字に統一", op_lower),
    "date_iso": ("日付を yyyy-MM-dd に統一", op_date_iso),
}


def clean_columns(table: Table, columns: list[str], ops: list[str]) -> tuple[Table, int]:
    """指定列に操作を順番に適用し、変更セル数を返す。"""
    funcs = []
    for op in ops:
        if op not in CLEAN_OPS:
            raise CsvToolError(f"不明なクレンジング操作です: {op}", op=op)
        funcs.append(CLEAN_OPS[op][1])
    indices = [table.col_index(c) for c in columns]
    changed = 0
    for row in table.rows:
        for ci in indices:
            v = row[ci]
            for f in funcs:
                v = f(v)
            if v != row[ci]:
                row[ci] = v
                changed += 1
    return table, changed
