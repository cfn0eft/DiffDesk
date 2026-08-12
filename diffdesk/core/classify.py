"""差異の自動分類。

変更セルの「なぜ違うのか」をプログラムで仕分けする(AI不使用)。
正規化を1種類ずつ試し、どれで一致するかで原因を判定する。
"""
from __future__ import annotations

import re
import unicodedata

from .model import DiffResult
from .normalize import _canon_decimal
from .transform import canon_date

# 判定順(単独で一致した最初の原因を採用)
CAUSES = ("space", "width", "case", "numeric", "date", "zeropad", "combo", "real")

CAUSE_JA = {
    "space": "空白のみの違い",
    "width": "全角/半角のみの違い",
    "case": "大文字/小文字のみの違い",
    "numeric": "数値表記の違い(1550 = 1550.0)",
    "date": "日付形式の違い(2020/1/5 = 2020-01-05)",
    "zeropad": "ゼロ埋めの違い(1 = 0001)",
    "combo": "表記ゆれ(複合)",
    "real": "真の相違",
}

_WS = re.compile(r"\s+")
_NUMLIKE = re.compile(r"0*[0-9]+")


def _strip_ws(s: str) -> str:
    return _WS.sub("", s)


def _nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def classify_value_pair(a: str, b: str) -> str:
    """2つの値の差異原因を返す(CAUSESのいずれか。等しい場合は"same")。"""
    if a == b:
        return "same"
    if _strip_ws(a) == _strip_ws(b):
        return "space"
    if _nfkc(a) == _nfkc(b):
        return "width"
    if a.casefold() == b.casefold():
        return "case"
    sa, sb = a.strip(), b.strip()
    if _canon_decimal(sa) == _canon_decimal(sb):
        return "numeric"
    da, db = canon_date(sa), canon_date(sb)
    if (da != sa or db != sb) and da == db:
        return "date"
    if (_NUMLIKE.fullmatch(sa) and _NUMLIKE.fullmatch(sb)
            and sa.lstrip("0") == sb.lstrip("0")):
        return "zeropad"
    # 単独では一致しないが、全正規化を重ねると一致する(例: 全角+空白)
    full = lambda s: _canon_decimal(_nfkc(_strip_ws(s)).casefold())  # noqa: E731
    if full(a) == full(b):
        return "combo"
    return "real"


def classify_diff(result: DiffResult) -> dict:
    """差分結果の変更セルを原因別に集計する。

    返り値: {"total": 全差異セル数, "causes": [
        {"cause", "label", "count", "columns": {列: 件数},
         "samples": [{"col_a","value_a","value_b"}] (最大3件)}]}
    順序はCAUSES順(存在するもののみ)。
    """
    counts: dict[str, int] = {}
    columns: dict[str, dict[str, int]] = {}
    samples: dict[str, list[dict]] = {}
    triples: dict[str, set] = {}
    total = 0
    for rd in result.rows:
        if rd.status != "changed":
            continue
        for cd in rd.cell_diffs:
            cause = classify_value_pair(cd.value_a, cd.value_b)
            if cause == "same":
                continue
            total += 1
            counts[cause] = counts.get(cause, 0) + 1
            triples.setdefault(cause, set()).add(
                (cd.col_a, cd.value_a, cd.value_b))
            columns.setdefault(cause, {})
            columns[cause][cd.col_a] = columns[cause].get(cd.col_a, 0) + 1
            bucket = samples.setdefault(cause, [])
            if len(bucket) < 3 and not any(
                    s["value_a"] == cd.value_a and s["value_b"] == cd.value_b
                    and s["col_a"] == cd.col_a for s in bucket):
                bucket.append({"col_a": cd.col_a, "value_a": cd.value_a,
                               "value_b": cd.value_b})
    return {
        "total": total,
        "causes": [{
            "cause": c, "label": CAUSE_JA[c], "count": counts[c],
            "rule_count": len(triples.get(c, ())),
            "columns": columns.get(c, {}), "samples": samples.get(c, []),
        } for c in CAUSES if c in counts],
    }


def rows_with_cause(result: DiffResult, cause: str):
    """指定原因の差異セルを含む変更行のみを返す(rowsのサブセット)。"""
    out = []
    for rd in result.rows:
        if rd.status != "changed":
            continue
        if any(classify_value_pair(cd.value_a, cd.value_b) == cause
               for cd in rd.cell_diffs):
            out.append(rd)
    return out


def value_rules_for_cause(result: DiffResult, cause: str) -> list[dict]:
    """指定原因の差異を値ルール既知として一括登録するためのエントリ一覧。

    (列, 値A, 値B) の組で重複排除した value タイプの既知差分エントリを返す。
    """
    seen: set[tuple[str, str, str]] = set()
    rules: list[dict] = []
    for rd in result.rows:
        if rd.status != "changed":
            continue
        for cd in rd.cell_diffs:
            if classify_value_pair(cd.value_a, cd.value_b) != cause:
                continue
            key = (cd.col_a, cd.value_a, cd.value_b)
            if key in seen:
                continue
            seen.add(key)
            rules.append({
                "type": "value", "col_a": cd.col_a,
                "value_a": cd.value_a, "value_b": cd.value_b,
                "note": f"自動分類({CAUSE_JA[cause]})から一括登録",
            })
    return rules
