"""投入時の変換ルールを比較時に再現する。

移行定義JSON(マッピング仕様書)の valueMap / truthyValues / normalizeRules /
type(date・number)を ColumnPair.transform として保持し、照合時にA側の値へ
適用してから比較する。「変換して投入されたはずの値」と抽出値を正しく突合できる。
表示・出力は常に元の値。
"""
from __future__ import annotations

import re
from typing import Callable

from .model import ColumnPair
from .normalize import values_equal

_DATE_RE = re.compile(
    r"^\s*(\d{4})[/\-年.](\d{1,2})[/\-月.](\d{1,2})日?(?:[ T].*)?$")


def canon_date(s: str) -> str:
    """日付らしい文字列をISO形式(YYYY-MM-DD)へ。解釈できなければそのまま。"""
    m = _DATE_RE.match(s)
    if not m:
        return s
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return s
    return f"{y:04d}-{mo:02d}-{d:02d}"


def apply_transform(value: str, t: dict) -> str:
    """A側の値に投入時の変換ルールを再現適用する。"""
    v = value
    for rule in t.get("regex_rules") or []:
        try:
            v = re.sub(rule.get("pattern", ""), rule.get("replacement", ""), v)
        except re.error:
            pass  # 不正なルールは無視(取り込み時に検証済みの想定)
    vm = t.get("value_map")
    if vm:
        stripped = v.strip()
        if stripped in vm:
            v = vm[stripped]
        elif "default_value" in t:
            v = t["default_value"]
    truthy = t.get("truthy_values")
    if truthy is not None:
        v = "true" if v.strip() in truthy else str(t.get("default_value", "false"))
    return v


def pair_values_equal(a: str, b: str, pair: ColumnPair,
                      normalizer: Callable[[str], str],
                      numeric_tolerance: float | None = None) -> bool:
    """変換ルールを考慮したセル値の等価判定。

    - transformあり: A側へ変換を適用してから比較
    - type=date: 両側をISO日付へ正規化(2021/10/15 = 2021-10-15)
    - type=boolean: 両側を小文字化して比較(True = true)
    """
    t = pair.transform
    if not t:
        return values_equal(a, b, normalizer, numeric_tolerance)
    a2 = apply_transform(a, t)
    b2 = b
    typ = t.get("type", "")
    if typ == "date":
        a2, b2 = canon_date(a2.strip()), canon_date(b2.strip())
    elif typ == "boolean":
        a2, b2 = a2.strip().lower(), b2.strip().lower()
    return values_equal(a2, b2, normalizer, numeric_tolerance)


def transform_summary(t: dict) -> str:
    """マッピング画面に表示する変換ルールの短い説明。"""
    parts = []
    if t.get("regex_rules"):
        parts.append(f"正規表現{len(t['regex_rules'])}件")
    if t.get("value_map"):
        parts.append(f"値変換{len(t['value_map'])}組")
    if t.get("truthy_values") is not None:
        parts.append("真偽値化")
    if t.get("type") == "date":
        parts.append("日付")
    if t.get("type") == "number":
        parts.append("数値")
    return "・".join(parts) or "変換"
