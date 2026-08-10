"""列マッピングの自動提案(LLM不使用)。

1. 名前一致: 完全一致 → NFKC正規化・大小文字無視の一致
2. 値ベース一致: 残った列同士で「列の中身(サンプル値)の重なり」から対応を推定
   — 列名が全く異なるファイル(日本語ヘッダー vs Salesforce API名)でも紐づけられる
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from .model import Table

_SAMPLE_ROWS = 500
_MIN_DISTINCT = 2      # 定数列(全行同じ値)は値ベース対象外
_MIN_CONFIDENCE = 0.5


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).strip().casefold()


@dataclass
class MappingSuggestion:
    col_a: str
    col_b: str
    method: str        # "name" | "value"
    confidence: float  # 0.0〜1.0

    def to_dict(self) -> dict:
        return {
            "col_a": self.col_a, "col_b": self.col_b,
            "is_key": False, "sf_field": None,
            "method": self.method, "confidence": round(self.confidence, 2),
        }


def _value_sets(table: Table, columns: list[str]) -> dict[str, set[str]]:
    idx = {c: table.col_index(c) for c in columns}
    sets: dict[str, set[str]] = {c: set() for c in columns}
    for row in table.rows[:_SAMPLE_ROWS]:
        for c, i in idx.items():
            v = _norm(row[i])
            if v:
                sets[c].add(v)
    return sets


def suggest_mapping(table_a: Table, table_b: Table) -> list[MappingSuggestion]:
    suggestions: list[MappingSuggestion] = []
    used_b: set[str] = set()

    # --- 1) 名前一致
    norm_b = {}
    for b in table_b.columns:
        norm_b.setdefault(_norm(b), b)
    for a in table_a.columns:
        hit = None
        confidence = 0.0
        if a in table_b.columns and a not in used_b:
            hit, confidence = a, 1.0
        else:
            cand = norm_b.get(_norm(a))
            if cand is not None and cand not in used_b:
                hit, confidence = cand, 0.9
        if hit is not None:
            used_b.add(hit)
            suggestions.append(MappingSuggestion(a, hit, "name", confidence))

    # --- 2) 値ベース一致(名前で決まらなかった列同士)
    rest_a = [c for c in table_a.columns if not any(s.col_a == c for s in suggestions)]
    rest_b = [c for c in table_b.columns if c not in used_b]
    if not rest_a or not rest_b or not table_a.rows or not table_b.rows:
        return suggestions

    sets_a = _value_sets(table_a, rest_a)
    sets_b = _value_sets(table_b, rest_b)
    candidates: list[tuple[float, str, str]] = []
    for a in rest_a:
        sa = sets_a[a]
        if len(sa) < _MIN_DISTINCT:
            continue
        for b in rest_b:
            sb = sets_b[b]
            if len(sb) < _MIN_DISTINCT:
                continue
            overlap = len(sa & sb) / min(len(sa), len(sb))
            if overlap >= _MIN_CONFIDENCE:
                candidates.append((overlap, a, b))

    # 重なりが大きい順に貪欲に割り当て
    used_a: set[str] = set()
    for overlap, a, b in sorted(candidates, key=lambda t: -t[0]):
        if a in used_a or b in used_b:
            continue
        used_a.add(a)
        used_b.add(b)
        suggestions.append(MappingSuggestion(a, b, "value", overlap))

    order = {c: i for i, c in enumerate(table_a.columns)}
    suggestions.sort(key=lambda s: order[s.col_a])
    return suggestions
