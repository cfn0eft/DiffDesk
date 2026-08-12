"""APIリクエスト/レスポンスのPydanticモデル(coreのdictシリアライズの薄いラッパ)。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ParseRequest(BaseModel):
    encoding: str | None = None
    delimiter: str | None = None
    sheet: str | None = None
    header_row: int = Field(default=1, ge=1, description="1始まりのヘッダー行番号")


class TableUpdateRequest(BaseModel):
    columns: list[str]
    rows: list[list[str]]


class CleanRequest(BaseModel):
    columns: list[str]
    ops: list[str]


class ValidateRequest(BaseModel):
    key_columns: list[str] = []
    required_columns: list[str] = []
    formats: dict[str, str] = {}
    max_lengths: dict[str, int] = {}
    allowed_values: dict[str, list[str]] = {}
    ranges: dict[str, list[float | None]] = {}


class BaselineSaveRequest(BaseModel):
    name: str


class BaselineCompareRequest(BaseModel):
    name: str


class FuzzyMatchRequest(BaseModel):
    file_a: str
    file_b: str
    pairs: list[list[str]]  # [[col_a, col_b], ...]
    threshold: float = 0.75


class FuzzyLinkRequest(BaseModel):
    file_a: str
    file_b: str
    matches: list[dict]  # [{index_a, index_b, score}]


class CrosstabRequest(BaseModel):
    row_col: str
    col_col: str | None = None
    save_as_file: bool = False


class SplitAddressRequest(BaseModel):
    column: str


class ExportHtmlRequest(BaseModel):
    only_b_is_error: bool = True


class CalcColumnRequest(BaseModel):
    mode: str  # concat | substring | conditional
    new_name: str
    columns: list[str] = []          # concat用
    separator: str = ""              # concat用
    column: str = ""                 # substring/conditional用
    start: int = 1                   # substring用(1始まり)
    length: int | None = None        # substring用
    op: str = "eq"                   # conditional用
    value: str = ""                  # conditional用
    then_value: str = ""             # conditional用
    else_value: str = ""             # conditional用


class RecipeSaveRequest(BaseModel):
    name: str
    file_id: str | None = None       # 指定時はそのファイルの操作履歴を保存
    ops: list[dict] | None = None    # 直接opsを渡す場合


class RecipeApplyRequest(BaseModel):
    name: str


class KnownDiffRequest(BaseModel):
    entry: dict  # {type: "cell"|"row", key: [...], ...}


class ManualPairRequest(BaseModel):
    key_a: list[str]  # 基準(A)側 only_a 行のキー
    key_b: list[str]  # 比較(B)側 only_b 行のキー
    note: str = ""  # 紐づけ理由のメモ(監査用・任意)
    score: float | None = None  # 登録時の一致率(監査用・任意)


class LinkSuggestRequest(BaseModel):
    threshold: float = 0.5
    limit: int = 50


class LinkImportRequest(BaseModel):
    text: str  # Web版AIの回答をそのまま貼り付けたテキスト


class UserDictRequest(BaseModel):
    pairs: list[dict]  # [{col_a, col_b}, ...]


class ClusterRequest(BaseModel):
    column: str


class ApplyMapRequest(BaseModel):
    column: str
    mapping: dict[str, str]


class AnonymizeRequest(BaseModel):
    spec: dict[str, str]  # 列名 -> モード


class SplitColumnRequest(BaseModel):
    column: str
    delimiter: str


class ColumnValuesRequest(BaseModel):
    column: str
    limit: int = 200


class SearchRequest(BaseModel):
    query: str
    columns: list[str] | None = None
    regex: bool = False
    case_sensitive: bool = True


class ReplaceRequest(SearchRequest):
    replacement: str = ""


class ConcatRequest(BaseModel):
    file_ids: list[str]
    mode: str = "union"


class EnrichRequest(BaseModel):
    other_file_id: str
    key_pairs: list[list[str]]  # [[col_a, col_b], ...]
    add_columns: list[str]
    options: dict = {}


class DiffRequest(BaseModel):
    file_a: str
    file_b: str
    mapping: dict
    options: dict = {}
    row_filter: dict = {}


class MergeRequest(BaseModel):
    choices: list[dict] = []
    include_only_b: bool = False


class AutomapRequest(BaseModel):
    file_a: str
    file_b: str


class ExportTableRequest(BaseModel):
    encoding: str = "utf-8-sig"
    format: str = "csv"  # csv | xlsx
    delimiter: str = ","
    errors: str = "strict"  # strict | replace
    filename: str | None = None


class ExportUpsertRequest(BaseModel):
    external_id: str
    include_insert: bool = True
    include_update: bool = True
    encoding: str = "utf-8-sig"
    errors: str = "strict"


class ExportDeleteRequest(BaseModel):
    id_col_b: str = "Id"
    encoding: str = "utf-8-sig"


class ExportReportRequest(BaseModel):
    format: str = "csv"  # csv | xlsx
    encoding: str = "utf-8-sig"


class ExportVerifyRequest(BaseModel):
    format: str = "xlsx"  # xlsx | csv
    only_b_is_error: bool = True
    encoding: str = "utf-8-sig"


class JunctionVerifyRequest(BaseModel):
    file_source: str   # 移行元データのfile_id
    file_j: str        # 中間抽出のfile_id
    file_a: str = ""   # 親A抽出のfile_id(任意)
    file_b: str = ""   # 親B抽出のfile_id(任意)
    config: dict       # JunctionConfig.from_dict に渡す設定


class InferTemplateRequest(BaseModel):
    file_source: str
    file_j: str
    a_source_col: str
    b_source_col: str
    j_key_col: str
    a_regex_pattern: str = ""
    a_regex_replacement: str = ""
    b_regex_pattern: str = ""
    b_regex_replacement: str = ""


class JunctionExportRequest(JunctionVerifyRequest):
    encoding: str = "utf-8-sig"


class MigrationSpecRequest(BaseModel):
    spec: dict  # 移行定義JSON(1ファイル分)


class MigrationSpecsRequest(BaseModel):
    specs: list[dict]  # 移行定義JSON(複数ファイル分)


class ProfileSaveRequest(BaseModel):
    profile: dict


class ProjectRequest(BaseModel):
    name: str
