"""一括クレンジング(列単位の変換)。"""
from __future__ import annotations

import re
import unicodedata
from typing import Callable

from .model import DiffDeskError, Table

# 半角カナ→全角カナはNFKCで統一されるため、専用テーブルは全角ASCII変換のみ持つ
_HAN_TO_ZEN_ASCII = {i: i + 0xFEE0 for i in range(0x21, 0x7F)}
_HAN_TO_ZEN_ASCII[0x20] = 0x3000

# 全角英数記号(FF01-FF5E)と全角スペースのみを半角へ(カナ・漢字・①㈱等は不変)
_ZEN_TO_HAN_ASCII = {i + 0xFEE0: i for i in range(0x21, 0x7F)}
_ZEN_TO_HAN_ASCII[0x3000] = 0x20

_DATE_PATTERNS = [
    re.compile(r"^(?P<y>\d{4})[/\-.年](?P<m>\d{1,2})[/\-.月](?P<d>\d{1,2})日?$"),
    re.compile(r"^(?P<y>\d{4})(?P<m>\d{2})(?P<d>\d{2})$"),
]


def op_trim(v: str) -> str:
    return v.strip(" \t\r\n　")


def op_zen2han(v: str) -> str:
    """全角英数記号・スペースを半角に。カタカナはNFKCで全角に統一。"""
    return unicodedata.normalize("NFKC", v)


def op_alnum_han(v: str) -> str:
    """全角英数記号のみ半角に変換(カナ・漢字・①㈱などはそのまま)。"""
    return v.translate(_ZEN_TO_HAN_ASCII)


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


def op_digits_only(v: str) -> str:
    """数字以外を除去(電話番号・郵便番号の統一に。全角数字は半角化)。"""
    return re.sub(r"\D", "", unicodedata.normalize("NFKC", v))


_INT_RE = re.compile(r"^[+-]?\d+$")


def op_num_decimal(v: str) -> str:
    """整数に .0 を付ける(1550 → 1550.0)。

    Salesforce等が数値を小数点付きで出力する形式に合わせたいとき用。
    整数以外(既に小数点付き・数値でない値・空)はそのまま。全角数字は半角化される。
    """
    s = unicodedata.normalize("NFKC", v.strip(" \t\r\n　"))
    if _INT_RE.match(s):
        return s + ".0"
    return v


def op_num_plain(v: str) -> str:
    """小数点以下の末尾ゼロを除く(1550.0 → 1550、250.50 → 250.5)。

    小数点を含む純粋な数値のみ対象。先頭ゼロのID(0001)は変えない。
    """
    from .normalize import _canon_decimal
    s = unicodedata.normalize("NFKC", v.strip(" \t\r\n　"))
    out = _canon_decimal(s)
    return out if out != s else v


CLEAN_OPS: dict[str, tuple[str, Callable[[str], str]]] = {
    "trim": ("前後の空白を除去", op_trim),
    "alnum_han": ("全角英数記号→半角(それ以外は変えない)", op_alnum_han),
    "zen2han": ("全角英数→半角・半角カナ→全角(NFKC)", op_zen2han),
    "han2zen": ("半角英数→全角", op_han2zen),
    "kana_zenkaku": ("半角カナ→全角カナ", op_kana_zenkaku),
    "upper": ("大文字に統一", op_upper),
    "lower": ("小文字に統一", op_lower),
    "date_iso": ("日付を yyyy-MM-dd に統一", op_date_iso),
    "digits_only": ("数字のみ抽出(電話・郵便番号)", op_digits_only),
    "num_decimal": ("整数に .0 を付ける(1550 → 1550.0)", op_num_decimal),
    "num_plain": ("数値の末尾 .0 を除く(1550.0 → 1550)", op_num_plain),
}

# 列全体を見て処理する操作(セル単位では表現できないもの)
COLUMN_OPS: dict[str, str] = {
    "fill_down": "空欄を上の値で埋める(Excel結合セル対策)",
}


def _fill_down(rows: list[list[str]], ci: int) -> None:
    last = ""
    for row in rows:
        if row[ci].strip():
            last = row[ci]
        elif last:
            row[ci] = last


def clean_columns(table: Table, columns: list[str], ops: list[str]) -> tuple[Table, int]:
    """指定列に操作を順番に適用し、変更セル数を返す。"""
    for op in ops:
        if op not in CLEAN_OPS and op not in COLUMN_OPS:
            raise DiffDeskError(f"不明なクレンジング操作です: {op}", op=op)
    indices = [table.col_index(c) for c in columns]
    changed = 0
    for ci in indices:
        before = [row[ci] for row in table.rows]
        for op in ops:
            if op in CLEAN_OPS:
                f = CLEAN_OPS[op][1]
                for row in table.rows:
                    row[ci] = f(row[ci])
            else:  # COLUMN_OPS
                if op == "fill_down":
                    _fill_down(table.rows, ci)
        changed += sum(1 for row, old in zip(table.rows, before) if row[ci] != old)
    return table, changed
