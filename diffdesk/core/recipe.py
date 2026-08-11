"""レシピ: ファイルに適用した整形操作の記録と再適用(Power Queryの発想)。

クレンジング・置換・分割などの操作列を名前付きで保存し、
別のファイル(翌月の同形式ファイル等)にワンクリックで再適用できる。
"""
from __future__ import annotations

import json
from pathlib import Path

from . import profile as _profile
from .address import split_address_column
from .clean import clean_columns
from .cluster import apply_value_map
from .edit import (
    concat_columns,
    conditional_column,
    dedupe_rows,
    replace_all,
    split_column,
    substring_column,
)
from .model import DiffDeskError, Table
from .profile import _safe_path

# 操作名 -> (日本語ラベル, 適用関数)。関数は (table, params) -> (table, 概要文字列)
def _op_clean(t: Table, p: dict):
    t, n = clean_columns(t, p["columns"], p["ops"])
    return t, f"{n}セル変更"


def _op_replace(t: Table, p: dict):
    t, n = replace_all(t, p["query"], p.get("replacement", ""),
                       columns=p.get("columns"), regex=p.get("regex", False),
                       case_sensitive=p.get("case_sensitive", True))
    return t, f"{n}セル置換"


def _op_dedupe(t: Table, p: dict):
    t, n = dedupe_rows(t)
    return t, f"{n}行削除"


def _op_split(t: Table, p: dict):
    t, n = split_column(t, p["column"], p["delimiter"])
    return t, f"{n}列に分割"


def _op_split_address(t: Table, p: dict):
    t, n = split_address_column(t, p["column"])
    return t, f"{n}行で住所検出"


def _op_apply_map(t: Table, p: dict):
    t, n = apply_value_map(t, p["column"], p["mapping"])
    return t, f"{n}セル統一"


def _op_concat(t: Table, p: dict):
    t = concat_columns(t, p["columns"], p["new_name"], p.get("separator", ""))
    return t, f"列「{p['new_name']}」作成"


def _op_substring(t: Table, p: dict):
    t = substring_column(t, p["column"], p["new_name"], int(p.get("start", 1)),
                         p.get("length"))
    return t, f"列「{p['new_name']}」作成"


def _op_conditional(t: Table, p: dict):
    t = conditional_column(t, p["column"], p["op"], p.get("value", ""),
                           p["new_name"], p.get("then_value", ""),
                           p.get("else_value", ""))
    return t, f"列「{p['new_name']}」作成"


RECIPE_OPS = {
    "clean": ("一括クレンジング", _op_clean),
    "replace": ("検索・置換", _op_replace),
    "dedupe": ("完全重複行の削除", _op_dedupe),
    "split_column": ("列分割", _op_split),
    "split_address": ("住所分割", _op_split_address),
    "apply_map": ("表記ゆれ統一", _op_apply_map),
    "concat_columns": ("計算列: 結合", _op_concat),
    "substring_column": ("計算列: 切り出し", _op_substring),
    "conditional_column": ("計算列: 条件分岐", _op_conditional),
}


def describe_op(op: dict) -> str:
    """操作レコードを人向けの1行説明にする。"""
    name = op.get("op", "?")
    label = RECIPE_OPS.get(name, (name, None))[0]
    p = op.get("params", {})
    target = p.get("column") or "、".join(p.get("columns", [])[:3]) or ""
    return f"{label}" + (f"({target})" if target else "")


def apply_recipe(table: Table, ops: list[dict]) -> tuple[Table, list[str]]:
    """操作列を順に適用し、(結果Table, 各操作の結果概要) を返す。"""
    logs: list[str] = []
    for op in ops:
        name = op.get("op")
        if name not in RECIPE_OPS:
            raise DiffDeskError(f"不明なレシピ操作です: {name}", op=name)
        label, fn = RECIPE_OPS[name]
        try:
            table, summary = fn(table, op.get("params", {}))
        except DiffDeskError as e:
            raise DiffDeskError(f"レシピ「{label}」の適用に失敗: {e.message}")
        logs.append(f"{describe_op(op)}: {summary}")
    return table, logs


# ---------------------------------------------------------------- 保存
def _recipe_dir(directory: Path | None) -> Path:
    return (directory or _profile.DEFAULT_PROFILE_DIR.parent) / "recipes"


def save_recipe(name: str, ops: list[dict], *, directory: Path | None = None) -> Path:
    if not ops:
        raise DiffDeskError("保存する操作がありません。")
    d = _recipe_dir(directory)
    d.mkdir(parents=True, exist_ok=True)
    path = _safe_path(name, d)
    path.write_text(json.dumps({"version": 1, "name": name, "ops": ops},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_recipe(name: str, *, directory: Path | None = None) -> list[dict]:
    path = _safe_path(name, _recipe_dir(directory))
    if not path.exists():
        raise DiffDeskError(f"レシピが見つかりません: {name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("ops", [])


def list_recipes(*, directory: Path | None = None) -> list[str]:
    d = _recipe_dir(directory)
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.json"))
