"""csvtool.core — web非依存の純Pythonコアロジック。

このパッケージはCLI・スクリプト・他UIからそのまま再利用できる。
fastapi等のwebライブラリをimportしてはならない。
"""
from .clean import CLEAN_OPS, clean_columns
from .diff import apply_filter, diff_tables
from .edit import (
    dedupe_rows,
    delete_column,
    delete_rows,
    insert_column,
    insert_row,
    rename_column,
    replace_all,
    search_cells,
    set_cell,
)
from .enrich import apply_merge, concat_tables, vlookup_join
from .io import (
    EncodingWriteError,
    SUPPORTED_DELIMITERS,
    SUPPORTED_ENCODINGS,
    detect_delimiter,
    detect_encoding,
    is_excel_filename,
    list_sheets,
    load_csv,
    load_excel,
    load_table,
    write_csv,
    write_xlsx,
)
from .model import (
    CellDiff,
    ColumnPair,
    CsvToolError,
    DiffOptions,
    DiffResult,
    FilterCondition,
    MappingConfig,
    Profile,
    RowDiff,
    RowFilter,
    Table,
)
from .normalize import make_normalizer, values_equal
from .profile import (
    delete_profile,
    list_profiles,
    load_profile,
    profile_from_json,
    profile_to_json,
    save_profile,
)
from .report_xlsx import build_xlsx_report
from .upsert import (
    build_delete_table,
    build_report_table,
    build_sdl,
    build_upsert_table,
)
from .validate import FORMAT_CHECKS, ValidationIssue, ValidationRules, validate_table

__all__ = [name for name in dir() if not name.startswith("_")]
