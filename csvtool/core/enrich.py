"""VLOOKUP的列付加・複数ファイル結合・差分マージ適用。"""
from __future__ import annotations

from .model import (
    CsvToolError,
    DiffOptions,
    DiffResult,
    Table,
)
from .normalize import make_normalizer


def vlookup_join(table_a: Table, table_b: Table, *,
                 key_pairs: list[tuple[str, str]],
                 add_columns: list[str],
                 options: DiffOptions | None = None,
                 default: str = "") -> tuple[Table, int]:
    """Bをキー照合してBの指定列をAに付加したTableと、未一致行数を返す。

    Excel の VLOOKUP 相当。B側で同一キーが複数ある場合は最初の行を使う。
    """
    if not key_pairs:
        raise CsvToolError("キー列の対応付けが指定されていません。")
    if not add_columns:
        raise CsvToolError("付加する列が指定されていません。")
    options = options or DiffOptions()
    normalizer = make_normalizer(options)

    ka_idx = [table_a.col_index(a) for a, _ in key_pairs]
    kb_idx = [table_b.col_index(b) for _, b in key_pairs]
    add_idx = [table_b.col_index(c) for c in add_columns]

    index_b: dict[tuple[str, ...], list[str]] = {}
    for row in table_b.rows:
        key = tuple(normalizer(row[i]) for i in kb_idx)
        if all(v == "" for v in key):
            continue
        if key not in index_b:
            index_b[key] = [row[i] for i in add_idx]

    out = table_a.copy()
    existing = set(out.columns)
    new_names = []
    for c in add_columns:
        name = c
        while name in existing:
            name = name + "_B"
        existing.add(name)
        new_names.append(name)
    out.columns.extend(new_names)

    unmatched = 0
    for row in out.rows:
        key = tuple(normalizer(row[i]) for i in ka_idx)
        values = index_b.get(key)
        if values is None:
            unmatched += 1
            row.extend([default] * len(add_columns))
        else:
            row.extend(values)
    return out, unmatched


def concat_tables(tables: list[Table], *, mode: str = "union") -> Table:
    """複数Tableを縦に連結する。

    mode="union": 全列の和集合(存在しない列は空)。最初の表の列順を優先。
    mode="strict": 列構成が完全一致しない場合はエラー。
    """
    if not tables:
        raise CsvToolError("結合するファイルがありません。")
    if mode == "strict":
        base = tables[0].columns
        for t in tables[1:]:
            if t.columns != base:
                raise CsvToolError(
                    f"列構成が一致しません: {t.name or '(無名)'}",
                    expected=base, actual=t.columns,
                )
        columns = list(base)
    elif mode == "union":
        columns = []
        for t in tables:
            for c in t.columns:
                if c not in columns:
                    columns.append(c)
    else:
        raise CsvToolError(f"不明な結合モードです: {mode}", mode=mode)

    rows: list[list[str]] = []
    for t in tables:
        idx = {c: i for i, c in enumerate(t.columns)}
        for row in t.rows:
            rows.append([row[idx[c]] if c in idx else "" for c in columns])
    return Table(columns=columns, rows=rows, name="結合結果")


def apply_merge(diff: DiffResult, choices: list[dict], *,
                include_only_a: bool = True,
                include_only_b: bool = False) -> Table:
    """差分マージ: 変更セルごとのA/B採用選択を適用したマージ結果Tableを返す。

    - 出力列はA側のマッピング列名(A列順)。
    - ベースはAの値。choices で {key: [...], col_a: str, use: "b"} を指定した
      セルのみBの値を採用する。
    - include_only_b=True の場合、Bのみの行もマッピング経由でA列名に変換して追加。
    """
    choice_map: dict[tuple[tuple[str, ...], str], str] = {}
    for ch in choices:
        key = tuple(str(k) for k in ch.get("key", []))
        col_a = str(ch.get("col_a", ""))
        use = str(ch.get("use", "a"))
        if use not in ("a", "b"):
            raise CsvToolError(f"採用指定が不正です: {use}(a または b)", use=use)
        choice_map[(key, col_a)] = use

    cols_a = [p.col_a for p in diff.mapping.pairs]
    rows: list[list[str]] = []
    for rd in diff.rows:
        if rd.status in ("same", "changed"):
            assert rd.row_a is not None and rd.row_b is not None
            row = list(rd.row_a)
            for cd in rd.cell_diffs:
                if choice_map.get((rd.key, cd.col_a)) == "b":
                    row[cols_a.index(cd.col_a)] = cd.value_b
            rows.append(row)
        elif rd.status == "only_a" and include_only_a:
            assert rd.row_a is not None
            rows.append(list(rd.row_a))
        elif rd.status == "only_b" and include_only_b:
            assert rd.row_b is not None
            rows.append(list(rd.row_b))
    return Table(columns=cols_a, rows=rows, name="マージ結果")
