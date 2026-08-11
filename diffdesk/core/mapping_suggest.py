"""列マッピングの自動提案(LLM不使用・完全ローカル)。

3つの証拠を組み合わせて対応を推定する:

1. 名前一致   — 完全一致 / NFKC正規化一致
2. 意味一致   — 日本語ヘッダー↔Salesforce項目名の類義語辞書と、
                API名のトークン分解(EmployeeNumber__c → {employee, number})
3. 値ベース   — 列の中身(サンプル値)の重なり。日付表記(2020/4/1 vs 2020-04-01)や
                数値表記(100 vs 100.0)の違いは正規化して吸収する

名前・意味・値のスコアを統合し、確信度の高い順に貪欲に割り当てる。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .model import Table

_SAMPLE_ROWS = 1000
_MIN_DISTINCT = 2      # 定数列(全行同じ値)は値ベース対象外
_MIN_SCORE = 0.5

# 日本語ヘッダーによく使われる語 → Salesforce項目名に現れる英語トークン
_JA_TOKENS: dict[str, tuple[str, ...]] = {
    "氏名": ("name",), "名前": ("name",), "姓名": ("name",),
    "姓": ("last", "name"), "名": ("first", "name"),
    "フリガナ": ("kana", "furigana", "phonetic"), "ふりがな": ("kana", "furigana"),
    "会社名": ("company", "account"), "会社": ("company", "account"),
    "取引先": ("account",), "顧客": ("customer", "account", "client"),
    "部署": ("department",), "部門": ("department", "division"),
    "役職": ("title", "position"), "所属": ("department", "unit"),
    "電話番号": ("phone",), "電話": ("phone", "tel"),
    "携帯": ("mobile", "phone"), "FAX": ("fax",),
    "メールアドレス": ("email", "mail"), "メール": ("email", "mail"),
    "住所": ("address", "street"), "郵便番号": ("postal", "zip", "code"),
    "都道府県": ("state", "prefecture"), "市区町村": ("city",),
    "番地": ("street",), "国": ("country",),
    "社員番号": ("employee", "number"), "従業員番号": ("employee", "number"),
    "会員番号": ("member", "number"), "管理番号": ("number", "code", "id"),
    "生年月日": ("birthdate", "birth", "date"), "誕生日": ("birthdate", "birth"),
    "入社日": ("hire", "date", "start"), "開始日": ("start", "date"),
    "終了日": ("end", "date", "close"), "作成日": ("created", "date"),
    "更新日": ("modified", "updated", "date"), "日付": ("date",),
    "金額": ("amount",), "単価": ("price", "unit"), "数量": ("quantity", "qty"),
    "売上": ("revenue", "sales", "amount"), "予算": ("budget",),
    "状態": ("status", "state"), "ステータス": ("status",),
    "区分": ("type", "category", "class"), "種別": ("type", "category"),
    "備考": ("description", "note", "remarks", "memo"),
    "説明": ("description",), "メモ": ("memo", "note"),
    "コード": ("code",), "番号": ("number", "no"), "ID": ("id",),
    "担当者": ("owner", "person", "contact"), "担当": ("owner", "assignee"),
    "URL": ("url", "website", "web"), "サイト": ("website", "site", "web"),
    "業種": ("industry",), "従業員数": ("employees", "number"),
    "評価": ("rating", "score"), "優先度": ("priority",),
}

_DATE_RE = re.compile(r"^(\d{4})[/\-.年](\d{1,2})[/\-.月](\d{1,2})日?$")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).strip().casefold()


def _canon_value(s: str) -> str:
    """値の正規化: NFKC・trim・casefold + 日付/数値/真偽の表記統一。"""
    v = _norm(s)
    if not v:
        return ""
    m = _DATE_RE.match(v)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    if v in ("true", "false"):
        return "1" if v == "true" else "0"
    try:
        f = float(v)
        if f.is_integer():
            return str(int(f))
        return repr(f)
    except ValueError:
        return v


def _header_tokens(name: str) -> set[str]:
    """ヘッダー名をトークン集合に分解する。

    英語系: EmployeeNumber__c → {employee, number} / postal_code → {postal, code}
    日本語系: 類義語辞書に含まれる語を部分一致で拾う(社員番号 → {employee, number})
    """
    tokens: set[str] = set()
    base = unicodedata.normalize("NFKC", name).strip()
    ascii_part = re.sub(r"__c$|__r$", "", base, flags=re.IGNORECASE)
    ascii_part = _CAMEL_RE.sub(" ", ascii_part)
    for t in re.split(r"[^A-Za-z0-9]+", ascii_part):
        t = t.casefold()
        if len(t) >= 2 or t == "id":
            tokens.add(t)
    for ja, en in _JA_TOKENS.items():
        if ja.casefold() in base.casefold():
            tokens.update(en)
    return tokens


def _name_score(a: str, b: str) -> float:
    if a == b:
        return 1.0
    na, nb = _norm(a), _norm(b)
    if na == nb:
        return 0.95
    ta, tb = _header_tokens(a), _header_tokens(b)
    if ta and tb:
        inter = ta & tb
        if inter:
            jac = len(inter) / len(ta | tb)
            return 0.55 + 0.4 * jac  # トークンが1つでも重なれば候補、全一致で0.95
    if len(na) >= 3 and (na in nb or nb in na):
        return 0.7
    return 0.0


@dataclass
class MappingSuggestion:
    col_a: str
    col_b: str
    method: str        # "name" | "value" | "name+value"
    confidence: float  # 0.0〜1.0
    key_candidate: bool = False  # 両側で値がユニーク=紐づけキーの有力候補

    def to_dict(self) -> dict:
        return {
            "col_a": self.col_a, "col_b": self.col_b,
            "is_key": False, "sf_field": None,
            "method": self.method, "confidence": round(self.confidence, 2),
            "key_candidate": self.key_candidate,
        }


def _value_sets(table: Table) -> tuple[dict[str, set[str]], dict[str, bool]]:
    """列ごとの正規化済み値集合と、キー候補性(サンプル内で空なし・重複なし)を返す。"""
    idx = {c: i for i, c in enumerate(table.columns)}
    sets: dict[str, set[str]] = {c: set() for c in table.columns}
    counts: dict[str, int] = {c: 0 for c in table.columns}
    sampled = table.rows[:_SAMPLE_ROWS]
    for row in sampled:
        for c, i in idx.items():
            v = _canon_value(row[i])
            if v:
                sets[c].add(v)
                counts[c] += 1
    uniqueish = {
        c: bool(sampled) and counts[c] == len(sampled) and len(sets[c]) == counts[c]
        for c in table.columns
    }
    return sets, uniqueish


def suggest_mapping(table_a: Table, table_b: Table,
                    user_pairs: list[tuple[str, str]] | None = None
                    ) -> list[MappingSuggestion]:
    sets_a, unique_a = _value_sets(table_a)
    sets_b, unique_b = _value_sets(table_b)
    user_set = {(a, b) for a, b in (user_pairs or [])}

    candidates: list[tuple[float, str, str, str]] = []  # (score, a, b, method)
    for a in table_a.columns:
        sa = sets_a[a]
        for b in table_b.columns:
            if (a, b) in user_set:  # ユーザー辞書の対応は最優先
                candidates.append((1.0, a, b, "辞書"))
                continue
            ns = _name_score(a, b)
            sb = sets_b[b]
            vs = 0.0
            if len(sa) >= _MIN_DISTINCT and len(sb) >= _MIN_DISTINCT:
                vs = len(sa & sb) / min(len(sa), len(sb))
            # 統合: 強い方を主、弱い方を加点(両方の証拠があると確信度が上がる)
            score = max(ns, vs) + 0.15 * min(ns, vs)
            if score < _MIN_SCORE:
                continue
            if ns >= _MIN_SCORE and vs >= _MIN_SCORE:
                method = "name+value"
            elif ns >= vs:
                method = "name"
            else:
                method = "value"
            candidates.append((min(score, 1.0), a, b, method))

    used_a: set[str] = set()
    used_b: set[str] = set()
    picked: list[MappingSuggestion] = []
    for score, a, b, method in sorted(candidates, key=lambda t: -t[0]):
        if a in used_a or b in used_b:
            continue
        used_a.add(a)
        used_b.add(b)
        picked.append(MappingSuggestion(
            a, b, method, score,
            key_candidate=unique_a.get(a, False) and unique_b.get(b, False)))

    order = {c: i for i, c in enumerate(table_a.columns)}
    picked.sort(key=lambda s: order[s.col_a])
    return picked
