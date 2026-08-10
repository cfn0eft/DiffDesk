"""テスト用フィクスチャを決定的に再生成するスクリプト。

実行: python scripts/make_fixtures.py
生成物は tests/fixtures/ にコミットされるため、テストはこのスクリプトに依存しない。
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

MASTER_ROWS = [
    ["氏名", "メール", "部署", "社員番号", "入社日"],
    ["山田太郎", "taro@example.com", "営業部", "0001", "2020/4/1"],
    ["鈴木花子", "hanako@example.com", "開発部", "0002", "2021/10/15"],
    ["佐藤次郎", "jiro@example.com", "営業部", "0003", "2019/1/7"],
    ["高橋三郎", "saburo@example.com", "総務部", "0004", "2022/7/1"],
    ["田中④子", "yoshiko@example.com", "開発部", "0005", "2023/12/25"],  # ④=CP932拡張
]

# Salesforceエクスポート想定: 英語ヘッダー、Id列あり、値に差分あり
SF_ROWS = [
    ["Id", "Name", "Email", "Department__c", "EmployeeNumber__c"],
    ["a01000000000001", "山田太郎", "taro@example.com", "営業部", "0001"],
    ["a01000000000002", "鈴木花子", "hanako-new@example.com", "開発部", "0002"],  # メール変更
    ["a01000000000003", "佐藤次郎", "jiro@example.com", "人事部", "0003"],        # 部署変更
    ["a01000000000006", "伊藤六郎", "rokuro@example.com", "営業部", "0006"],      # Bのみ
]


def csv_bytes(rows: list[list[str]], encoding: str, delimiter: str = ",") -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=delimiter, lineterminator="\r\n")
    w.writerows(rows)
    return buf.getvalue().encode(encoding)


def make_xlsx() -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "社員マスタ"
    for row in MASTER_ROWS:
        ws.append(row)
    # 2枚目: タイトル行が1行目にあるシート(ヘッダー行指定のテスト用)
    ws2 = wb.create_sheet("タイトル付き")
    ws2.append(["社員一覧(2026年度)"])
    for row in MASTER_ROWS:
        ws2.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / "master_utf8.csv").write_bytes(csv_bytes(MASTER_ROWS, "utf-8"))
    (FIXTURES / "master_utf8_bom.csv").write_bytes(csv_bytes(MASTER_ROWS, "utf-8-sig"))
    (FIXTURES / "master_cp932.csv").write_bytes(csv_bytes(MASTER_ROWS, "cp932"))
    (FIXTURES / "master_tab.tsv").write_bytes(csv_bytes(MASTER_ROWS, "utf-8", "\t"))
    (FIXTURES / "salesforce_export.csv").write_bytes(csv_bytes(SF_ROWS, "utf-8"))
    (FIXTURES / "master.xlsx").write_bytes(make_xlsx())
    print(f"fixtures written to {FIXTURES}")


if __name__ == "__main__":
    main()
