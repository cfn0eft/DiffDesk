"""キーなし あいまい突合(確率的レコード連結の簡易版)。

共通キーがない2ファイルを、複数列ペアの類似度スコアで紐づけ候補として提示する。
Fellegi-Sunter流の「列ごとの一致度の重み付き合算」をルールベースで簡略化したもの。
ブロッキング(先頭文字グループ化)で比較回数を抑える。
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from .model import DiffDeskError, Table
from .mapping_suggest import _canon_value  # 値の正規化を流用

_MAX_ROWS = 20_000
_DEFAULT_THRESHOLD = 0.75


@dataclass
class FuzzyCandidate:
    index_a: int
    index_b: int
    score: float
    details: list[float]  # 列ペアごとの類似度

    def to_dict(self) -> dict:
        return {"index_a": self.index_a, "index_b": self.index_b,
                "score": round(self.score, 3),
                "details": [round(d, 2) for d in self.details]}


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def fuzzy_match(table_a: Table, table_b: Table, *,
                pairs: list[tuple[str, str]],
                threshold: float = _DEFAULT_THRESHOLD,
                max_candidates: int = 500) -> list[FuzzyCandidate]:
    """列ペアの類似度合算で紐づけ候補を返す(スコア降順、1対1割当)。

    pairs: [(A列, B列), ...] 先頭のペアがブロッキングにも使われる。
    """
    if not pairs:
        raise DiffDeskError("突合に使う列ペアを1組以上指定してください。")
    if len(table_a.rows) > _MAX_ROWS or len(table_b.rows) > _MAX_ROWS:
        raise DiffDeskError(
            f"あいまい突合は{_MAX_ROWS:,}行までです。行フィルタ等で絞ってから実行してください。")

    ia = [table_a.col_index(a) for a, _ in pairs]
    ib = [table_b.col_index(b) for _, b in pairs]

    norm_a = [[_canon_value(row[i]) for i in ia] for row in table_a.rows]
    norm_b = [[_canon_value(row[i]) for i in ib] for row in table_b.rows]

    # ブロッキング: 先頭ペアの正規化値の先頭1文字でグループ化して比較回数を削減
    blocks: dict[str, list[int]] = {}
    for j, vals in enumerate(norm_b):
        key = vals[0][:1]
        blocks.setdefault(key, []).append(j)

    candidates: list[FuzzyCandidate] = []
    for i, vals_a in enumerate(norm_a):
        key = vals_a[0][:1]
        for j in blocks.get(key, ()):  # 先頭文字が同じもののみ比較
            vals_b = norm_b[j]
            details = [_similarity(x, y) for x, y in zip(vals_a, vals_b)]
            filled = [d for d, x, y in zip(details, vals_a, vals_b) if x and y]
            if not filled:
                continue
            score = sum(filled) / len(filled)
            if score >= threshold:
                candidates.append(FuzzyCandidate(i, j, score, details))

    # スコア降順で貪欲に1対1割当
    candidates.sort(key=lambda c: -c.score)
    used_a: set[int] = set()
    used_b: set[int] = set()
    picked: list[FuzzyCandidate] = []
    for c in candidates:
        if c.index_a in used_a or c.index_b in used_b:
            continue
        used_a.add(c.index_a)
        used_b.add(c.index_b)
        picked.append(c)
        if len(picked) >= max_candidates:
            break
    return picked


def build_linked_table(table_a: Table, table_b: Table,
                       matches: list[dict]) -> Table:
    """確定した紐づけ(index_a/index_b)からA+B横結合の紐づけ結果Tableを作る。"""
    cols_b = []
    existing = set(table_a.columns)
    for c in table_b.columns:
        name = c
        while name in existing:
            name = name + "_B"
        existing.add(name)
        cols_b.append(name)
    columns = list(table_a.columns) + cols_b + ["突合スコア"]
    rows = []
    for m in matches:
        ia, jb = int(m["index_a"]), int(m["index_b"])
        if not (0 <= ia < len(table_a.rows)) or not (0 <= jb < len(table_b.rows)):
            raise DiffDeskError("紐づけ候補の行番号が範囲外です(ファイルを編集した場合は再検出してください)。")
        rows.append(list(table_a.rows[ia]) + list(table_b.rows[jb]) + [str(m.get("score", ""))])
    return Table(columns=columns, rows=rows, name="あいまい突合結果")
