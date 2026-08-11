"""diffdesk.core — web非依存の純Pythonコアロジック。

このパッケージはCLI・スクリプト・他UIからそのまま再利用できる。
fastapi等のwebライブラリをimportしてはならない。
"""
from .anonymize import ANONYMIZE_MODES, anonymize_columns
from .clean import CLEAN_OPS, COLUMN_OPS, clean_columns
from .cluster import ValueCluster, apply_value_map, cluster_column, fingerprint
from .loader_errors import (
    ERROR_CATEGORIES,
    analyze_errors,
    build_retry_table,
    find_error_column,
)
from .diff import apply_filter, diff_tables
from .edit import (
    dedupe_rows,
    split_column,
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
from .mapping_suggest import MappingSuggestion, suggest_mapping
from .verify import (
    VerificationResult,
    build_verification,
    build_verification_table,
    build_verification_xlsx,
)
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
    DiffDeskError,
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
