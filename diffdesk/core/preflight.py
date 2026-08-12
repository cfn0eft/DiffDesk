"""照合前のプリフライト診断。

A/Bを選んだ時点でデータの状態を点検し、差分実行前に
設定ミス・データ問題に気づけるようにする。
"""
from __future__ import annotations

import unicodedata

from .model import Table

_MAX_KEY_CANDIDATES = 3


def _norm_name(s: str) -> str:
    return unicodedata.normalize("NFKC", s).casefold().strip()


def _unique_nonempty_cols(table: Table) -> set[str]:
    """全行が空でなくユニークな列(キー候補)。"""
    out = set()
    for i, col in enumerate(table.columns):
        values = [row[i] for row in table.rows]
        if not values:
            continue
        if any(v.strip() == "" for v in values):
            continue
        if len(set(values)) == len(values):
            out.add(col)
    return out


def preflight(table_a: Table, table_b: Table) -> list[dict]:
    """診断結果のリスト [{level: ok|info|warn, message}] を返す。"""
    checks: list[dict] = []
    ra, rb = len(table_a.rows), len(table_b.rows)

    # 行数
    if ra == 0 or rb == 0:
        checks.append({"level": "warn",
                       "message": f"行数: A={ra}行 / B={rb}行 — データが空のファイルがあります。"})
    elif max(ra, rb) >= min(ra, rb) * 1.5 and abs(ra - rb) >= 10:
        checks.append({"level": "warn",
                       "message": f"行数差が大きいです(A={ra}行 / B={rb}行)。"
                                  f"対象範囲や行フィルタの条件を確認してください。"})
    else:
        checks.append({"level": "ok", "message": f"行数: A={ra}行 / B={rb}行"})

    # 列の対応
    norm_a = {_norm_name(c): c for c in table_a.columns}
    norm_b = {_norm_name(c): c for c in table_b.columns}
    common = set(norm_a) & set(norm_b)
    if common:
        checks.append({"level": "ok",
                       "message": f"列: A={len(table_a.columns)}列 / B={len(table_b.columns)}列、"
                                  f"名前が対応する列 {len(common)}組"})
    else:
        checks.append({"level": "info",
                       "message": "同名の列がありません。自動対応付けはユーザー辞書と"
                                  "値の中身から推定します(結果を必ず確認してください)。"})

    # キー候補(A/B両方でユニーク・空なし、名前対応が取れる列)
    uniq_a = _unique_nonempty_cols(table_a)
    uniq_b = _unique_nonempty_cols(table_b)
    candidates = [c for c in table_a.columns  # A側の列順で安定させる
                  if _norm_name(c) in common
                  and c in uniq_a and norm_b[_norm_name(c)] in uniq_b]
    if candidates:
        shown = "、".join(candidates[:_MAX_KEY_CANDIDATES])
        checks.append({"level": "ok",
                       "message": f"キー候補: {shown}(両ファイルでユニーク・空なし)"})
    else:
        # 片側だけユニークな対応列 → 重複・空の内訳を出す
        partial = []
        for n in common:
            ca, cb = norm_a[n], norm_b[n]
            in_a, in_b = ca in uniq_a, cb in uniq_b
            if in_a != in_b:
                side = "B" if in_a else "A"
                partial.append(f"{ca}({side}側に重複または空あり)")
        if partial:
            checks.append({"level": "warn",
                           "message": "両ファイルでユニークな共通列がありません: "
                                      + "、".join(partial[:3])
                                      + " — 複合キーにするか、該当行の重複を解消してください。"})
        else:
            checks.append({"level": "warn",
                           "message": "キーに使えそうな列(ユニーク・空なし)が見つかりません。"
                                      "キー方式「行番号で比較」「行の内容で比較」の使用を検討してください。"})

    # 全行空の列
    for name, table in (("A", table_a), ("B", table_b)):
        if not table.rows:
            continue
        empty_cols = [c for i, c in enumerate(table.columns)
                      if all(row[i].strip() == "" for row in table.rows)]
        if empty_cols:
            checks.append({"level": "info",
                           "message": f"ファイル{name}に全行が空の列: "
                                      + "、".join(empty_cols[:5])})

    # 完全重複行
    for name, table in (("A", table_a), ("B", table_b)):
        dup = len(table.rows) - len({tuple(r) for r in table.rows})
        if dup:
            checks.append({"level": "warn",
                           "message": f"ファイル{name}に完全重複行が{dup}行あります"
                                      f"(ツールタブの重複削除で解消できます)。"})
    return checks
