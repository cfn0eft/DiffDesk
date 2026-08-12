"""diffdesk.core — web非依存の純Pythonコアロジック。

このパッケージはCLI・スクリプト・他UIからそのまま再利用できる。
fastapi等のwebライブラリをimportしてはならない。
"""
from .address import split_address, split_address_column
from .junction import (
    JunctionConfig,
    build_orphan_table,
    infer_key_template,
    verify_junction,
)
from .migration_spec import (
    build_junction_settings,
    build_mapping_pairs,
    parse_migration_spec,
)
from .transform import apply_transform, pair_values_equal, transform_summary
from .known import apply_known_diffs, column_diff_summary
from .manual import (
    apply_manual_pairs,
    build_link_prompt,
    list_unmatched,
    pair_similarity,
    parse_link_answer,
    suggest_links,
    validate_manual_pair,
)
from .workspace import (
    add_known_diff,
    add_manual_link,
    add_user_pairs,
    append_history,
    clear_history,
    clear_known_diffs,
    clear_manual_links,
    load_history,
    load_known_diffs,
    load_manual_links,
    load_user_dict,
    peek_undo,
    remove_known_diff,
    remove_manual_link,
    remove_user_pair,
    undo_last,
)
from .project import (
    create_project,
    delete_project,
    list_projects,
    switch_project,
)
from .anonymize import ANONYMIZE_MODES, anonymize_columns
from .fuzzy import FuzzyCandidate, build_linked_table, fuzzy_match
from .profile_stats import (
    compare_profiles,
    list_baselines,
    load_baseline,
    profile_table,
    save_baseline,
)
from .report_html import build_html_report
from .rollback import (
    build_restore_table,
    build_undo_delete_table,
    find_success_id_column,
)
from .stats import crosstab
from .clean import CLEAN_OPS, COLUMN_OPS, clean_columns
from .cluster import ValueCluster, apply_value_map, cluster_column, fingerprint
from .loader_errors import (
    ERROR_CATEGORIES,
    analyze_errors,
    build_retry_table,
    find_error_column,
)
from .diff import apply_filter, diff_tables
from .recipe import (
    RECIPE_OPS,
    apply_recipe,
    describe_op,
    list_recipes,
    load_recipe,
    save_recipe,
)
from .edit import (
    concat_columns,
    conditional_column,
    dedupe_rows,
    split_column,
    substring_column,
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
