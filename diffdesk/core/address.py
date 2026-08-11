"""日本の住所分割(ルールベース)。

住所1列を 郵便番号 / 都道府県 / 市区町村 / それ以降 に分割する。
Salesforceの住所項目(PostalCode / State / City / Street)へのマッピング用。
"""
from __future__ import annotations

import re
import unicodedata

from .model import DiffDeskError, Table

_PREFECTURES = (
    "北海道 青森県 岩手県 宮城県 秋田県 山形県 福島県 茨城県 栃木県 群馬県 埼玉県 千葉県 "
    "東京都 神奈川県 新潟県 富山県 石川県 福井県 山梨県 長野県 岐阜県 静岡県 愛知県 三重県 "
    "滋賀県 京都府 大阪府 兵庫県 奈良県 和歌山県 鳥取県 島根県 岡山県 広島県 山口県 徳島県 "
    "香川県 愛媛県 高知県 福岡県 佐賀県 長崎県 熊本県 大分県 宮崎県 鹿児島県 沖縄県"
).split()
_PREF_RE = re.compile("|".join(_PREFECTURES))
_ZIP_RE = re.compile(r"〒?\s*(\d{3})[-−ー]?(\d{4})")
# 市区町村: 「〜市〜区」(政令市)、「〜郡〜町/村」、「〜市/区/町/村」
_CITY_RE = re.compile(
    r"^(?:(?P<seirei>.+?市.+?区)|(?P<gun>.+?郡.+?[町村])|(?P<simple>.+?[市区町村]))"
)


def split_address(value: str) -> dict[str, str]:
    """住所文字列を {zip, prefecture, city, rest} に分割する(分割不能部分は空)。"""
    s = unicodedata.normalize("NFKC", value).strip()
    result = {"zip": "", "prefecture": "", "city": "", "rest": ""}
    if not s:
        return result
    m = _ZIP_RE.search(s)
    if m:
        result["zip"] = f"{m.group(1)}-{m.group(2)}"
        s = (s[:m.start()] + s[m.end():]).strip()
    m = _PREF_RE.search(s)
    if m:
        result["prefecture"] = m.group(0)
        s = s[m.end():].strip() if m.start() == 0 else (s[:m.start()] + s[m.end():]).strip()
    m = _CITY_RE.match(s)
    if m:
        result["city"] = m.group(0)
        s = s[m.end():].strip()
    result["rest"] = s
    return result


def split_address_column(table: Table, column: str) -> tuple[Table, int]:
    """住所列を4列(郵便番号/都道府県/市区町村/以降)に置き換える。分割できた行数を返す。"""
    i = table.col_index(column)
    new_names = []
    existing = set(table.columns) - {column}
    for suffix in ("郵便番号", "都道府県", "市区町村", "以降"):
        name = f"{column}_{suffix}"
        while name in existing:
            name += "_x"
        existing.add(name)
        new_names.append(name)
    parsed = 0
    table.columns[i:i + 1] = new_names
    for row in table.rows:
        parts = split_address(row[i])
        if parts["prefecture"] or parts["zip"]:
            parsed += 1
        row[i:i + 1] = [parts["zip"], parts["prefecture"], parts["city"], parts["rest"]]
    if parsed == 0:
        raise DiffDeskError(
            f"列「{column}」から住所(都道府県・郵便番号)を検出できませんでした。")
    return table, parsed
