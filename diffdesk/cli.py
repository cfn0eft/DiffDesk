"""CLI: GUIなしで差分・アップサートCSV生成等をバッチ実行する。

例:
    python -m diffdesk diff master.xlsx sf.csv --profile 月次照合 --report report.csv
    python -m diffdesk upsert master.csv sf.csv --profile p.json --out upsert.csv
    python -m diffdesk convert in.csv --out out.csv --encoding cp932
    python -m diffdesk validate in.csv --keys 社員番号 --required 氏名 メール
    python -m diffdesk concat a.csv b.csv --out merged.csv
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import (
    DiffDeskError,
    build_verification,
    build_verification_table,
    build_verification_xlsx,
    build_delete_table,
    build_report_table,
    build_sdl,
    build_upsert_table,
    build_xlsx_report,
    concat_tables,
    dedupe_rows,
    diff_tables,
    load_profile,
    load_table,
    validate_table,
    write_csv,
    write_xlsx,
)
from .core.validate import ValidationRules

ENCODINGS = ("utf-8-sig", "utf-8", "cp932")


def _load(path: str, *, encoding: str | None = None, sheet: str | None = None,
          header_row: int = 1):
    p = Path(path)
    if not p.exists():
        raise DiffDeskError(f"ファイルが見つかりません: {path}")
    try:
        raw = p.read_bytes()
    except OSError as e:
        raise DiffDeskError(f"ファイルを読み込めません: {path} ({e})")
    return load_table(raw, p.name, encoding=encoding, sheet=sheet,
                      header_row=header_row - 1)


def _write_out(table, out: str, encoding: str) -> None:
    path = Path(out)
    if path.suffix.lower() == ".xlsx":
        path.write_bytes(write_xlsx(table))
    else:
        path.write_bytes(write_csv(table, encoding=encoding))
    print(f"出力: {path} ({len(table.rows)}行)")


def _add_input_options(p: argparse.ArgumentParser, *, two_files: bool) -> None:
    if two_files:
        p.add_argument("file_a", help="ファイルA(正マスタ)")
        p.add_argument("file_b", help="ファイルB(Salesforceエクスポート等)")
        p.add_argument("--sheet-a", help="ファイルAのシート名(Excel)")
        p.add_argument("--sheet-b", help="ファイルBのシート名(Excel)")
        p.add_argument("--encoding-a", help="ファイルAのエンコーディング(既定: 自動判定)")
        p.add_argument("--encoding-b", help="ファイルBのエンコーディング(既定: 自動判定)")
        p.add_argument("--header-row-a", type=int, default=1, help="Aのヘッダー行番号(1始まり)")
        p.add_argument("--header-row-b", type=int, default=1, help="Bのヘッダー行番号(1始まり)")
    else:
        p.add_argument("file", help="入力ファイル")
        p.add_argument("--sheet", help="シート名(Excel)")
        p.add_argument("--encoding", dest="in_encoding", help="入力エンコーディング(既定: 自動判定)")
        p.add_argument("--header-row", type=int, default=1, help="ヘッダー行番号(1始まり)")


def _run_diff_common(args):
    profile = load_profile(args.profile)
    # キー未指定のプロファイル(単純対応表JSON等)は --external-id / external_id をキーに昇格
    if not profile.mapping.key_pairs:
        ext = getattr(args, "external_id", None) or profile.external_id
        if ext:
            for p in profile.mapping.pairs:
                if p.col_a == ext:
                    p.is_key = True
    a = _load(args.file_a, encoding=args.encoding_a, sheet=args.sheet_a,
              header_row=args.header_row_a)
    b = _load(args.file_b, encoding=args.encoding_b, sheet=args.sheet_b,
              header_row=args.header_row_b)
    return profile, diff_tables(a, b, profile.mapping, profile.options,
                                profile.row_filter)


def cmd_diff(args) -> int:
    profile, result = _run_diff_common(args)
    s = result.summary
    print(f"Aのみ: {s['only_a']}  Bのみ: {s['only_b']}  変更: {s['changed']}  一致: {s['same']}")
    if s["duplicates_a"] or s["duplicates_b"]:
        print(f"警告: キー重複 A={s['duplicates_a']}件 B={s['duplicates_b']}件(照合から除外)")
    if s["empty_key_a"] or s["empty_key_b"]:
        print(f"警告: キー空 A={s['empty_key_a']}行 B={s['empty_key_b']}行(照合から除外)")
    if args.report:
        _write_out(build_report_table(result), args.report, args.out_encoding)
    if args.xlsx:
        Path(args.xlsx).write_bytes(build_xlsx_report(result))
        print(f"出力: {args.xlsx}")
    if args.json:
        print(json.dumps(s, ensure_ascii=False))
    return 1 if (s["only_a"] or s["only_b"] or s["changed"]) and args.check else 0


def cmd_upsert(args) -> int:
    profile, result = _run_diff_common(args)
    ext = args.external_id or profile.external_id
    if not ext:
        raise DiffDeskError("外部ID列を --external-id かプロファイルで指定してください。")
    include = set()
    if not args.no_insert:
        include.add("only_a")
    if not args.no_update:
        include.add("changed")
    if not include:
        raise DiffDeskError("--no-insert と --no-update を同時には指定できません。")
    t = build_upsert_table(result, external_id_col_a=ext, include=include)
    _write_out(t, args.out, args.out_encoding)
    if args.delete_out:
        d = build_delete_table(result, id_col_b=args.delete_id_column)
        _write_out(d, args.delete_out, args.out_encoding)
        print("注意: 削除CSVの内容を必ず確認してからData Loaderに投入してください。")
    if args.sdl:
        Path(args.sdl).write_text(build_sdl(result), encoding="utf-8")
        print(f"出力: {args.sdl}")
    return 0


def cmd_verify(args) -> int:
    """投入後検証: 件数照合と差異判定。合格なら終了コード0、要確認なら1。"""
    profile, result = _run_diff_common(args)
    v = build_verification(result, only_b_is_error=not args.allow_only_b)
    print("✔ 投入OK(全件一致)" if v.passed else "✖ 要確認(差異あり)")
    print(f"  A照合対象: {v.rows_a}件  B照合対象: {v.rows_b}件  キー一致: {v.matched}件")
    print(f"  完全一致: {v.same}  値差異: {v.changed}  未投入(Aのみ): {v.only_a}"
          f"  想定外(Bのみ): {v.only_b}")
    if v.unmatchable_a or v.unmatchable_b:
        print(f"  照合不能: A={v.unmatchable_a}件 B={v.unmatchable_b}件(キー重複・空)")
    for p in v.problems:
        print(f"  - {p}")
    if args.report:
        path = Path(args.report)
        if path.suffix.lower() == ".xlsx":
            path.write_bytes(build_verification_xlsx(
                result, only_b_is_error=not args.allow_only_b))
            print(f"出力: {path}")
        else:
            _write_out(build_verification_table(
                result, only_b_is_error=not args.allow_only_b),
                args.report, args.out_encoding)
    return 0 if v.passed else 1


def cmd_convert(args) -> int:
    t = _load(args.file, encoding=args.in_encoding, sheet=args.sheet,
              header_row=args.header_row)
    if args.dedupe:
        t, removed = dedupe_rows(t)
        if removed:
            print(f"重複行を{removed}件削除")
    _write_out(t, args.out, args.out_encoding)
    return 0


def cmd_validate(args) -> int:
    t = _load(args.file, encoding=args.in_encoding, sheet=args.sheet,
              header_row=args.header_row)
    rules = ValidationRules(
        key_columns=args.keys or [],
        required_columns=args.required or [],
        formats=dict(kv.split("=", 1) for kv in (args.format or [])),
    )
    issues = validate_table(t, rules)
    for i in issues:
        print(f"{i.row}行目 [{i.column}] {i.message}")
    print(f"検出: {len(issues)}件")
    return 1 if issues else 0


def cmd_concat(args) -> int:
    tables = [_load(f) for f in args.files]
    out = concat_tables(tables, mode="strict" if args.strict else "union")
    _write_out(out, args.out, args.out_encoding)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diffdesk",
        description="CSV/Excelの比較・変換・Data Loader用CSV生成(引数なしでWebアプリ起動)",
    )
    sub = parser.add_subparsers(dest="command")

    def add_out_encoding(p):
        p.add_argument("--out-encoding", choices=ENCODINGS, default="utf-8-sig",
                       help="出力エンコーディング(既定: utf-8-sig)")

    p = sub.add_parser("diff", help="2ファイルを比較して差分サマリー/レポートを出力")
    _add_input_options(p, two_files=True)
    p.add_argument("--profile", required=True, help="プロファイル名またはJSONパス")
    p.add_argument("--external-id", help="キー列(A側列名。キー未指定のマッピングJSON用)")
    p.add_argument("--report", help="差分レポートCSVの出力先")
    p.add_argument("--xlsx", help="色付きExcelレポートの出力先")
    p.add_argument("--json", action="store_true", help="サマリーをJSONでも出力")
    p.add_argument("--check", action="store_true", help="差分があれば終了コード1")
    add_out_encoding(p)
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("upsert", help="Data Loader用アップサートCSVを生成")
    _add_input_options(p, two_files=True)
    p.add_argument("--profile", required=True, help="プロファイル名またはJSONパス")
    p.add_argument("--out", required=True, help="アップサートCSVの出力先")
    p.add_argument("--external-id", help="外部ID列(A側列名。プロファイル設定を上書き)")
    p.add_argument("--no-insert", action="store_true", help="only_a(insert)を含めない")
    p.add_argument("--no-update", action="store_true", help="changed(update)を含めない")
    p.add_argument("--delete-out", help="削除用CSVの出力先(Bのみ行のId)")
    p.add_argument("--delete-id-column", default="Id", help="B側のId列名(既定: Id)")
    p.add_argument("--sdl", help=".sdlマッピングファイルの出力先")
    add_out_encoding(p)
    p.set_defaults(func=cmd_upsert)

    p = sub.add_parser("verify", help="投入後の検証(件数照合と差異判定。要確認なら終了コード1)")
    _add_input_options(p, two_files=True)
    p.add_argument("--profile", required=True, help="プロファイル名またはJSONパス")
    p.add_argument("--external-id", help="キー列(A側列名。キー未指定のマッピングJSON用)")
    p.add_argument("--allow-only-b", action="store_true",
                   help="Bのみのレコード(SF既存レコード)を問題として扱わない")
    p.add_argument("--report", help="検証レポートの出力先(.xlsx または .csv)")
    add_out_encoding(p)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("convert", help="エンコーディング/形式変換(CSV↔Excel)")
    _add_input_options(p, two_files=False)
    p.add_argument("--out", required=True, help="出力先(.csv または .xlsx)")
    p.add_argument("--dedupe", action="store_true", help="完全重複行を削除")
    add_out_encoding(p)
    p.set_defaults(func=cmd_convert)

    p = sub.add_parser("validate", help="単体ファイルの検証")
    _add_input_options(p, two_files=False)
    p.add_argument("--keys", nargs="*", help="重複チェックするキー列")
    p.add_argument("--required", nargs="*", help="必須列(空セル禁止)")
    p.add_argument("--format", nargs="*",
                   help="形式チェック(列名=email|phone|number|date_iso)")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("concat", help="複数ファイルを縦に結合")
    p.add_argument("files", nargs="+", help="入力ファイル(2つ以上)")
    p.add_argument("--out", required=True, help="出力先")
    p.add_argument("--strict", action="store_true", help="列構成の完全一致を要求")
    add_out_encoding(p)
    p.set_defaults(func=cmd_concat)

    return parser


def run_cli(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except DiffDeskError as e:
        print(f"エラー: {e.message}", file=sys.stderr)
        if e.details.get("locations"):
            for loc in e.details["locations"][:10]:
                print(f"  {loc['row']}行目 [{loc['column']}] 文字: {loc['char']}",
                      file=sys.stderr)
        return 2
