"""表記ゆれ検出(OpenRefineのfingerprint法を日本語向けに調整)。

「株式会社テスト / テスト(株) / ﾃｽﾄ株式会社」のような同一実体の別表記を、
正規化キー(fingerprint)の一致でグルーピングする。
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .model import Table

# 法人格などの識別に寄与しない語(NFKC後の表記で判定)
_LEGAL_FORMS = re.compile(
    r"株式会社|有限会社|合同会社|合資会社|合名会社|一般社団法人|一般財団法人|"
    r"公益社団法人|公益財団法人|特定非営利活動法人|医療法人|学校法人|"
    r"\(株\)|\(有\)|\(同\)|\(社\)|\(財\)"
)
_NON_WORD = re.compile(r"[^\w]", re.UNICODE)


def fingerprint(value: str) -> str:
    """表記ゆれ判定用の正規化キーを返す。"""
    v = unicodedata.normalize("NFKC", value).strip().casefold()
    v = _LEGAL_FORMS.sub("", v)
    v = _NON_WORD.sub("", v)  # 空白・記号・中点等を除去
    return v


@dataclass
class ValueCluster:
    key: str
    values: list[tuple[str, int]]  # (元の表記, 出現回数) 出現回数の多い順
    suggested: str                 # 統一先の推奨表記(最頻値、同数なら長い方)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "values": [{"value": v, "count": c} for v, c in self.values],
            "suggested": self.suggested,
            "total": sum(c for _, c in self.values),
        }


def cluster_column(table: Table, column: str, *, max_clusters: int = 200) -> list[ValueCluster]:
    """指定列の表記ゆれクラスタ(2種類以上の表記があるグループ)を返す。"""
    i = table.col_index(column)
    counts: Counter[str] = Counter()
    for row in table.rows:
        v = row[i]
        if v.strip():
            counts[v] += 1

    groups: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for value, count in counts.items():
        key = fingerprint(value)
        if key:
            groups[key].append((value, count))

    clusters: list[ValueCluster] = []
    for key, values in groups.items():
        if len(values) < 2:
            continue
        values.sort(key=lambda vc: (-vc[1], -len(vc[0])))
        clusters.append(ValueCluster(key=key, values=values, suggested=values[0][0]))
    clusters.sort(key=lambda c: -sum(cnt for _, cnt in c.values))
    return clusters[:max_clusters]


def apply_value_map(table: Table, column: str, mapping: dict[str, str]) -> tuple[Table, int]:
    """列内の値を対応表どおりに置換し、置換セル数を返す(完全一致のみ)。"""
    i = table.col_index(column)
    changed = 0
    for row in table.rows:
        new = mapping.get(row[i])
        if new is not None and new != row[i]:
            row[i] = new
            changed += 1
    return table, changed
