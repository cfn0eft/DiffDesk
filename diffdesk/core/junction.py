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
    # 親A/親Bの正規化(任意の正規表現置換)。移行時に値を変換して登録した場合、
    # その変換を再現する(例: 1550 を 1550.0 で登録 → ^(\d+)$ → \1.0)
    a_regex_pattern: str = ""
    a_regex_replacement: str = ""
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
            a_regex_pattern=str(d.get("a_regex_pattern", "")),
            a_regex_replacement=str(d.get("a_regex_replacement", "")),
            b_regex_pattern=str(d.get("b_regex_pattern", "")),
            b_regex_replacement=str(d.get("b_regex_replacement", "")),
            required_col=str(d.get("required_col", "")),
            j_ref_a_col=str(d.get("j_ref_a_col", "")),
            j_ref_b_col=str(d.get("j_ref_b_col", "")),
        )
        # 必須は3つだけ(親A/親Bの外部ID列は親抽出を使う場合のみ検証時に必須)
        for name, v in (("a_source_col", cfg.a_source_col),
                        ("b_source_col", cfg.b_source_col),
                        ("j_key_col", cfg.j_key_col)):
            if not v:
                raise DiffDeskError(f"多対多検証の設定 {name} が未指定です。")
        if "{A}" not in cfg.key_template or "{B}" not in cfg.key_template:
            raise DiffDeskError(
                "複合キーの形式には {A} と {B} の両方を含めてください(例: REL-{A}-{B})。")
        for label, pat in (("親A", cfg.a_regex_pattern), ("親B", cfg.b_regex_pattern)):
            if pat:
                try:
                    re.compile(pat)
                except re.error as e:
                    raise DiffDeskError(f"{label}の正規化の正規表現が不正です: {e}")
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


def verify_junction(source: Table, extract_a: Table | None,
                    extract_b: Table | None,
                    extract_j: Table, config: JunctionConfig,
                    options: DiffOptions | None = None) -> dict:
    """多対多モデルの移行検証を実行し、4ステップ+関係ビューの結果を返す。

    extract_a / extract_b は任意。未指定の場合はその親のマクロ検証をスキップし、
    孤立分析の原因も「不明(親抽出未指定)」になる。
    """
    norm = make_normalizer(options or DiffOptions())

    ia = source.col_index(config.a_source_col)
    ib = source.col_index(config.b_source_col)
    ireq = source.col_index(config.required_col) if config.required_col else None
    if extract_a is not None and not config.a_ext_col:
        raise DiffDeskError("親A抽出を選んだ場合は、親Aの外部ID列を指定してください。")
    if extract_b is not None and not config.b_ext_col:
        raise DiffDeskError("親B抽出を選んだ場合は、親Bの外部ID列を指定してください。")
    iea = extract_a.col_index(config.a_ext_col) if extract_a is not None else None
    ieb = extract_b.col_index(config.b_ext_col) if extract_b is not None else None
    iej = extract_j.col_index(config.j_key_col)

    def norm_a(v: str) -> str:
        v = norm(v)
        if config.a_regex_pattern:
            v = re.sub(config.a_regex_pattern, config.a_regex_replacement, v)
        return v

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
        a_raw = norm_a(row[ia])
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

    # ステップ1〜3: マクロ検証(親は抽出がある場合のみ)
    step1 = (_macro("親A", a_expected, [r[iea] for r in extract_a.rows], norm_a)
             if extract_a is not None else None)
    step2 = (_macro("親B", b_expected, [r[ieb] for r in extract_b.rows], norm_b)
             if extract_b is not None else None)
    step3 = _macro("中間", set(j_expected), [r[iej] for r in extract_j.rows], norm)
    step3["skipped_required"] = skipped_required
    step3["skipped_empty_pair"] = skipped_empty_pair

    # ステップ4: 未取込中間キーの原因切り分け
    a_actual = ({norm_a(r[iea]) for r in extract_a.rows} - {""}
                if extract_a is not None else None)
    b_actual = ({norm_b(r[ieb]) for r in extract_b.rows} - {""}
                if extract_b is not None else None)
    j_actual = {norm(r[iej]) for r in extract_j.rows} - {""}
    causes = {"missing_a": 0, "missing_b": 0, "missing_both": 0,
              "parents_ok": 0, "unknown": 0}
    samples: list[dict] = []
    cause_by_key: dict[str, str] = {}
    for jkey, (a_key, b_key) in j_expected.items():
        if norm(jkey) in j_actual:
            continue
        a_ok = (a_key in a_actual) if a_actual is not None else None
        b_ok = (b_key in b_actual) if b_actual is not None else None
        if a_ok is False and b_ok is False:
            cause = "missing_both"
        elif a_ok is False:
            cause = "missing_a"
        elif b_ok is False:
            cause = "missing_b"
        elif a_ok and b_ok:
            cause = "parents_ok"
        else:
            cause = "unknown"  # 親抽出が未指定で判定材料がない
        causes[cause] += 1
        cause_by_key[jkey] = cause
        if len(samples) < _SAMPLE_LIMIT:
            samples.append({"key": jkey, "a": a_key, "b": b_key, "cause": cause})

    total_missing = sum(causes.values())
    bottleneck = None
    if total_missing:
        worst = max(causes, key=lambda c: causes[c])
        bottleneck = worst if causes[worst] else None

    # 参照整合(任意): 中間抽出の親参照列が親抽出に実在するか
    ref_errors = None
    if (config.j_ref_a_col and config.j_ref_b_col
            and a_actual is not None and b_actual is not None):
        ira = extract_j.col_index(config.j_ref_a_col)
        irb = extract_j.col_index(config.j_ref_b_col)
        bad_a = sum(1 for r in extract_j.rows if norm_a(r[ira]) not in a_actual)
        bad_b = sum(1 for r in extract_j.rows if norm_b(r[irb]) not in b_actual)
        ref_errors = {"bad_ref_a": bad_a, "bad_ref_b": bad_b}

    relations = _build_relations(j_expected, j_actual, cause_by_key,
                                 step3, config, norm)

    passed = ((step1 is None or step1["passed"])
              and (step2 is None or step2["passed"])
              and step3["passed"])
    return {
        "parent_a": step1,
        "parent_b": step2,
        "junction": step3,
        "orphans": {"causes": causes, "total": total_missing,
                    "bottleneck": bottleneck, "samples": samples},
        "ref_errors": ref_errors,
        "relations": relations,
        "passed": passed,
    }


_RELATION_GROUP_LIMIT = 2000


def _template_regex(template: str) -> re.Pattern | None:
    """複合キーテンプレートを逆変換用の正規表現にする({A}は控えめ、{B}は貪欲)。"""
    try:
        pat = re.escape(template)
        pat = pat.replace(re.escape("{A}"), "(?P<A>.+?)")
        pat = pat.replace(re.escape("{B}"), "(?P<B>.+)")
        return re.compile("^" + pat + "$")
    except re.error:
        return None


def _build_relations(j_expected: dict, j_actual: set[str],
                     cause_by_key: dict, step3: dict,
                     config: JunctionConfig, norm) -> dict:
    """親Aごとに「紐づく親B」を状態つきで並べた関係ビュー用データを作る。"""
    groups: dict[str, dict] = {}

    def group(a_key: str) -> dict:
        if a_key not in groups:
            groups[a_key] = {"a": a_key, "ok": 0, "ng": 0, "items": []}
        return groups[a_key]

    for jkey, (a_key, b_key) in j_expected.items():
        g = group(a_key)
        if norm(jkey) in j_actual:
            g["items"].append({"b": b_key, "key": jkey, "status": "ok"})
            g["ok"] += 1
        else:
            g["items"].append({"b": b_key, "key": jkey, "status": "missing",
                               "cause": cause_by_key.get(jkey, "unknown")})
            g["ng"] += 1

    # 想定外の実績キー(移行元に無い): テンプレート逆変換で(a,b)へ分解
    rx = _template_regex(config.key_template)
    unparsed: list[str] = []
    for k in step3["extra"]:  # _macroで_SAMPLE_LIMITに制限済み
        m = rx.match(k) if rx else None
        if m:
            g = group(m.group("A"))
            g["items"].append({"b": m.group("B"), "key": k, "status": "extra"})
            g["ng"] += 1
        else:
            unparsed.append(k)

    ordered = list(groups.values())
    # 問題のある親を先頭に(UIの既定フィルタとも整合)
    ordered.sort(key=lambda g: (g["ng"] == 0, g["a"]))
    return {
        "groups": ordered[:_RELATION_GROUP_LIMIT],
        "total_groups": len(ordered),
        "truncated": len(ordered) > _RELATION_GROUP_LIMIT,
        "unparsed_extra": unparsed[:100],
        "unparsed_extra_count": len(unparsed),
    }


def infer_key_template(source: Table, extract_j: Table, *,
                       a_source_col: str, b_source_col: str, j_key_col: str,
                       a_regex_pattern: str = "",
                       a_regex_replacement: str = "",
                       b_regex_pattern: str = "",
                       b_regex_replacement: str = "",
                       options: DiffOptions | None = None,
                       sample: int = 500) -> dict:
    """移行元の(親A,親B)組と中間キーの実例から複合キーの形式を推定する。

    実例キーの中に親A・親Bの値がそれぞれ1回ずつ現れる場合、その位置関係から
    テンプレート(例: "REL-{A}-{B}")を復元し、多数決+適用検証で確からしさを返す。
    """
    norm = make_normalizer(options or DiffOptions())

    def regex_norm(pattern: str, replacement: str):
        def f(v: str) -> str:
            v = norm(v)
            if pattern:
                try:
                    v = re.sub(pattern, replacement, v)
                except re.error:
                    pass
            return v
        return f

    norm_a = regex_norm(a_regex_pattern, a_regex_replacement)
    norm_b = regex_norm(b_regex_pattern, b_regex_replacement)

    ia = source.col_index(a_source_col)
    ib = source.col_index(b_source_col)
    iej = extract_j.col_index(j_key_col)
    pairs = []
    seen = set()
    for row in source.rows[: sample * 4]:
        a, b = norm_a(row[ia]), norm_b(row[ib])
        if a and b and (a, b) not in seen:
            seen.add((a, b))
            pairs.append((a, b))
        if len(pairs) >= sample:
            break
    jkeys = [norm(r[iej]) for r in extract_j.rows[:sample] if norm(r[iej])]
    jset = set(jkeys)
    if not pairs or not jkeys:
        raise DiffDeskError("推定に使える行がありません(移行元と中間抽出の両方に値が必要です)。")

    votes: dict[str, int] = {}
    for a, b in pairs:
        for k in jkeys:
            if a in k and b in k:
                marked = k.replace(a, "\x00", 1)
                if b not in marked:
                    continue
                marked = marked.replace(b, "\x01", 1)
                if "\x00" not in marked or "\x01" not in marked:
                    continue
                tpl = marked.replace("\x00", "{A}").replace("\x01", "{B}")
                votes[tpl] = votes.get(tpl, 0) + 1

    if not votes:
        return {"template": None, "coverage": 0.0, "checked": len(pairs)}
    best = max(votes, key=lambda t: votes[t])
    # 検証: 全サンプル組にテンプレートを適用し、実例キー集合に何割現れるか
    hit = sum(1 for a, b in pairs
              if best.replace("{A}", a).replace("{B}", b) in jset)
    return {"template": best, "coverage": round(hit / len(pairs), 3),
            "checked": len(pairs), "matched": hit}


CAUSE_JA = {
    "missing_a": "親Aの外部IDが移行先に存在しない",
    "missing_b": "親Bの外部IDが移行先に存在しない",
    "missing_both": "親A・親Bの両方が存在しない",
    "parents_ok": "両親は存在するが中間だけ未取込",
    "unknown": "不明(親抽出が未指定のため判定不可)",
}


def build_orphan_table(result: dict, config: JunctionConfig) -> Table:
    """未取込の中間キー一覧をCSV出力用Tableにする(原因つき・アクション可能)。"""
    rows = [[s["key"], s["a"], s["b"], CAUSE_JA.get(s["cause"], s["cause"])]
            for s in result["orphans"]["samples"]]
    return Table(
        columns=["複合キー", "親Aキー", "親Bキー", "未取込の原因"],
        rows=rows, name="未取込一覧",
    )
