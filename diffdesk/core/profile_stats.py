"""ファイル健康診断: 列プロファイルと基準(ベースライン)との比較警告。

Great Expectations の考え方を軽量化したもの。列ごとの統計をプロファイルし、
保存した基準と比較して「いつもと違う」変化を警告する。
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from . import profile as _profile
from .model import DiffDeskError, Table
from .profile import _safe_path

_TOP_VALUES = 5
_NEW_VALUE_SAMPLE = 5
_DATE_RE = re.compile(r"^\d{4}[/\-.年]\d{1,2}[/\-.月]\d{1,2}日?$")


def _guess_type(values: list[str]) -> str:
    if not values:
        return "空"
    n_num = n_date = 0
    for v in values:
        if _DATE_RE.match(v):
            n_date += 1
        else:
            try:
                float(v)
                n_num += 1
            except ValueError:
                pass
    n = len(values)
    if n_date / n > 0.8:
        return "日付"
    if n_num / n > 0.8:
        return "数値"
    return "文字列"


def profile_table(table: Table, *, sample_rows: int = 100_000) -> dict:
    """列ごとの統計プロファイルを返す(JSON化可能)。"""
    rows = table.rows[:sample_rows]
    n = len(rows)
    columns = []
    for i, col in enumerate(table.columns):
        values = [row[i] for row in rows]
        non_empty = [v for v in values if v.strip()]
        counter = Counter(non_empty)
        columns.append({
            "name": col,
            "empty_rate": round(1 - len(non_empty) / n, 4) if n else 0.0,
            "unique": len(counter),
            "type": _guess_type(non_empty[:1000]),
            "top_values": [{"value": v, "count": c} for v, c in counter.most_common(_TOP_VALUES)],
            "distinct_sample": sorted(counter)[:2000],  # 未知値検知用(上限あり)
            "max_length": max((len(v) for v in non_empty), default=0),
        })
    return {"version": 1, "rows": len(table.rows), "columns": columns}


def compare_profiles(baseline: dict, current: dict, *,
                     row_change_threshold: float = 0.3,
                     empty_rate_threshold: float = 0.15) -> list[dict]:
    """基準プロファイルと現在を比較し、警告リストを返す。

    各警告: {level: "warn"|"info", message}
    """
    warnings: list[dict] = []

    base_rows, cur_rows = baseline.get("rows", 0), current.get("rows", 0)
    if base_rows and abs(cur_rows - base_rows) / base_rows >= row_change_threshold:
        pct = (cur_rows - base_rows) / base_rows * 100
        warnings.append({"level": "warn",
                         "message": f"行数が基準から{pct:+.0f}%変動しています"
                                    f"(基準{base_rows}行 → 今回{cur_rows}行)"})

    base_cols = {c["name"]: c for c in baseline.get("columns", [])}
    cur_cols = {c["name"]: c for c in current.get("columns", [])}

    for name in cur_cols.keys() - base_cols.keys():
        warnings.append({"level": "warn", "message": f"基準にない新しい列があります: {name}"})
    for name in base_cols.keys() - cur_cols.keys():
        warnings.append({"level": "warn", "message": f"基準にあった列がありません: {name}"})

    for name in base_cols.keys() & cur_cols.keys():
        b, c = base_cols[name], cur_cols[name]
        diff_empty = c["empty_rate"] - b["empty_rate"]
        if diff_empty >= empty_rate_threshold:
            warnings.append({"level": "warn",
                             "message": f"列「{name}」の空欄率が急増: "
                                        f"{b['empty_rate']:.0%} → {c['empty_rate']:.0%}"})
        if b.get("type") and c.get("type") and b["type"] != c["type"]:
            warnings.append({"level": "warn",
                             "message": f"列「{name}」の型が変化: {b['type']} → {c['type']}"})
        # カテゴリ列(基準でユニーク数が少ない)の未知の値
        base_sample = set(b.get("distinct_sample", []))
        if base_sample and b.get("unique", 0) <= 50 and len(base_sample) >= b.get("unique", 0):
            new_values = [v for v in c.get("distinct_sample", []) if v not in base_sample]
            if new_values:
                shown = "、".join(new_values[:_NEW_VALUE_SAMPLE])
                warnings.append({"level": "warn",
                                 "message": f"列「{name}」に基準にない値: {shown}"
                                            + ("…" if len(new_values) > _NEW_VALUE_SAMPLE else "")})
    if not warnings:
        warnings.append({"level": "info", "message": "基準からの目立った変化はありません。"})
    return warnings


# ---------------------------------------------------------------- 基準の保存
def _baseline_dir(directory: Path | None) -> Path:
    return (directory or _profile.DEFAULT_PROFILE_DIR.parent) / "baselines"


def save_baseline(name: str, profile: dict, *, directory: Path | None = None) -> Path:
    d = _baseline_dir(directory)
    d.mkdir(parents=True, exist_ok=True)
    path = _safe_path(name, d)
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_baseline(name: str, *, directory: Path | None = None) -> dict:
    path = _safe_path(name, _baseline_dir(directory))
    if not path.exists():
        raise DiffDeskError(f"基準プロファイルが見つかりません: {name}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_baselines(*, directory: Path | None = None) -> list[str]:
    d = _baseline_dir(directory)
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.json"))
