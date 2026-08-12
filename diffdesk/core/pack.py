"""検証パック: 照合結果の証跡一式を1つのzipにまとめて出力する。

同梱物:
- 照合レポート.csv        (全行の分類と差分セル)
- 検証レポート.xlsx       (投入検証の合否と問題行・監査シート)
- 共有用レポート.html     (フィルタ内蔵の単一ファイルレポート)
- 既知差分.csv / 手動紐づけ.csv (容認・紐づけの登録内容)
- 監査ログ.csv            (この案件の操作証跡)
- はじめにお読みください.txt (概要と件数サマリー)
"""
from __future__ import annotations

import io
import zipfile
from datetime import datetime
from pathlib import Path

from .audit import audit_table
from .io import write_csv
from .model import DiffResult, Table
from .report_html import build_html_report
from .upsert import build_report_table
from .verify import build_verification, build_verification_xlsx
from .workspace import load_known_diffs, load_manual_links, load_notes


def _known_table(directory: Path | None) -> Table:
    rows = []
    for e in load_known_diffs(directory=directory):
        kind = {"cell": "セル差分", "row": "欠落行", "value": "値ルール(全行)"}.get(
            e.get("type"), e.get("type", ""))
        rows.append([
            kind,
            "/".join(e.get("key") or []) or "(全行)",
            e.get("col_a", ""), e.get("value_a", ""), e.get("value_b", ""),
            e.get("status", ""), e.get("note", ""), e.get("added_at", ""),
        ])
    return Table(
        columns=["種類", "キー", "列", "基準の値", "比較の値", "欠落側", "メモ", "登録日時"],
        rows=rows, name="既知差分")


def _notes_table(directory: Path | None) -> Table:
    rows = [["/".join(e.get("key") or []), e.get("text", ""),
             e.get("updated_at", "")] for e in load_notes(directory=directory)]
    return Table(columns=["キー", "メモ", "更新日時"], rows=rows, name="注釈")


def _links_table(directory: Path | None) -> Table:
    rows = [[
        "/".join(e.get("key_a") or []), "/".join(e.get("key_b") or []),
        "" if e.get("score") is None else f"{round(e['score'] * 100)}%",
        e.get("note", ""), e.get("added_at", ""),
    ] for e in load_manual_links(directory=directory)]
    return Table(columns=["基準(A)のキー", "比較(B)のキー", "一致率", "メモ", "登録日時"],
                 rows=rows, name="手動紐づけ")


def _readme_text(result: DiffResult, project_name: str, version: str) -> str:
    s = result.summary
    v = build_verification(result)
    lines = [
        "DiffDesk 検証パック",
        "=" * 40,
        f"作成日時   : {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"DiffDesk   : v{version}",
        f"案件       : {project_name}",
        f"基準(A)    : {result.name_a}",
        f"比較(B)    : {result.name_b}",
        "",
        "件数サマリー",
        "-" * 40,
        f"一致       : {s['same']}",
        f"値の相違   : {s['changed']}",
        f"Aのみ(未登録): {s['only_a']}",
        f"Bのみ      : {s['only_b']}",
        f"一致率     : {v.to_dict()['match_rate'] * 100:.1f}%",
        f"判定       : {'OK' if v.passed else '要確認'}",
        "",
        "同梱ファイル",
        "-" * 40,
        "照合レポート.csv        … 全行の分類と差分セル",
        "検証レポート.xlsx       … 投入検証の合否・問題行・監査シート",
        "共有用レポート.html     … ブラウザで開ける単一ファイルレポート",
        "既知差分.csv            … 「確認済み・問題なし」として容認した差異",
        "手動紐づけ.csv          … 手動でペアにしたレコードの監査記録",
        "注釈.csv                … 行に付けたレビューメモ",
        "監査ログ.csv            … この案件で行った操作の証跡",
    ]
    return "\r\n".join(lines) + "\r\n"


def build_verification_pack(result: DiffResult, *, project_name: str = "既定",
                            version: str = "", only_b_is_error: bool = True,
                            directory: Path | None = None) -> bytes:
    """検証パックzipのバイト列を作る。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("はじめにお読みください.txt",
                   _readme_text(result, project_name, version).encode("utf-8-sig"))
        z.writestr("照合レポート.csv", write_csv(build_report_table(result)))
        z.writestr("検証レポート.xlsx",
                   build_verification_xlsx(result, only_b_is_error=only_b_is_error))
        z.writestr("共有用レポート.html",
                   build_html_report(result, only_b_is_error=only_b_is_error)
                   .encode("utf-8"))
        z.writestr("既知差分.csv", write_csv(_known_table(directory)))
        z.writestr("手動紐づけ.csv", write_csv(_links_table(directory)))
        z.writestr("注釈.csv", write_csv(_notes_table(directory)))
        z.writestr("監査ログ.csv", write_csv(audit_table(directory=directory)))
    return buf.getvalue()
