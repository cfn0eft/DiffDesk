"""多対多(親A - 中間 - 親B)モデルの移行検証。

データ移行QAの定型ロジックを実装する:
  ステップ1: 親Aのマクロ検証 — 移行元のユニーク件数(期待値) vs 抽出の実績件数
  ステップ2: 親Bのマクロ検証 — 空白除外+正規化後のユニーク件数 vs 実績件数
  ステップ3: 中間のマクロ検証 — スキップ条件適用後の複合キーのユニーク件数 vs 実績件数
  ステップ4: 未取込の孤立分析 — 欠落した中間キーの原因を
             「親A欠落 / 親B欠落 / 両親欠落 / 親は存在(中間のみ欠落)」に切り分け

すべて純Python。比較は normalize の既定正規化(空白除去・NFKC・数値同一視)を通す。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import DiffDeskError, DiffOptions, Table
from .normalize import make_normalizer

_SAMPLE_LIMIT = 200  # レポートに載せる欠落・過剰キーの上限


@dataclass
class JunctionConfig:
    """多対多検証の設定。列名は各ファイルの実列名。"""

    # 移行元(1ファイルに親A・親Bのソース値が行単位で入っている前提)
    a_source_col: str            # 親Aのソース列
    b_source_col: str            # 親Bのソース列
    # 抽出側
    a_ext_col: str               # 親A抽出の外部ID列
    b_ext_col: str               # 親B抽出の外部ID列
    j_key_col: str               # 中間抽出の複合キー列
    # 複合キー生成テンプレート({A} {B} を置換)
    key_template: str = "{A}-{B}"
    # 親Bの正規化(任意の正規表現置換)
    b_regex_pattern: str = ""
    b_regex_replacement: str = ""
    # スキップ条件: この列が空白の行は取り込み対象外(任意)
    required_col: str = ""
    # 中間抽出の親参照列(任意・指定時は参照整合も確認)
    j_ref_a_col: str = ""
    j_ref_b_col: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "JunctionConfig":
        cfg = cls(
            a_source_col=str(d.get("a_source_col", "")),
            b_source_col=str(d.get("b_source_col", "")),
            a_ext_col=str(d.get("a_ext_col", "")),
            b_ext_col=str(d.get("b_ext_col", "")),
            j_key_col=str(d.get("j_key_col", "")),
            key_template=str(d.get("key_template", "{A}-{B}") or "{A}-{B}"),
            b_regex_pattern=str(d.get("b_regex_pattern", "")),
            b_regex_replacement=str(d.get("b_regex_replacement", "")),
            required_col=str(d.get("required_col", "")),
            j_ref_a_col=str(d.get("j_ref_a_col", "")),
            j_ref_b_col=str(d.get("j_ref_b_col", "")),
        )
        for name, v in (("a_source_col", cfg.a_source_col),
                        ("b_source_col", cfg.b_source_col),
                        ("a_ext_col", cfg.a_ext_col),
                        ("b_ext_col", cfg.b_ext_col),
                        ("j_key_col", cfg.j_key_col)):
            if not v:
                raise DiffDeskError(f"多対多検証の設定 {name} が未指定です。")
        if "{A}" not in cfg.key_template or "{B}" not in cfg.key_template:
            raise DiffDeskError(
                "複合キーの形式には {A} と {B} の両方を含めてください(例: REL-{A}-{B})。")
        if cfg.b_regex_pattern:
            try:
                re.compile(cfg.b_regex_pattern)
            except re.error as e:
                raise DiffDeskError(f"親Bの正規化の正規表現が不正です: {e}")
        return cfg


def _macro(name: str, expected_keys: set[str], actual_keys: list[str],
           normalizer) -> dict:
    """期待キー集合と実績キー一覧の突合(件数+欠落/過剰の内訳)。"""
    actual_set: set[str] = set()
    dup_actual = 0
    for k in actual_keys:
        nk = normalizer(k)
        if not nk:
            continue
        if nk in actual_set:
            dup_actual += 1
        actual_set.add(nk)
    missing = sorted(expected_keys - actual_set)
    extra = sorted(actual_set - expected_keys)
    return {
        "name": name,
        "expected": len(expected_keys),
        "actual": len(actual_keys),
        "actual_unique": len(actual_set),
        "diff": len(actual_keys) - len(expected_keys),
        "missing": missing[:_SAMPLE_LIMIT],
        "missing_count": len(missing),
        "extra": extra[:_SAMPLE_LIMIT],
        "extra_count": len(extra),
        "dup_actual": dup_actual,
        "passed": not missing and not extra and dup_actual == 0,
    }


def verify_junction(source: Table, extract_a: Table, extract_b: Table,
                    extract_j: Table, config: JunctionConfig,
                    options: DiffOptions | None = None) -> dict:
    """多対多モデルの移行検証を実行し、4ステップの結果を返す。"""
    norm = make_normalizer(options or DiffOptions())

    ia = source.col_index(config.a_source_col)
    ib = source.col_index(config.b_source_col)
    ireq = source.col_index(config.required_col) if config.required_col else None
    iea = extract_a.col_index(config.a_ext_col)
    ieb = extract_b.col_index(config.b_ext_col)
    iej = extract_j.col_index(config.j_key_col)

    def norm_b(v: str) -> str:
        v = norm(v)
        if config.b_regex_pattern:
            v = re.sub(config.b_regex_pattern, config.b_regex_replacement, v)
        return v

    # 移行元から期待値を組み立てる
    a_expected: set[str] = set()
    b_expected: set[str] = set()
    j_expected: dict[str, tuple[str, str]] = {}  # 複合キー -> (親Aキー, 親Bキー)
    skipped_required = 0
    skipped_empty_pair = 0
    for row in source.rows:
        a_raw = norm(row[ia])
        b_raw = norm_b(row[ib])
        if a_raw:
            a_expected.add(a_raw)
        if b_raw:
            b_expected.add(b_raw)
        # 中間: スキップ条件(必須列が空白)と、キー成分が欠けた行は対象外
        if ireq is not None and not norm(row[ireq]):
            skipped_required += 1
            continue
        if not a_raw or not b_raw:
            skipped_empty_pair += 1
            continue
        jkey = config.key_template.replace("{A}", a_raw).replace("{B}", b_raw)
        j_expected.setdefault(jkey, (a_raw, b_raw))

    # ステップ1〜3: マクロ検証
    step1 = _macro("親A", a_expected, [r[iea] for r in extract_a.rows], norm)
    step2 = _macro("親B", b_expected, [r[ieb] for r in extract_b.rows], norm_b)
    step3 = _macro("中間", set(j_expected), [r[iej] for r in extract_j.rows], norm)
    step3["skipped_required"] = skipped_required
    step3["skipped_empty_pair"] = skipped_empty_pair

    # ステップ4: 未取込中間キーの原因切り分け
    a_actual = {norm(r[iea]) for r in extract_a.rows} - {""}
    b_actual = {norm_b(r[ieb]) for r in extract_b.rows} - {""}
    j_actual = {norm(r[iej]) for r in extract_j.rows} - {""}
    causes = {"missing_a": 0, "missing_b": 0, "missing_both": 0, "parents_ok": 0}
    samples: list[dict] = []
    for jkey, (a_key, b_key) in j_expected.items():
        if norm(jkey) in j_actual:
            continue
        a_ok = a_key in a_actual
        b_ok = b_key in b_actual
        cause = ("parents_ok" if a_ok and b_ok
                 else "missing_both" if not a_ok and not b_ok
                 else "missing_a" if not a_ok
                 else "missing_b")
        causes[cause] += 1
        if len(samples) < _SAMPLE_LIMIT:
            samples.append({"key": jkey, "a": a_key, "b": b_key, "cause": cause})

    total_missing = sum(causes.values())
    bottleneck = None
    if total_missing:
        worst = max(("missing_a", "missing_b", "missing_both", "parents_ok"),
                    key=lambda c: causes[c])
        bottleneck = worst if causes[worst] else None

    # 参照整合(任意): 中間抽出の親参照列が親抽出に実在するか
    ref_errors = None
    if config.j_ref_a_col and config.j_ref_b_col:
        ira = extract_j.col_index(config.j_ref_a_col)
        irb = extract_j.col_index(config.j_ref_b_col)
        bad_a = sum(1 for r in extract_j.rows if norm(r[ira]) not in a_actual)
        bad_b = sum(1 for r in extract_j.rows if norm_b(r[irb]) not in b_actual)
        ref_errors = {"bad_ref_a": bad_a, "bad_ref_b": bad_b}

    passed = step1["passed"] and step2["passed"] and step3["passed"]
    return {
        "parent_a": step1,
        "parent_b": step2,
        "junction": step3,
        "orphans": {"causes": causes, "total": total_missing,
                    "bottleneck": bottleneck, "samples": samples},
        "ref_errors": ref_errors,
        "passed": passed,
    }


CAUSE_JA = {
    "missing_a": "親Aの外部IDが移行先に存在しない",
    "missing_b": "親Bの外部IDが移行先に存在しない",
    "missing_both": "親A・親Bの両方が存在しない",
    "parents_ok": "両親は存在するが中間だけ未取込",
}


def build_orphan_table(result: dict, config: JunctionConfig) -> Table:
    """未取込の中間キー一覧をCSV出力用Tableにする(原因つき・アクション可能)。"""
    rows = [[s["key"], s["a"], s["b"], CAUSE_JA.get(s["cause"], s["cause"])]
            for s in result["orphans"]["samples"]]
    return Table(
        columns=["複合キー", "親Aキー", "親Bキー", "未取込の原因"],
        rows=rows, name="未取込一覧",
    )
