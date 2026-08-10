"""APIエンドポイント。ロジックは全て diffdesk.core に委譲する。"""
from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import Response

from ..core import (
    CLEAN_OPS,
    build_verification,
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
    return {"changed_cells": changed, "preview": _preview(table)}


@router.get("/clean-ops")
def clean_ops():
    return {"ops": [{"id": k, "label": v[0]} for k, v in CLEAN_OPS.items()]}


@router.post("/files/{file_id}/validate")
def validate_file(file_id: str, req: sc.ValidateRequest):
    table = store.get_table(file_id)
    rules = ValidationRules(
        key_columns=req.key_columns,
        required_columns=req.required_columns,
        formats=req.formats,
        max_lengths=req.max_lengths,
    )
    issues = validate_table(table, rules)
    return {"count": len(issues), "issues": [i.to_dict() for i in issues[:500]]}


@router.post("/files/{file_id}/dedupe")
def dedupe_file(file_id: str):
    table = store.get_table(file_id).copy()
    table, removed = dedupe_rows(table)
    store.set_table(file_id, table)
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

@router.post("/automap")
def automap(req: sc.AutomapRequest):
    a = store.get_table(req.file_a)
    b = store.get_table(req.file_b)
    suggestions = suggest_mapping(a, b)
    return {
        "pairs": [s.to_dict() for s in suggestions],
        "by_name": sum(1 for s in suggestions if s.method == "name"),
        "by_value": sum(1 for s in suggestions if s.method == "value"),
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
    return {
        "diff_id": diff_id,
        "summary": result.summary,
        "duplicates_a": [list(k) for k in result.duplicates_a[:100]],
        "duplicates_b": [list(k) for k in result.duplicates_b[:100]],
        "columns_a": [p.col_a for p in mapping.pairs],
        "columns_b": [p.col_b for p in mapping.pairs],
        "key_flags": [p.is_key for p in mapping.pairs],
    }


@router.get("/diff/{diff_id}/rows")
def diff_rows(diff_id: str, status: str = "", offset: int = 0, limit: int = 200):
    result = store.get_diff(diff_id)
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
    result = store.get_diff(diff_id)
    return build_verification(result, only_b_is_error=only_b_is_error).to_dict()


@router.post("/diff/{diff_id}/merge")
def merge_diff(diff_id: str, req: sc.MergeRequest):
    result = store.get_diff(diff_id)
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
    result = store.get_diff(diff_id)
    include = set()
    if req.include_insert:
        include.add("only_a")
    if req.include_update:
        include.add("changed")
    table = build_upsert_table(result, external_id_col_a=req.external_id,
                               include=include)
    raw = write_csv(table, encoding=req.encoding, errors=req.errors)
    return _download(raw, "upsert.csv", "text/csv")


@router.post("/export/delete/{diff_id}")
def export_delete(diff_id: str, req: sc.ExportDeleteRequest):
    result = store.get_diff(diff_id)
    table = build_delete_table(result, id_col_b=req.id_col_b)
    raw = write_csv(table, encoding=req.encoding)
    return _download(raw, "delete.csv", "text/csv")


@router.get("/export/sdl/{diff_id}")
def export_sdl(diff_id: str):
    result = store.get_diff(diff_id)
    return _download(build_sdl(result).encode("utf-8"), "mapping.sdl", "text/plain")


@router.post("/export/report/{diff_id}")
def export_report(diff_id: str, req: sc.ExportReportRequest):
    result = store.get_diff(diff_id)
    if req.format == "xlsx":
        return _download(build_xlsx_report(result), "差分レポート.xlsx",
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    table = build_report_table(result)
    raw = write_csv(table, encoding=req.encoding)
    return _download(raw, "差分レポート.csv", "text/csv")


@router.post("/export/verify/{diff_id}")
def export_verify(diff_id: str, req: sc.ExportVerifyRequest):
    result = store.get_diff(diff_id)
    if req.format == "xlsx":
        return _download(
            build_verification_xlsx(result, only_b_is_error=req.only_b_is_error),
            "投入検証レポート.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    table = build_verification_table(result, only_b_is_error=req.only_b_is_error)
    raw = write_csv(table, encoding=req.encoding)
    return _download(raw, "投入検証レポート.csv", "text/csv")


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
