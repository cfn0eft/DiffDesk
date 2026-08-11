"""単体ファイルの検証(キー重複・必須・形式チェック)。"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .model import DiffDeskError, Table

_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")
_PHONE_RE = re.compile(r"^[\d\-() +]{6,}$")

FORMAT_CHECKS = {
    "email": ("メールアドレス形式", lambda v: bool(_EMAIL_RE.match(v))),
    "phone": ("電話番号形式", lambda v: bool(_PHONE_RE.match(v))),
    "number": ("数値", lambda v: _is_number(v)),
    "date_iso": ("日付(yyyy-MM-dd)", lambda v: bool(re.match(r"^\d{4}-\d{2}-\d{2}$", v))),
}


def _is_number(v: str) -> bool:
    try:
        float(v)
        return True
    except ValueError:
        return False


@dataclass
class ValidationRules:
    key_columns: list[str] = field(default_factory=list)      # 重複チェック対象(複合可)
    required_columns: list[str] = field(default_factory=list)  # 空セル禁止
    formats: dict[str, str] = field(default_factory=dict)      # 列名 -> FORMAT_CHECKSのキー
    max_lengths: dict[str, int] = field(default_factory=dict)  # 列名 -> 最大文字数
    allowed_values: dict[str, list[str]] = field(default_factory=dict)  # 列名 -> 許可値(ピックリスト)
    ranges: dict[str, list[float | None]] = field(default_factory=dict)  # 列名 -> [最小, 最大](検査値の基準範囲等。Noneは片側なし)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ValidationRules":
        return cls(
            key_columns=[str(c) for c in d.get("key_columns", [])],
            required_columns=[str(c) for c in d.get("required_columns", [])],
            formats={str(k): str(v) for k, v in d.get("formats", {}).items()},
            max_lengths={str(k): int(v) for k, v in d.get("max_lengths", {}).items()},
            allowed_values={str(k): [str(x) for x in v]
                            for k, v in d.get("allowed_values", {}).items()},
            ranges={str(k): [None if x is None else float(x) for x in v]
                    for k, v in d.get("ranges", {}).items()},
        )


@dataclass
class ValidationIssue:
    row: int          # 1始まりのデータ行番号
    column: str
    code: str         # duplicate_key / required_empty / format / max_length
    message: str
    value: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def validate_table(table: Table, rules: ValidationRules,
                   *, limit: int = 1000) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    def add(issue: ValidationIssue) -> bool:
        issues.append(issue)
        return len(issues) >= limit

    for fmt_col, fmt_name in rules.formats.items():
        if fmt_name not in FORMAT_CHECKS:
            raise DiffDeskError(f"不明な形式チェックです: {fmt_name}", format=fmt_name)

    if rules.key_columns:
        key_idx = [table.col_index(c) for c in rules.key_columns]
        seen: dict[tuple[str, ...], int] = {}
        for ri, row in enumerate(table.rows, start=1):
            key = tuple(row[i].strip() for i in key_idx)
            if all(v == "" for v in key):
                continue
            if key in seen:
                if add(ValidationIssue(
                        row=ri, column="+".join(rules.key_columns),
                        code="duplicate_key",
                        message=f"キー重複: {'/'.join(key)} ({seen[key]}行目と重複)",
                        value="/".join(key))):
                    return issues
            else:
                seen[key] = ri

    req_idx = [(c, table.col_index(c)) for c in rules.required_columns]
    fmt_idx = [(c, table.col_index(c), f) for c, f in rules.formats.items()]
    len_idx = [(c, table.col_index(c), n) for c, n in rules.max_lengths.items()]
    allow_idx = [(c, table.col_index(c), {v.strip() for v in vals})
                 for c, vals in rules.allowed_values.items()]
    range_idx = [(c, table.col_index(c),
                  (v[0] if len(v) > 0 else None), (v[1] if len(v) > 1 else None))
                 for c, v in rules.ranges.items()]

    for ri, row in enumerate(table.rows, start=1):
        for col, i in req_idx:
            if row[i].strip() == "":
                if add(ValidationIssue(row=ri, column=col, code="required_empty",
                                       message=f"必須列 {col} が空です")):
                    return issues
        for col, i, fmt in fmt_idx:
            v = row[i].strip()
            if v and not FORMAT_CHECKS[fmt][1](v):
                if add(ValidationIssue(
                        row=ri, column=col, code="format", value=v,
                        message=f"{col} が{FORMAT_CHECKS[fmt][0]}ではありません: {v}")):
                    return issues
        for col, i, n in len_idx:
            if len(row[i]) > n:
                if add(ValidationIssue(
                        row=ri, column=col, code="max_length", value=row[i],
                        message=f"{col} が最大文字数 {n} を超えています ({len(row[i])}文字)")):
                    return issues
        for col, i, allowed in allow_idx:
            v = row[i].strip()
            if v and v not in allowed:
                if add(ValidationIssue(
                        row=ri, column=col, code="allowed_values", value=v,
                        message=f"{col} が許可値にありません: {v}")):
                    return issues
        for col, i, lo, hi in range_idx:
            v = row[i].strip()
            if not v:
                continue
            try:
                num = float(v)
            except ValueError:
                if add(ValidationIssue(
                        row=ri, column=col, code="range", value=v,
                        message=f"{col} が数値ではないため範囲判定できません: {v}")):
                    return issues
                continue
            if (lo is not None and num < lo) or (hi is not None and num > hi):
                lo_s = "" if lo is None else str(lo)
                hi_s = "" if hi is None else str(hi)
                if add(ValidationIssue(
                        row=ri, column=col, code="range", value=v,
                        message=f"{col} が基準範囲外です: {v}(範囲 {lo_s}〜{hi_s})")):
                    return issues
    return issues
