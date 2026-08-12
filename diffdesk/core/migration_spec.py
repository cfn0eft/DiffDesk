"""移行定義JSON(マッピング仕様書)の取り込み。

Excel→Salesforce移行で使われる定義JSON(fields配列に excelColumn /
salesforceField / valueMap / truthyValues / normalizeRules / composite 等を持つ形式)を
解析し、DiffDeskの2つの機能に変換する:
- 紐づけ設定のマッピング(変換ルールつきColumnPair) → 投入時の変換を再現した照合
- 多対多検証タブの設定(複合キー・スキップ条件・正規化・外部ID列)
"""
from __future__ import annotations

import re

from .model import DiffDeskError


def parse_migration_spec(data: dict) -> dict:
    """1つの移行定義JSONを解析して正規形にする。"""
    if not isinstance(data, dict) or not isinstance(data.get("fields"), list):
        raise DiffDeskError(
            "移行定義JSONの形式が不正です(fields 配列が見つかりません)。")
    ext_field = str(data.get("externalIdField", "") or "")
    pairs: list[dict] = []
    constants: list[dict] = []
    composite = None

    for i, f in enumerate(data["fields"]):
        if not isinstance(f, dict):
            raise DiffDeskError(f"fields[{i}] の形式が不正です。")
        sf = str(f.get("salesforceField", "") or "")
        if not sf:
            raise DiffDeskError(f"fields[{i}] に salesforceField がありません。")

        # 複合キー項目(source: composite / sourceColumns指定)
        if f.get("source") == "composite" or (
                "sourceColumns" in f and "excelColumn" not in f):
            cols = [str(c) for c in (f.get("sourceColumns") or [])]
            if len(cols) < 2:
                raise DiffDeskError(
                    f"複合キー {sf} の sourceColumns は2列以上必要です。")
            composite = {"target_field": sf,
                         "prefix": str(f.get("prefix", "") or ""),
                         "source_columns": cols}
            continue

        # 定数項目(元データに対応列が無い) → 照合対象外として報告のみ
        if "excelColumn" not in f:
            constants.append({"field": sf,
                              "value": str(f.get("constantValue", ""))})
            continue

        transform: dict = {}
        rules = f.get("normalizeRules") or []
        if rules:
            checked = []
            for r in rules:
                pat = str(r.get("pattern", ""))
                try:
                    re.compile(pat)
                except re.error as e:
                    raise DiffDeskError(f"{sf} の normalizeRules が不正です: {e}")
                checked.append({"pattern": pat,
                                "replacement": str(r.get("replacement", ""))})
            transform["regex_rules"] = checked
        if isinstance(f.get("valueMap"), dict) and f["valueMap"]:
            transform["value_map"] = {str(k): str(v)
                                      for k, v in f["valueMap"].items()}
        if isinstance(f.get("truthyValues"), list):
            transform["truthy_values"] = [str(v) for v in f["truthyValues"]]
        typ = str(f.get("type", "string") or "string")
        if typ in ("date", "number", "boolean"):
            transform["type"] = typ
        if "defaultValue" in f:
            transform["default_value"] = str(f.get("defaultValue", ""))
        # 変換として意味を持つ場合のみ保持(default_valueだけでは変換しない)
        meaningful = any(k in transform for k in
                        ("regex_rules", "value_map", "truthy_values")) \
            or transform.get("type") in ("date", "boolean")
        verify = f.get("verifyExternalId") if isinstance(
            f.get("verifyExternalId"), dict) else None
        pairs.append({
            "col_a": str(f["excelColumn"]),
            "col_b": sf,
            "is_key": bool(ext_field) and sf == ext_field,
            "transform": transform if meaningful else None,
            "verify": verify,
        })

    if not pairs and not composite:
        raise DiffDeskError("移行定義JSONに取り込める項目がありません。")
    return {
        "object": str(data.get("object", "") or ""),
        "external_id_field": ext_field,
        "skip_if_blank": [str(c) for c in (data.get("skipIfBlank") or [])],
        "pairs": pairs,
        "constants": constants,
        "composite": composite,
    }


def build_mapping_pairs(spec: dict) -> list[dict]:
    """紐づけ設定用のペア一覧(ColumnPair.from_dict互換)を返す。"""
    return [{"col_a": p["col_a"], "col_b": p["col_b"], "is_key": p["is_key"],
             "sf_field": None, "transform": p["transform"]}
            for p in spec["pairs"]]


def build_junction_settings(specs: list[dict]) -> dict:
    """複数の移行定義から多対多検証タブの設定値を組み立てる。

    specs のうち composite を持つものを中間オブジェクト定義とみなす。
    親A/親Bの外部ID列は中間定義の verifyExternalId から取る(親定義は任意)。
    """
    junction = next((s for s in specs if s["composite"]), None)
    if junction is None:
        raise DiffDeskError(
            "中間オブジェクトの定義(複合キー項目を持つJSON)が見つかりません。")
    comp = junction["composite"]
    a_col, b_col = comp["source_columns"][0], comp["source_columns"][1]
    template = f'{comp["prefix"]}{{A}}-{{B}}'

    def pair_for(col):
        return next((p for p in junction["pairs"] if p["col_a"] == col), None)

    pa, pb = pair_for(a_col), pair_for(b_col)
    warnings = []
    a_ext = (pa or {}).get("verify", {}).get("field", "") if pa and pa.get("verify") else ""
    b_ext = (pb or {}).get("verify", {}).get("field", "") if pb and pb.get("verify") else ""
    if not a_ext:
        warnings.append(f"親A({a_col})の外部ID列が定義から特定できませんでした。手動で選択してください。")
    if not b_ext:
        warnings.append(f"親B({b_col})の外部ID列が定義から特定できませんでした。手動で選択してください。")

    b_pattern = b_repl = ""
    rules = (pb or {}).get("transform") or {}
    regex_rules = rules.get("regex_rules") or []
    if regex_rules:
        b_pattern = regex_rules[0]["pattern"]
        b_repl = regex_rules[0]["replacement"]
        if len(regex_rules) > 1:
            warnings.append(
                f"親Bの正規化ルールが{len(regex_rules)}件ありますが、先頭の1件のみ適用します。")

    required = junction["skip_if_blank"][0] if junction["skip_if_blank"] else ""
    if len(junction["skip_if_blank"]) > 1:
        warnings.append("skipIfBlank が複数ありますが、先頭の1列のみ適用します。")

    return {
        "settings": {
            "a_source_col": a_col,
            "b_source_col": b_col,
            "a_ext_col": a_ext,
            "b_ext_col": b_ext,
            "j_key_col": junction["external_id_field"],
            "key_template": template,
            "b_regex_pattern": b_pattern,
            "b_regex_replacement": b_repl,
            "required_col": required,
            "j_ref_a_col": (pa or {}).get("col_b", ""),
            "j_ref_b_col": (pb or {}).get("col_b", ""),
        },
        "object": junction["object"],
        "warnings": warnings,
    }
