"""コアデータモデル。web非依存の純Python。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

RowStatus = Literal["only_a", "only_b", "changed", "same"]

FILTER_OPS = (
    "eq", "ne", "contains", "not_contains",
    "starts_with", "ends_with", "empty", "not_empty", "regex",
)


class DiffDeskError(Exception):
    """ユーザーに提示可能なエラーの基底クラス。"""

    code = "error"

    def __init__(self, message: str, **details: Any):
        super().__init__(message)
        self.message = message
        self.details = details


@dataclass
class Table:
    """全セルを文字列として保持する表。境界型としてJSON化が容易。"""

    columns: list[str]
    rows: list[list[str]]
    name: str = ""
    source_encoding: str = ""
    sheet: str | None = None

    def col_index(self, column: str) -> int:
        try:
            return self.columns.index(column)
        except ValueError:
            raise DiffDeskError(f"列が見つかりません: {column}", column=column)

    def copy(self) -> "Table":
        return Table(
            columns=list(self.columns),
            rows=[list(r) for r in self.rows],
            name=self.name,
            source_encoding=self.source_encoding,
            sheet=self.sheet,
        )

    def to_dict(self) -> dict:
        return {
            "columns": self.columns,
            "rows": self.rows,
            "name": self.name,
            "source_encoding": self.source_encoding,
            "sheet": self.sheet,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Table":
        t = cls(
            columns=[str(c) for c in d.get("columns", [])],
            rows=[[str(c) for c in row] for row in d.get("rows", [])],
            name=str(d.get("name", "")),
            source_encoding=str(d.get("source_encoding", "")),
            sheet=d.get("sheet"),
        )
        t.make_rectangular()
        return t

    def make_rectangular(self) -> None:
        """行の長さを列数に揃える(不足は空文字で埋め、超過分は列を追加)。"""
        width = len(self.columns)
        for row in self.rows:
            if len(row) > width:
                width = len(row)
        while len(self.columns) < width:
            self.columns.append(f"列{len(self.columns) + 1}")
        for row in self.rows:
            if len(row) < width:
                row.extend([""] * (width - len(row)))


@dataclass
class ColumnPair:
    """ファイルA・B間の列の対応付け。"""

    col_a: str
    col_b: str
    is_key: bool = False
    sf_field: str | None = None  # Data Loader出力時のSalesforce項目名(未指定はcol_b)

    @property
    def output_field(self) -> str:
        return self.sf_field if self.sf_field else self.col_b

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ColumnPair":
        return cls(
            col_a=str(d["col_a"]),
            col_b=str(d["col_b"]),
            is_key=bool(d.get("is_key", False)),
            sf_field=d.get("sf_field") or None,
        )


@dataclass
class MappingConfig:
    pairs: list[ColumnPair]

    @property
    def key_pairs(self) -> list[ColumnPair]:
        return [p for p in self.pairs if p.is_key]

    @property
    def value_pairs(self) -> list[ColumnPair]:
        return [p for p in self.pairs if not p.is_key]

    def validate(self, columns_a: list[str], columns_b: list[str]) -> None:
        if not self.pairs:
            raise DiffDeskError("列マッピングが空です。少なくとも1組の対応付けが必要です。")
        if not self.key_pairs:
            raise DiffDeskError("キー列が指定されていません。1組以上のペアにキー指定が必要です。")
        seen: set[tuple[str, str]] = set()
        for p in self.pairs:
            if p.col_a not in columns_a:
                raise DiffDeskError(f"ファイルAに列がありません: {p.col_a}", column=p.col_a)
            if p.col_b not in columns_b:
                raise DiffDeskError(f"ファイルBに列がありません: {p.col_b}", column=p.col_b)
            if (p.col_a, p.col_b) in seen:
                raise DiffDeskError(f"同じ対応付けが重複しています: {p.col_a} ↔ {p.col_b}")
            seen.add((p.col_a, p.col_b))

    def to_dict(self) -> dict:
        return {"pairs": [p.to_dict() for p in self.pairs]}

    @classmethod
    def from_dict(cls, d: dict) -> "MappingConfig":
        return cls(pairs=[ColumnPair.from_dict(p) for p in d.get("pairs", [])])


@dataclass
class DiffOptions:
    """比較時の正規化オプション。比較にのみ使い、表示・出力は常に元の値。"""

    trim: bool = True
    ignore_case: bool = False
    normalize_width: bool = True  # NFKCによる全角半角統一
    normalize_numeric: bool = True  # 数値の表記を同一視(1551 = 1551.0)
    numeric_tolerance: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DiffOptions":
        tol = d.get("numeric_tolerance")
        return cls(
            trim=bool(d.get("trim", True)),
            ignore_case=bool(d.get("ignore_case", False)),
            normalize_width=bool(d.get("normalize_width", True)),
            normalize_numeric=bool(d.get("normalize_numeric", True)),
            numeric_tolerance=float(tol) if tol is not None else None,
        )


@dataclass
class FilterCondition:
    column: str
    op: str  # FILTER_OPS のいずれか
    value: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FilterCondition":
        op = str(d.get("op", "eq"))
        if op not in FILTER_OPS:
            raise DiffDeskError(f"不明なフィルタ条件です: {op}", op=op)
        return cls(column=str(d["column"]), op=op, value=str(d.get("value", "")))


@dataclass
class RowFilter:
    """比較前の行絞り込み。A側・B側それぞれの条件(AND結合)。"""

    conditions_a: list[FilterCondition] = field(default_factory=list)
    conditions_b: list[FilterCondition] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "conditions_a": [c.to_dict() for c in self.conditions_a],
            "conditions_b": [c.to_dict() for c in self.conditions_b],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RowFilter":
        return cls(
            conditions_a=[FilterCondition.from_dict(c) for c in d.get("conditions_a", [])],
            conditions_b=[FilterCondition.from_dict(c) for c in d.get("conditions_b", [])],
        )


@dataclass
class CellDiff:
    col_a: str
    col_b: str
    value_a: str
    value_b: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RowDiff:
    key: tuple[str, ...]  # 正規化済みキー値
    status: RowStatus
    row_a: list[str] | None  # マッピング列に射影したAの元の値(A列順)
    row_b: list[str] | None
    cell_diffs: list[CellDiff] = field(default_factory=list)
    known: bool = False  # 既知差分として容認済み(欠落レコード or 全セル差分が既知)
    known_diffs: list[CellDiff] = field(default_factory=list)  # 既知扱いのセル差分
    manual: bool = False  # ユーザーが手動で紐づけたペア
    key_b: tuple[str, ...] | None = None  # 手動紐づけ時の相手側(B)のキー

    def to_dict(self) -> dict:
        return {
            "key": list(self.key),
            "status": self.status,
            "row_a": self.row_a,
            "row_b": self.row_b,
            "cell_diffs": [c.to_dict() for c in self.cell_diffs],
            "known": self.known,
            "known_diffs": [c.to_dict() for c in self.known_diffs],
            "manual": self.manual,
            "key_b": list(self.key_b) if self.key_b else None,
        }


@dataclass
class DiffResult:
    mapping: MappingConfig
    options: DiffOptions
    rows: list[RowDiff]
    duplicates_a: list[tuple[str, ...]]
    duplicates_b: list[tuple[str, ...]]
    empty_key_a: int = 0
    empty_key_b: int = 0
    name_a: str = ""
    name_b: str = ""

    @property
    def summary(self) -> dict:
        counts = {"only_a": 0, "only_b": 0, "changed": 0, "same": 0}
        for r in self.rows:
            counts[r.status] += 1
        counts["duplicates_a"] = len(self.duplicates_a)
        counts["duplicates_b"] = len(self.duplicates_b)
        counts["empty_key_a"] = self.empty_key_a
        counts["empty_key_b"] = self.empty_key_b
        return counts


@dataclass
class Profile:
    """マッピング・オプション・フィルタ・外部ID設定の保存単位。"""

    name: str
    mapping: MappingConfig
    options: DiffOptions = field(default_factory=DiffOptions)
    row_filter: RowFilter = field(default_factory=RowFilter)
    external_id: str | None = None  # 外部IDに使うキーペアのcol_a名

    VERSION = 1

    def to_dict(self) -> dict:
        return {
            "version": self.VERSION,
            "name": self.name,
            "mapping": self.mapping.to_dict(),
            "options": self.options.to_dict(),
            "row_filter": self.row_filter.to_dict(),
            "external_id": self.external_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        if not isinstance(d, dict) or "mapping" not in d:
            raise DiffDeskError("プロファイルの形式が不正です(mappingがありません)。")
        return cls(
            name=str(d.get("name", "")),
            mapping=MappingConfig.from_dict(d["mapping"]),
            options=DiffOptions.from_dict(d.get("options", {})),
            row_filter=RowFilter.from_dict(d.get("row_filter", {})),
            external_id=d.get("external_id") or None,
        )
