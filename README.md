# DiffDesk — CSV/Excel 比較・編集・Data Loader用CSV生成ツール

ヘッダーが異なる2つの表データ(例: 元のExcelマスタと Salesforce からエクスポートしたCSV)を
**任意の列マッピングで紐づけて差分を検出**し、CSVの編集や
**Salesforce Data Loader 用のアップサート/削除CSV生成**までを行うローカルWebアプリ+CLIです。

- ロジックは純Python(`diffdesk/core/`)で、Web以外(CLI・自作スクリプト)からもそのまま使えます
- LLMは使用していません。すべてローカルで完結し、データが外部に送信されることはありません

## 主な機能

| 分類 | 機能 |
|---|---|
| 読み込み | CSV / TSV / Excel(.xlsx)。エンコーディング自動判定(UTF-8 / BOM付き / CP932)+手動上書き、区切り文字自動判定、シート選択、ヘッダー行位置指定 |
| 比較 | 任意の列マッピング(ヘッダー名が違ってもOK)、複合キー対応、Aのみ/Bのみ/変更/一致の分類、キー重複・空キー警告、正規化オプション(空白・全半角・大小文字・数値許容誤差)、行フィルタ |
| Salesforce | アップサートCSV(insert+update、外部ID、SF項目名へのヘッダー変換)、削除用CSV、Data Loader用 .sdl マッピング出力。**API接続はせずCSV生成のみ**(投入は既存のData Loaderで) |
| 編集 | グリッド編集(セル・行・列、undo)、検索・置換(正規表現対応)、一括クレンジング(空白除去・全半角変換・日付をyyyy-MM-ddに統一 等)、検証(キー重複・必須・メール等の形式) |
| 変換・整形 | VLOOKUP的な列付加(キー照合でB列をAに付加)、複数ファイル縦結合、文字コード一括変換、完全重複行削除、差分マージ(変更セルごとにA/B採用を選択) |
| 出力 | CSV(UTF-8 / BOM付き / CP932、CRLF)、Excel(.xlsx)、色付きExcel差分レポート、差分レポートCSV |
| 再利用 | マッピング+オプションのプロファイル保存/読込(`~/.diffdesk/profiles/`)。CLIとWebで共用 |

## インストール

Python 3.10 以上が必要です。

### かんたんインストール(GitHubから直接)

```bash
pip install "diffdesk @ git+https://github.com/cfn0eft/CSV-.git"
diffdesk   # ← これだけで起動(ブラウザが自動で開きます)
```

特定バージョンに固定したい場合はタグやコミットSHAを付けます:
`pip install "diffdesk @ git+https://github.com/cfn0eft/CSV-.git@v0.1.0"`

### 厳格インストール(ハッシュ検証付き・推奨)

リポジトリを取得したうえで、依存を全バージョン固定+SHA256検証付きで導入します
(改ざんされた配布物はインストールに失敗します):

```bash
git clone https://github.com/cfn0eft/CSV-.git && cd CSV-
pip install --require-hashes --only-binary :all: -r requirements.txt
pip install --no-deps -e .

# 開発(テスト実行)する場合は追加で
pip install --require-hashes --only-binary :all: -r requirements-dev.txt
```

依存は openpyxl / charset-normalizer / fastapi / uvicorn / python-multipart のみ
(いずれも著名パッケージ)。フロントエンドは自作・同梱で、CDN等の外部読み込みは一切ありません。

## 使い方(Webアプリ)

```bash
python -m diffdesk
```

ブラウザが自動で開きます(既定: http://127.0.0.1:8765、`--port` で変更可)。

1. **ファイル読み込み** — ファイルA(正マスタ)とファイルB(比較対象)をドロップ。
   文字化けしたらエンコーディングを選び直して「再読込」
2. **列マッピング** — 「自動対応付け」→ 紐づけキーにチェック(例: 社員番号 ↔ EmployeeNumber__c)。
   必要ならSF項目名・比較オプション・行フィルタを設定し、プロファイルとして保存
3. **差分結果** — サマリーと変更セルのハイライトを確認し、
   「Data Loader用アップサートCSV」等を出力。マージ結果の新規ファイル化も可能
4. **グリッド編集** — 読み込んだファイルやマージ結果をその場で編集・整形して保存/ダウンロード

## 使い方(CLI)

```bash
# 差分サマリー+色付きExcelレポート
python -m diffdesk diff master.xlsx sf_export.csv --profile 月次照合 --xlsx report.xlsx

# アップサートCSV+削除CSV+.sdl を一括生成
python -m diffdesk upsert master.xlsx sf_export.csv --profile 月次照合 \
    --out upsert.csv --delete-out delete.csv --sdl mapping.sdl

# 文字コード変換 / 検証 / 結合
python -m diffdesk convert in.csv --out out.csv --out-encoding cp932
python -m diffdesk validate in.csv --keys 社員番号 --required 氏名 --format メール=email
python -m diffdesk concat 4月.csv 5月.csv 6月.csv --out 上期.csv
```

プロファイル(マッピング定義)はWeb画面で作って保存するのが簡単です。JSONを直接書くこともできます。

## コアロジックをスクリプトから使う

```python
from pathlib import Path
from diffdesk.core import (
    ColumnPair, MappingConfig, load_table, diff_tables, build_upsert_table, write_csv,
)

a = load_table(Path("master.xlsx").read_bytes(), "master.xlsx")
b = load_table(Path("sf.csv").read_bytes(), "sf.csv")
mapping = MappingConfig(pairs=[
    ColumnPair("社員番号", "EmployeeNumber__c", is_key=True),
    ColumnPair("氏名", "Name"),
])
result = diff_tables(a, b, mapping)
print(result.summary)
upsert = build_upsert_table(result, external_id_col_a="社員番号")
Path("upsert.csv").write_bytes(write_csv(upsert))  # UTF-8 BOM付き・CRLF
```

## 開発

```bash
python -m pytest -q            # 全テスト
python scripts/make_fixtures.py     # テストフィクスチャ再生成
python scripts/make_requirements.py # 依存ロックファイル再生成
```

構成: `diffdesk/core/`(純Pythonロジック)/ `diffdesk/web/`(FastAPI)/
`diffdesk/static/`(フロントエンド)/ `diffdesk/cli.py`(CLI)。
`core` はwebライブラリに依存しないことをテストで担保しています。
