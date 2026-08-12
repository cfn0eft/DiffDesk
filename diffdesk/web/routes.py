"""APIエンドポイント。ロジックは全て diffdesk.core に委譲する。"""
from __future__ import annotations

import json
import urllib.parse

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import Response

from ..core import (
    ANONYMIZE_MODES,
    CLEAN_OPS,
    COLUMN_OPS,
    add_known_diff,
    add_user_pairs,
    analyze_errors,
    append_history,
    apply_known_diffs,
    apply_manual_pairs,
    DiffDeskError,
    JunctionConfig,
    build_junction_settings,
    build_mapping_pairs,
    build_orphan_table,
    infer_key_template,
    parse_migration_spec,
    verify_junction,
    add_manual_link,
    build_link_prompt,
    clear_manual_links,
    list_unmatched,
    load_manual_links,
    pair_similarity,
    parse_link_answer,
    remove_manual_link,
    suggest_links,
    validate_manual_pair,
    clear_history,
    clear_known_diffs,
    column_diff_summary,
    load_history,
    load_known_diffs,
    load_user_dict,
    remove_known_diff,
    remove_user_pair,
    anonymize_columns,
    apply_value_map,
    build_html_report,
    build_linked_table,
    build_restore_table,
    build_retry_table,
    build_undo_delete_table,
    build_verification,
    cluster_column,
    compare_profiles,
    concat_columns,
    conditional_column,
    crosstab,
    describe_op,
    apply_recipe,
    fuzzy_match,
    list_recipes,
    load_recipe,
    save_recipe,
    substring_column,
    profile_table,
    split_address_column,
    split_column,
    build_verification_table,
    build_verification_xlsx,
    suggest_mapping,
    DiffOptions,
    MappingConfig,
    Profile,
    RowFilter,
    Table,
    apply_merge,
    build_delete_table,
    build_report_table,
    build_sdl,
    build_upsert_table,
    build_xlsx_report,
    clean_columns,
    concat_tables,
    dedupe_rows,
    detect_encoding,
    diff_tables,
    is_excel_filename,
    list_sheets,
    load_table,
    replace_all,
    search_cells,
    validate_table,
    vlookup_join,
    write_csv,
    write_xlsx,
)
from ..core.profile import (
    delete_profile,
    list_profiles,
    load_profile,
    save_profile,
)
from ..core.validate import ValidationRules
from . import schemas as sc
from .sessions import store

router = APIRouter(prefix="/api")

PREVIEW_ROWS = 50


# ---------------------------------------------------------------- helpers

def _preview(table: Table, limit: int = PREVIEW_ROWS) -> dict:
    return {
        "columns": table.columns,
        "rows": table.rows[:limit],
        "total_rows": len(table.rows),
        "name": table.name,
        "sheet": table.sheet,
        "source_encoding": table.source_encoding,
    }


def _file_info(entry, table: Table | None) -> dict:
    info = {
        "file_id": entry.file_id,
        "filename": entry.filename,
        "is_excel": is_excel_filename(entry.filename),
        "parse_params": entry.parse_params,
    }
    if info["is_excel"] and entry.raw:
        info["sheets"] = list_sheets(entry.raw)
        info["detected_encoding"] = None
        info["confidence"] = None
    elif entry.raw:
        enc, conf = detect_encoding(entry.raw)
        info["detected_encoding"] = enc
        info["confidence"] = conf
        info["sheets"] = None
    else:
        info["sheets"] = None
        info["detected_encoding"] = None
        info["confidence"] = None
    if table is not None:
        info["preview"] = _preview(table)
    return info


def _safe_stem(name: str, limit: int = 40) -> str:
    """ファイル名から識別用の安全な語幹を作る(拡張子・危険文字を除去)。"""
    import re as _re
    from pathlib import PurePath
    stem = PurePath(str(name or "")).stem
    stem = _re.sub(r'[\\/:*?"<>|\s]+', "_", stem).strip("_")
    return stem[:limit] or "無題"


def _report_name(base: str, *names: str, ext: str) -> str:
    """識別できるレポートファイル名: base_A_vs_B_YYYYMMDD_HHMM.ext"""
    from datetime import datetime
    stems = [_safe_stem(n) for n in names if n]
    middle = "_vs_".join(stems)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    parts = [base] + ([middle] if middle else []) + [stamp]
    return "_".join(parts) + "." + ext


def _download(content: bytes, filename: str, media_type: str) -> Response:
    quoted = urllib.parse.quote(filename)
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
        },
    )


def _csv_or_xlsx(table: Table, fmt: str, encoding: str, filename_base: str,
                 errors: str = "strict", delimiter: str = ",") -> Response:
    if fmt == "xlsx":
        return _download(write_xlsx(table), f"{filename_base}.xlsx",
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    raw = write_csv(table, encoding=encoding, delimiter=delimiter, errors=errors)
    return _download(raw, f"{filename_base}.csv", "text/csv")


# ---------------------------------------------------------------- files

@router.post("/files")
async def upload_file(file: UploadFile = File(...)):
    raw = await file.read()
    entry = store.add_file(file.filename or "無題.csv", raw)
    table = load_table(raw, entry.filename)
    params = {"header_row": 1}
    if not is_excel_filename(entry.filename):
        params["encoding"] = table.source_encoding
    else:
        params["sheet"] = table.sheet
    store.set_table(entry.file_id, table, params)
    return _file_info(entry, table)


@router.post("/files/{file_id}/parse")
def parse_file(file_id: str, req: sc.ParseRequest):
    entry = store.get_file(file_id)
    if not entry.raw:
        raise_no_raw()
    table = load_table(entry.raw, entry.filename, encoding=req.encoding,
                       delimiter=req.delimiter, sheet=req.sheet,
                       header_row=req.header_row - 1)
    params = req.model_dump(exclude_none=True)
    if not is_excel_filename(entry.filename):
        params.setdefault("encoding", table.source_encoding)
    store.set_table(file_id, table, params)
    return _file_info(entry, table)


def raise_no_raw():
    from ..core import DiffDeskError
    raise DiffDeskError("このファイルは生成データのため再パースできません。")


@router.get("/files")
def list_files():
    result = []
    for e in store.list_files():
        result.append({
            "file_id": e.file_id,
            "filename": e.filename,
            "columns": e.table.columns if e.table else [],
            "total_rows": len(e.table.rows) if e.table else 0,
        })
    return {"files": result}


@router.get("/files/{file_id}/info")
def get_file_info(file_id: str):
    """読込設定・プレビューを含む詳細情報(役割割当・読込設定パネル用)。"""
    entry = store.get_file(file_id)
    return _file_info(entry, entry.table)


@router.get("/files/{file_id}")
def get_file(file_id: str, offset: int = 0, limit: int = 1000):
    table = store.get_table(file_id)
    limit = max(1, min(limit, 10000))
    return {
        "columns": table.columns,
        "rows": table.rows[offset:offset + limit],
        "offset": offset,
        "total_rows": len(table.rows),
        "filename": store.get_file(file_id).filename,
    }


@router.put("/files/{file_id}/table")
def update_table(file_id: str, req: sc.TableUpdateRequest):
    entry = store.get_file(file_id)
    table = Table.from_dict({"columns": req.columns, "rows": req.rows,
                             "name": entry.filename})
    store.set_table(file_id, table)
    return {"ok": True, "total_rows": len(table.rows)}


@router.delete("/files/{file_id}")
def remove_file(file_id: str):
    store.delete_file(file_id)
    return {"ok": True}


@router.post("/files/{file_id}/clean")
def clean_file(file_id: str, req: sc.CleanRequest):
    table = store.get_table(file_id).copy()
    table, changed = clean_columns(table, req.columns, req.ops)
    store.set_table(file_id, table)
    store.log_op(file_id, "clean", {"columns": req.columns, "ops": req.ops})
    return {"changed_cells": changed, "preview": _preview(table)}


@router.get("/clean-ops")
def clean_ops():
    ops = [{"id": k, "label": v[0]} for k, v in CLEAN_OPS.items()]
    ops += [{"id": k, "label": label} for k, label in COLUMN_OPS.items()]
    return {"ops": ops}


@router.get("/anonymize-modes")
def anonymize_modes():
    return {"modes": [{"id": k, "label": v} for k, v in ANONYMIZE_MODES.items()]}


@router.post("/files/{file_id}/clusters")
def get_clusters(file_id: str, req: sc.ClusterRequest):
    table = store.get_table(file_id)
    clusters = cluster_column(table, req.column)
    return {"count": len(clusters), "clusters": [c.to_dict() for c in clusters]}


@router.post("/files/{file_id}/apply-map")
def apply_map(file_id: str, req: sc.ApplyMapRequest):
    table = store.get_table(file_id).copy()
    table, changed = apply_value_map(table, req.column, req.mapping)
    store.set_table(file_id, table)
    store.log_op(file_id, "apply_map", {"column": req.column, "mapping": req.mapping})
    return {"changed": changed}


@router.post("/files/{file_id}/analyze-errors")
def analyze_error_file(file_id: str):
    table = store.get_table(file_id)
    return analyze_errors(table).to_dict()


@router.post("/export/retry/{file_id}")
def export_retry(file_id: str, req: sc.ExportTableRequest):
    table = store.get_table(file_id)
    retry = build_retry_table(table)
    raw = write_csv(retry, encoding=req.encoding, errors=req.errors)
    return _download(raw, _report_name("再投入用", store.get_file(file_id).filename, ext="csv"), "text/csv")


@router.post("/files/{file_id}/anonymize")
def anonymize_file(file_id: str, req: sc.AnonymizeRequest):
    table = store.get_table(file_id)
    out, changed = anonymize_columns(table, req.spec)
    entry = store.add_table_as_file(f"{store.get_file(file_id).filename}_匿名化.csv", out)
    info = _file_info(entry, out)
    info["changed"] = changed
    return info


@router.post("/files/{file_id}/split-column")
def split_column_file(file_id: str, req: sc.SplitColumnRequest):
    table = store.get_table(file_id).copy()
    table, n_parts = split_column(table, req.column, req.delimiter)
    store.set_table(file_id, table)
    store.log_op(file_id, "split_column",
                 {"column": req.column, "delimiter": req.delimiter})
    return {"parts": n_parts, "preview": _preview(table)}


@router.post("/files/{file_id}/column-values")
def column_values(file_id: str, req: sc.ColumnValuesRequest):
    """列のユニーク値一覧(許可値リストの自動生成用)。"""
    table = store.get_table(file_id)
    i = table.col_index(req.column)
    values: list[str] = []
    seen: set[str] = set()
    for row in table.rows:
        v = row[i].strip()
        if v and v not in seen:
            seen.add(v)
            values.append(v)
            if len(values) >= max(1, min(req.limit, 1000)):
                break
    return {"values": values, "truncated": len(values) >= req.limit}


@router.post("/files/{file_id}/validate")
def validate_file(file_id: str, req: sc.ValidateRequest):
    table = store.get_table(file_id)
    rules = ValidationRules(
        key_columns=req.key_columns,
        required_columns=req.required_columns,
        formats=req.formats,
        max_lengths=req.max_lengths,
        allowed_values=req.allowed_values,
        ranges=req.ranges,
    )
    issues = validate_table(table, rules)
    return {"count": len(issues), "issues": [i.to_dict() for i in issues[:500]]}


@router.post("/files/{file_id}/dedupe")
def dedupe_file(file_id: str):
    table = store.get_table(file_id).copy()
    table, removed = dedupe_rows(table)
    store.set_table(file_id, table)
    store.log_op(file_id, "dedupe", {})
    return {"removed": removed, "total_rows": len(table.rows)}


@router.post("/files/{file_id}/search")
def search_file(file_id: str, req: sc.SearchRequest):
    table = store.get_table(file_id)
    hits = search_cells(table, req.query, columns=req.columns, regex=req.regex,
                        case_sensitive=req.case_sensitive)
    return {"count": len(hits), "hits": hits}


@router.post("/files/{file_id}/replace")
def replace_file(file_id: str, req: sc.ReplaceRequest):
    table = store.get_table(file_id).copy()
    table, count = replace_all(table, req.query, req.replacement,
                               columns=req.columns, regex=req.regex,
                               case_sensitive=req.case_sensitive)
    store.set_table(file_id, table)
    store.log_op(file_id, "replace", {
        "query": req.query, "replacement": req.replacement,
        "columns": req.columns, "regex": req.regex,
        "case_sensitive": req.case_sensitive})
    return {"replaced": count}


@router.post("/files/concat")
def concat_files(req: sc.ConcatRequest):
    tables = [store.get_table(fid) for fid in req.file_ids]
    out = concat_tables(tables, mode=req.mode)
    entry = store.add_table_as_file("結合結果.csv", out)
    return _file_info(entry, out)


@router.post("/files/{file_id}/enrich")
def enrich_file(file_id: str, req: sc.EnrichRequest):
    a = store.get_table(file_id)
    b = store.get_table(req.other_file_id)
    out, unmatched = vlookup_join(
        a, b,
        key_pairs=[(p[0], p[1]) for p in req.key_pairs],
        add_columns=req.add_columns,
        options=DiffOptions.from_dict(req.options),
    )
    entry = store.add_table_as_file("列付加結果.csv", out)
    info = _file_info(entry, out)
    info["unmatched"] = unmatched
    return info


# ---------------------------------------------------------------- mapping/diff

def _diff_with_known(diff_id: str):
    """保存済み差分に手動紐づけ→既知差分の順で適用して返す(元は変更しない)。

    手動紐づけはキーの組でワークスペースに永続化されるため、同じファイルで
    差分を再実行しても自動で再適用される(該当行がない組は黙って無視)。
    """
    diff = apply_manual_pairs(store.get_diff(diff_id), load_manual_links())
    return apply_known_diffs(diff, load_known_diffs())


# ---------------------------------------------------------------- 手動紐づけ

@router.get("/diff/{diff_id}/manual-pairs")
def get_manual_pairs(diff_id: str):
    store.get_diff(diff_id)
    return {"pairs": load_manual_links()}


@router.post("/diff/{diff_id}/manual-pairs")
def add_manual_pair(diff_id: str, req: sc.ManualPairRequest):
    pair = validate_manual_pair({"key_a": req.key_a, "key_b": req.key_b})
    applied = _diff_with_known(diff_id)
    statuses = {r.key: r.status for r in applied.rows}
    if statuses.get(tuple(pair["key_a"])) != "only_a":
        raise DiffDeskError(
            f"基準(A)側のキー {'/'.join(pair['key_a'])} は未対応(Aのみ)の行ではありません。")
    if statuses.get(tuple(pair["key_b"])) != "only_b":
        raise DiffDeskError(
            f"比較(B)側のキー {'/'.join(pair['key_b'])} は未対応(Bのみ)の行ではありません。")
    pairs = add_manual_link({**pair, "note": req.note, "score": req.score})
    return {"pairs": pairs, "count": len(pairs)}


@router.delete("/diff/{diff_id}/manual-pairs/{index}")
def delete_manual_pair(diff_id: str, index: int):
    pairs = remove_manual_link(index)
    return {"pairs": pairs, "count": len(pairs)}


@router.delete("/diff/{diff_id}/manual-pairs")
def clear_manual_pairs(diff_id: str):
    clear_manual_links()
    return {"pairs": [], "count": 0}


@router.get("/diff/{diff_id}/unmatched")
def unmatched_rows(diff_id: str, side: str, rank_for: str = ""):
    """未対応行の一覧。rank_for=反対側行のキー(JSON配列)を渡すと一致率順。"""
    rank_key = None
    if rank_for:
        try:
            parsed = json.loads(rank_for)
            if isinstance(parsed, list):
                rank_key = [str(k) for k in parsed]
        except json.JSONDecodeError:
            pass  # 並べ替えなしで返す
    return {"rows": list_unmatched(_diff_with_known(diff_id), side,
                                   rank_for=rank_key)}


@router.post("/diff/{diff_id}/pair-preview")
def pair_preview(diff_id: str, req: sc.ManualPairRequest):
    """紐づけ前の類似度プレビュー(確認ダイアログ・ドラッグ中ガイド用)。"""
    return pair_similarity(_diff_with_known(diff_id), req.key_a, req.key_b)


@router.post("/diff/{diff_id}/link-suggest")
def link_suggest(diff_id: str, req: sc.LinkSuggestRequest):
    """未対応行同士のおすすめ紐づけ候補(スコア順・1対1)。"""
    return {"candidates": suggest_links(_diff_with_known(diff_id),
                                        threshold=req.threshold, limit=req.limit)}


@router.get("/diff/{diff_id}/link-prompt")
def link_prompt(diff_id: str):
    """Web版の対話AIに貼り付ける紐づけ判定プロンプトを生成(AIは呼ばない)。"""
    return build_link_prompt(_diff_with_known(diff_id))


@router.post("/diff/{diff_id}/link-import")
def link_import(diff_id: str, req: sc.LinkImportRequest):
    """AI回答テキストからJSONを抽出し、実在する未対応行の組だけ候補として返す。"""
    return parse_link_answer(_diff_with_known(diff_id), req.text)


@router.post("/automap")
def automap(req: sc.AutomapRequest):
    a = store.get_table(req.file_a)
    b = store.get_table(req.file_b)
    user_pairs = [(e["col_a"], e["col_b"]) for e in load_user_dict()]
    suggestions = suggest_mapping(a, b, user_pairs=user_pairs)
    return {
        "pairs": [s.to_dict() for s in suggestions],
        "by_name": sum(1 for s in suggestions if "name" in s.method),
        "by_value": sum(1 for s in suggestions if "value" in s.method),
        "by_dict": sum(1 for s in suggestions if s.method == "辞書"),
    }


@router.post("/diff")
def run_diff(req: sc.DiffRequest):
    a = store.get_table(req.file_a)
    b = store.get_table(req.file_b)
    mapping = MappingConfig.from_dict(req.mapping)
    options = DiffOptions.from_dict(req.options)
    row_filter = RowFilter.from_dict(req.row_filter)
    result = diff_tables(a, b, mapping, options, row_filter)
    diff_id = store.add_diff(result)
    # 照合履歴に記録(既知差分適用後のサマリーで)
    known_applied = apply_known_diffs(result, load_known_diffs())
    v = build_verification(known_applied)
    append_history({
        "name_a": result.name_a, "name_b": result.name_b,
        "rows_a": v.rows_a, "rows_b": v.rows_b,
        "same": v.same, "changed": v.changed,
        "only_a": v.only_a, "only_b": v.only_b,
        "match_rate": round(v.to_dict()["match_rate"], 4),
        "passed": v.passed,
    })
    return {
        "diff_id": diff_id,
        "summary": result.summary,
        "duplicates_a": [list(k) for k in result.duplicates_a[:100]],
        "duplicates_b": [list(k) for k in result.duplicates_b[:100]],
        "columns_a": [p.col_a for p in mapping.pairs],
        "columns_b": [p.col_b for p in mapping.pairs],
        # キーなし比較では列の🔑表示は意味を持たないので落とす
        "key_flags": [p.is_key if mapping.key_mode == "columns" else False
                      for p in mapping.pairs],
        "key_mode": mapping.key_mode,
    }


@router.get("/diff/{diff_id}/rows")
def diff_rows(diff_id: str, status: str = "", offset: int = 0, limit: int = 200):
    result = _diff_with_known(diff_id)
    statuses = set(status.split(",")) if status else None
    rows = [r for r in result.rows if statuses is None or r.status in statuses]
    limit = max(1, min(limit, 2000))
    return {
        "total": len(rows),
        "offset": offset,
        "rows": [r.to_dict() for r in rows[offset:offset + limit]],
    }


@router.get("/diff/{diff_id}/verify")
def verify_diff(diff_id: str, only_b_is_error: bool = True):
    result = _diff_with_known(diff_id)
    return build_verification(result, only_b_is_error=only_b_is_error).to_dict()


@router.post("/diff/{diff_id}/merge")
def merge_diff(diff_id: str, req: sc.MergeRequest):
    result = _diff_with_known(diff_id)
    out = apply_merge(result, req.choices, include_only_b=req.include_only_b)
    entry = store.add_table_as_file("マージ結果.csv", out)
    return _file_info(entry, out)


# ---------------------------------------------------------------- export

@router.post("/export/table/{file_id}")
def export_table(file_id: str, req: sc.ExportTableRequest):
    table = store.get_table(file_id)
    base = req.filename or (store.get_file(file_id).filename.rsplit(".", 1)[0] or "export")
    return _csv_or_xlsx(table, req.format, req.encoding, base,
                        errors=req.errors, delimiter=req.delimiter)


@router.post("/export/upsert/{diff_id}")
def export_upsert(diff_id: str, req: sc.ExportUpsertRequest):
    result = _diff_with_known(diff_id)
    include = set()
    if req.include_insert:
        include.add("only_a")
    if req.include_update:
        include.add("changed")
    table = build_upsert_table(result, external_id_col_a=req.external_id,
                               include=include)
    raw = write_csv(table, encoding=req.encoding, errors=req.errors)
    return _download(raw, _report_name("アップサート", result.name_a, result.name_b, ext="csv"), "text/csv")


@router.post("/export/delete/{diff_id}")
def export_delete(diff_id: str, req: sc.ExportDeleteRequest):
    result = _diff_with_known(diff_id)
    table = build_delete_table(result, id_col_b=req.id_col_b)
    raw = write_csv(table, encoding=req.encoding)
    return _download(raw, _report_name("削除用", result.name_a, result.name_b, ext="csv"), "text/csv")


@router.get("/export/sdl/{diff_id}")
def export_sdl(diff_id: str):
    result = _diff_with_known(diff_id)
    return _download(build_sdl(result).encode("utf-8"), _report_name("マッピング", result.name_a, result.name_b, ext="sdl"), "text/plain")


@router.post("/export/report/{diff_id}")
def export_report(diff_id: str, req: sc.ExportReportRequest):
    result = _diff_with_known(diff_id)
    if req.format == "xlsx":
        return _download(build_xlsx_report(result), _report_name("照合レポート", result.name_a, result.name_b, ext="xlsx"),
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    table = build_report_table(result)
    raw = write_csv(table, encoding=req.encoding)
    return _download(raw, _report_name("照合レポート", result.name_a, result.name_b, ext="csv"), "text/csv")


# ---------------------------------------------------------------- 移行定義JSON

@router.post("/migration-spec/mapping")
def migration_spec_mapping(req: sc.MigrationSpecRequest):
    """移行定義JSONを紐づけ設定用のマッピング(変換ルールつき)に変換。"""
    spec = parse_migration_spec(req.spec)
    pairs = build_mapping_pairs(spec)
    return {
        "pairs": pairs,
        "object": spec["object"],
        "external_id_field": spec["external_id_field"],
        "constants": spec["constants"],
        "transform_count": sum(1 for p in pairs if p["transform"]),
        "has_composite": spec["composite"] is not None,
    }


@router.post("/migration-spec/junction")
def migration_spec_junction(req: sc.MigrationSpecsRequest):
    """移行定義JSON(複数可)から多対多検証タブの設定を組み立てる。"""
    if not req.specs:
        raise DiffDeskError("移行定義JSONが指定されていません。")
    specs = [parse_migration_spec(s) for s in req.specs]
    return build_junction_settings(specs)


# ---------------------------------------------------------------- 多対多検証

def _junction_inputs(req: sc.JunctionVerifyRequest):
    return (store.get_table(req.file_source),
            store.get_table(req.file_a) if req.file_a else None,
            store.get_table(req.file_b) if req.file_b else None,
            store.get_table(req.file_j),
            JunctionConfig.from_dict(req.config))


@router.post("/junction-verify/infer-template")
def junction_infer_template(req: sc.InferTemplateRequest):
    """中間キーの実例から複合キーの形式({A}-{B}等)を自動推定する。"""
    return infer_key_template(
        store.get_table(req.file_source), store.get_table(req.file_j),
        a_source_col=req.a_source_col, b_source_col=req.b_source_col,
        j_key_col=req.j_key_col,
        a_regex_pattern=req.a_regex_pattern,
        a_regex_replacement=req.a_regex_replacement,
        b_regex_pattern=req.b_regex_pattern,
        b_regex_replacement=req.b_regex_replacement)


@router.post("/junction-verify")
def junction_verify(req: sc.JunctionVerifyRequest):
    """多対多(親A-中間-親B)モデルの移行検証(4ステップ)。"""
    source, a, b, j, cfg = _junction_inputs(req)
    return verify_junction(source, a, b, j, cfg)


@router.post("/junction-verify/orphans")
def junction_orphans_csv(req: sc.JunctionExportRequest):
    """未取込の中間キー一覧(原因つき)をCSVでダウンロード。"""
    source, a, b, j, cfg = _junction_inputs(req)
    result = verify_junction(source, a, b, j, cfg)
    table = build_orphan_table(result, cfg)
    raw = write_csv(table, encoding=req.encoding)
    return _download(raw, _report_name("未取込一覧", store.get_file(req.file_source).filename, store.get_file(req.file_j).filename, ext="csv"), "text/csv")


@router.post("/export/verify/{diff_id}")
def export_verify(diff_id: str, req: sc.ExportVerifyRequest):
    result = _diff_with_known(diff_id)
    if req.format == "xlsx":
        return _download(
            build_verification_xlsx(result, only_b_is_error=req.only_b_is_error),
            _report_name("投入検証", result.name_a, result.name_b, ext="xlsx"),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    table = build_verification_table(result, only_b_is_error=req.only_b_is_error)
    raw = write_csv(table, encoding=req.encoding)
    return _download(raw, _report_name("投入検証", result.name_a, result.name_b, ext="csv"), "text/csv")


@router.post("/export/restore/{diff_id}")
def export_restore(diff_id: str, req: sc.ExportDeleteRequest):
    """投入前のSF値による復元用update CSV(ロールバックキット)。"""
    result = _diff_with_known(diff_id)
    table = build_restore_table(result)
    raw = write_csv(table, encoding=req.encoding)
    return _download(raw, _report_name("復元用_投入前のSF値", result.name_a, result.name_b, ext="csv"), "text/csv")


@router.post("/files/{file_id}/undo-delete")
def export_undo_delete(file_id: str, req: sc.ExportDeleteRequest):
    """success.csvから新規作成レコードの取り消し用delete CSVを生成。"""
    table = store.get_table(file_id)
    undo, skipped = build_undo_delete_table(table)
    raw = write_csv(undo, encoding=req.encoding)
    resp = _download(raw, _report_name("取り消し用delete", store.get_file(file_id).filename, ext="csv"), "text/csv")
    resp.headers["X-Skipped-Updates"] = str(skipped)
    return resp


@router.post("/export/html/{diff_id}")
def export_html(diff_id: str, req: sc.ExportHtmlRequest):
    result = _diff_with_known(diff_id)
    html_text = build_html_report(result, only_b_is_error=req.only_b_is_error)
    return _download(html_text.encode("utf-8"), _report_name("照合レポート", result.name_a, result.name_b, ext="html"), "text/html")


# ---------------------------------------------------------------- 健康診断
@router.post("/files/{file_id}/profile")
def file_profile(file_id: str):
    return profile_table(store.get_table(file_id))


@router.get("/baselines")
def get_baselines():
    from ..core import list_baselines
    return {"baselines": list_baselines()}


@router.post("/files/{file_id}/save-baseline")
def save_file_baseline(file_id: str, req: sc.BaselineSaveRequest):
    from ..core import save_baseline
    save_baseline(req.name, profile_table(store.get_table(file_id)))
    return {"ok": True, "name": req.name}


@router.post("/files/{file_id}/compare-baseline")
def compare_file_baseline(file_id: str, req: sc.BaselineCompareRequest):
    from ..core import load_baseline
    baseline = load_baseline(req.name)
    current = profile_table(store.get_table(file_id))
    return {"warnings": compare_profiles(baseline, current)}


# ---------------------------------------------------------------- あいまい突合
@router.post("/fuzzy-match")
def run_fuzzy_match(req: sc.FuzzyMatchRequest):
    a = store.get_table(req.file_a)
    b = store.get_table(req.file_b)
    pairs = [(p[0], p[1]) for p in req.pairs]
    candidates = fuzzy_match(a, b, pairs=pairs, threshold=req.threshold)
    ia = [a.col_index(x) for x, _ in pairs]
    ib = [b.col_index(y) for _, y in pairs]
    out = []
    for c in candidates:
        out.append({
            **c.to_dict(),
            "values_a": [a.rows[c.index_a][i] for i in ia],
            "values_b": [b.rows[c.index_b][i] for i in ib],
        })
    return {"count": len(out), "candidates": out,
            "columns_a": [p[0] for p in pairs], "columns_b": [p[1] for p in pairs]}


@router.post("/fuzzy-link")
def run_fuzzy_link(req: sc.FuzzyLinkRequest):
    a = store.get_table(req.file_a)
    b = store.get_table(req.file_b)
    out = build_linked_table(a, b, req.matches)
    entry = store.add_table_as_file("あいまい突合結果.csv", out)
    return _file_info(entry, out)


# ---------------------------------------------------------------- 集計・住所
@router.post("/files/{file_id}/crosstab")
def file_crosstab(file_id: str, req: sc.CrosstabRequest):
    table = store.get_table(file_id)
    out = crosstab(table, req.row_col, req.col_col)
    result = {"table": {"columns": out.columns, "rows": out.rows}}
    if req.save_as_file:
        entry = store.add_table_as_file("集計結果.csv", out)
        result["file_id"] = entry.file_id
    return result


@router.post("/files/{file_id}/split-address")
def split_address_file(file_id: str, req: sc.SplitAddressRequest):
    table = store.get_table(file_id).copy()
    table, parsed = split_address_column(table, req.column)
    store.set_table(file_id, table)
    store.log_op(file_id, "split_address", {"column": req.column})
    return {"parsed": parsed, "preview": _preview(table)}


# ---------------------------------------------------------------- 計算列
@router.post("/files/{file_id}/calc-column")
def calc_column(file_id: str, req: sc.CalcColumnRequest):
    table = store.get_table(file_id).copy()
    if req.mode == "concat":
        table = concat_columns(table, req.columns, req.new_name, req.separator)
        store.log_op(file_id, "concat_columns", {
            "columns": req.columns, "new_name": req.new_name,
            "separator": req.separator})
    elif req.mode == "substring":
        table = substring_column(table, req.column, req.new_name,
                                 req.start, req.length)
        store.log_op(file_id, "substring_column", {
            "column": req.column, "new_name": req.new_name,
            "start": req.start, "length": req.length})
    elif req.mode == "conditional":
        table = conditional_column(table, req.column, req.op, req.value,
                                   req.new_name, req.then_value, req.else_value)
        store.log_op(file_id, "conditional_column", {
            "column": req.column, "op": req.op, "value": req.value,
            "new_name": req.new_name, "then_value": req.then_value,
            "else_value": req.else_value})
    else:
        from ..core import DiffDeskError
        raise DiffDeskError(f"不明な計算列モードです: {req.mode}")
    store.set_table(file_id, table)
    return {"preview": _preview(table)}


# ---------------------------------------------------------------- レシピ
@router.get("/files/{file_id}/recipe")
def get_file_recipe(file_id: str):
    entry = store.get_file(file_id)
    return {"ops": entry.ops,
            "labels": [describe_op(o) for o in entry.ops]}


@router.get("/recipes")
def get_recipes():
    return {"recipes": list_recipes()}


@router.post("/recipes")
def post_recipe(req: sc.RecipeSaveRequest):
    ops = req.ops
    if ops is None:
        ops = store.get_file(req.file_id).ops if req.file_id else []
    save_recipe(req.name, ops)
    return {"ok": True, "name": req.name, "count": len(ops)}


@router.post("/files/{file_id}/apply-recipe")
def apply_file_recipe(file_id: str, req: sc.RecipeApplyRequest):
    ops = load_recipe(req.name)
    table = store.get_table(file_id).copy()
    table, logs = apply_recipe(table, ops)
    store.set_table(file_id, table)
    entry = store.get_file(file_id)
    entry.ops.extend(ops)
    return {"logs": logs, "preview": _preview(table)}


# ---------------------------------------------------------------- 既知差分・履歴・辞書
@router.get("/known-diffs")
def get_known_diffs():
    return {"entries": load_known_diffs()}


@router.post("/known-diffs")
def post_known_diff(req: sc.KnownDiffRequest):
    entries = add_known_diff(req.entry)
    return {"ok": True, "count": len(entries)}


@router.delete("/known-diffs/{index}")
def delete_known_diff(index: int):
    return {"entries": remove_known_diff(index)}


@router.delete("/known-diffs")
def delete_all_known_diffs():
    clear_known_diffs()
    return {"ok": True}


@router.get("/diff/{diff_id}/columns-summary")
def diff_columns_summary(diff_id: str):
    result = _diff_with_known(diff_id)
    return {"columns": column_diff_summary(result)}


@router.get("/diff/{diff_id}/value-rule-count")
def value_rule_count(diff_id: str, col_a: str, value_a: str, value_b: str):
    """値ルール(全行既知)を登録した場合に影響するセル数(確認ダイアログ用)。"""
    result = _diff_with_known(diff_id)
    count = sum(
        1 for rd in result.rows if rd.status == "changed"
        for cd in rd.cell_diffs
        if cd.col_a == col_a and cd.value_a == value_a and cd.value_b == value_b)
    return {"count": count}


@router.get("/history")
def get_history(limit: int = 50):
    return {"history": load_history(limit=limit)}


@router.delete("/history")
def delete_history():
    clear_history()
    return {"ok": True}


@router.get("/user-dict")
def get_user_dict():
    return {"entries": load_user_dict()}


@router.post("/user-dict")
def post_user_dict(req: sc.UserDictRequest):
    entries = add_user_pairs(req.pairs)
    return {"ok": True, "count": len(entries)}


@router.delete("/user-dict/{index}")
def delete_user_dict_entry(index: int):
    return {"entries": remove_user_pair(index)}


# ---------------------------------------------------------------- profiles

@router.get("/profiles")
def get_profiles():
    return {"profiles": list_profiles()}


@router.post("/profiles")
def post_profile(req: sc.ProfileSaveRequest):
    profile = Profile.from_dict(req.profile)
    save_profile(profile)
    return {"ok": True, "name": profile.name}


@router.get("/profiles/{name}")
def get_profile(name: str):
    return {"profile": load_profile(name).to_dict()}


@router.delete("/profiles/{name}")
def remove_profile(name: str):
    delete_profile(name)
    return {"ok": True}
