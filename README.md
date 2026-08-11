<p align="center"><img src="diffdesk/static/logo.svg" width="380" alt="DiffDesk — CSV/Excel 突き合わせ・編集・Data Loader連携"></p>

# DiffDesk

**ヘッダーが異なる2つの表データを、任意の列マッピングで紐づけて突き合わせるローカルツール**です。
たとえば「元のExcelマスタ」と「Salesforceからエクスポートした CSV」を比較して差分を洗い出し、
そのまま **Salesforce Data Loader 用のアップサート/削除CSV** を生成できます。
CSVの編集・整形(グリッド編集・クレンジング・検証)もこれ1つで完結します。

- **完全ローカル動作** — データが外部に送信されることはありません(LLM等も不使用)
- **日本語データに強い** — CP932/UTF-8の自動判定、全角半角の同一視、先頭ゼロ(0001等)を壊さない設計
- **ロジックは純Python** — Web UIなしでもCLI・自作スクリプトから同じ機能を利用可能
- **1万〜10万行でも実用速度**(下記ベンチマーク参照)

---

## 画面

| 1. ファイル読み込み | 3. 差分結果 |
|---|---|
| ![ファイル読み込み](docs/images/tab1_load.png) | ![差分結果](docs/images/tab3_diff.png) |

| 2. 列マッピング | 4. グリッド編集 |
|---|---|
| ![列マッピング](docs/images/tab2_mapping.png) | ![グリッド編集](docs/images/tab4_grid.png) |

## 主な機能

| 分類 | 機能 |
|---|---|
| 読み込み | CSV / TSV / Excel(.xlsx)。エンコーディング自動判定(UTF-8 / BOM付き / CP932)+手動上書き、区切り文字自動判定、シート選択、ヘッダー行位置指定(1行目以外にヘッダーがあるExcel対応) |
| 比較 | 任意の列マッピング(ヘッダー名が違ってもOK)、複合キー対応、Aのみ/Bのみ/変更/一致の分類、キー重複・空キー警告、正規化オプション(空白・全半角・大小文字・数値許容誤差)、行フィルタ(比較前の絞り込み) |
| Salesforce | アップサートCSV(insert+update、外部ID指定、SF項目名へのヘッダー変換、親参照は `Account:ExtId__c` 形式に対応)、削除用CSV(Bのみ行のId)、Data Loader用 .sdl マッピング出力。**API接続はせずCSV生成のみ**(投入は既存のData Loaderで) |
| 投入後サポート | **投入検証**(件数照合と✔/✖の合否判定、検証レポート)、**Data Loaderエラーファイル分析**(error.csvの失敗理由を日本語で集計+対処ヒント+失敗行だけの再投入用CSV生成) |
| 編集 | グリッド編集(セル・行・列の追加削除、ソート、表示フィルタ、Enterで下セル移動、元に戻す)、検索・置換(正規表現対応)、一括クレンジング(空白除去・全半角変換・日付統一・数字のみ抽出・**空欄を上の値で埋める**) |
| データ品質 | **表記ゆれ検出→一括統一**(「株式会社テスト/テスト(株)」等を自動グルーピング)、検証(キー重複・必須列・形式・**許可値=ピックリスト**チェック。許可値は別ファイルの実値から自動生成可) |
| 変換・整形 | VLOOKUP的な列付加(キー照合でBの列をAに付加。SFのId列付与などに)、**列分割**(区切り文字で1列→複数列)、**匿名化**(sandbox用マスキング。同じ値には同じダミー値)、複数ファイル縦結合、文字コード一括変換、完全重複行削除、差分マージ |
| 出力 | CSV(UTF-8 / BOM付き / CP932、CRLF)、Excel(.xlsx)、色付きExcel差分レポート、差分レポートCSV |
| 再利用 | マッピング+比較オプション+行フィルタのプロファイル保存/読込(`~/.diffdesk/profiles/`)。Web画面とCLIで共用 |

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

依存を全バージョン固定+SHA256検証付きで導入します(改ざんされた配布物はインストールに失敗します):

```bash
git clone https://github.com/cfn0eft/CSV-.git && cd CSV-
pip install --require-hashes --only-binary :all: -r requirements.txt
pip install --no-deps -e .

# 開発(テスト実行)する場合は追加で
pip install --require-hashes --only-binary :all: -r requirements-dev.txt
```

依存は openpyxl / charset-normalizer / fastapi / uvicorn / python-multipart のみ(いずれも著名パッケージ)。
フロントエンドは自作・同梱で、CDN等の外部読み込みは一切ありません。

## 使い方 — 月次のSalesforce照合を例に

```bash
diffdesk          # または python -m diffdesk (既定: http://127.0.0.1:8765、--port で変更可)
```

1. **ファイル読み込み** — ファイルA(正マスタのExcel/CSV)とファイルB(SalesforceエクスポートCSV)をドロップ。
   文字化けしていたらエンコーディングを選び直して「再読込」(プレビューで直ったことを確認できます)
2. **列マッピング** — 「自動対応付け」を押し、紐づけキーにチェック(例: `社員番号 ↔ EmployeeNumber__c`)。
   Salesforce項目名が異なる場合は「SF項目名」欄に出力時の項目名を入力。
   設定は**プロファイルとして保存**しておくと、翌月からは読み込むだけで済みます
3. **差分結果** — サマリー(Aのみ/変更/Bのみ/一致)と変更セルのハイライトを確認。
   - 「**Data Loader用アップサートCSV**」→ 外部ID列とエンコーディング(既定: UTF-8 BOM付き)を選んで出力
   - 「**.sdlマッピング**」→ Data Loader側のフィールドマッピングもそのまま使えます
   - 削除運用がある場合は「削除用CSV」(Bのみ行のId)。内容を必ず確認してから投入してください
4. **グリッド編集** — 取り込み前の手直しやクレンジング・検証はこちら。編集後にCSV/Excelでダウンロード

### CLI(バッチ・定期実行向け)

```bash
# 差分サマリー+色付きExcelレポート
diffdesk diff master.xlsx sf_export.csv --profile 月次照合 --xlsx report.xlsx

# アップサートCSV+削除CSV+.sdl を一括生成
diffdesk upsert master.xlsx sf_export.csv --profile 月次照合 \
    --out upsert.csv --delete-out delete.csv --sdl mapping.sdl

# 文字コード変換 / 検証 / 結合
diffdesk convert in.csv --out out.csv --out-encoding cp932
diffdesk validate in.csv --keys 社員番号 --required 氏名 --format メール=email
diffdesk concat 4月.csv 5月.csv 6月.csv --out 上期.csv
```

`diffdesk diff --check` は差分があると終了コード1を返すので、定期ジョブでの検知にも使えます。

### プロファイル(マッピング定義)

Web画面で作成・保存するのが簡単です(`~/.diffdesk/profiles/*.json`)。JSONを直接書く場合の例:

```json
{
  "version": 1,
  "name": "月次照合",
  "mapping": { "pairs": [
    { "col_a": "社員番号", "col_b": "EmployeeNumber__c", "is_key": true },
    { "col_a": "氏名",     "col_b": "Name" },
    { "col_a": "部署",     "col_b": "Department__c", "sf_field": "Busho__c" }
  ]},
  "options": { "trim": true, "normalize_width": true },
  "external_id": "社員番号"
}
```

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
print(result.summary)   # {'only_a': …, 'only_b': …, 'changed': …, 'same': …, …}
upsert = build_upsert_table(result, external_id_col_a="社員番号")
Path("upsert.csv").write_bytes(write_csv(upsert))  # UTF-8 BOM付き・CRLF
```

## 性能(実測)

10万行 × 5列(変更5%・片側のみ数%)での実測値:

| 処理 | 1万行 | 10万行 |
|---|---|---|
| 読み込み(エンコーディング判定込み) | 0.1秒 | 1.3秒 |
| 差分実行 | 0.1秒 | 2.2秒 |
| アップサートCSV生成 | 瞬時 | 0.02秒 |
| 色付きExcelレポート | 1.5秒 | 12.5秒 |
| グリッド読込/一括保存(ブラウザ) | 瞬時 | 2秒 / 4秒 |

差分エンジンはキー辞書結合の O(n+m) で、行数にほぼ比例します。アップロード上限は100MBです。

## よくある質問

**Q. プレビューが文字化けする**
自動判定が外れています。エンコーディングのプルダウンから CP932 / UTF-8 等を選び直して「再読込」してください。プレビューが直れば正しい判定です。

**Q. CP932で保存しようとするとエラーになる**
CP932で表現できない文字(例: 𩸽、一部の環境依存文字)が含まれています。エラーに行・列・文字が表示されるので、該当セルを修正するか、UTF-8(BOM付き)で保存してください。

**Q. Data Loaderに投入するCSVはどの設定が良い?**
既定の **UTF-8(BOM付き)** を推奨します。Data Loader側の文字コード設定も UTF-8 にしてください。フィールドマッピングは同時出力される .sdl を読み込めば手作業不要です。

**Q. 削除用CSVは安全?**
「Bのみに存在する行のId」を出すだけで、このツールがSalesforceに直接触れることはありません。ただしData Loaderでの削除は取り消せないため、投入前に必ず内容を確認してください。

**Q. キー重複の警告が出た**
同じキー値の行が複数あると正しく突き合わせできないため、該当行は照合から除外して件数を表示しています。単体ファイル検証(グリッド編集タブ)で重複行を特定できます。

## 開発

```bash
python -m pytest -q                 # 全テスト(124件)
python scripts/make_fixtures.py     # テストフィクスチャ再生成
python scripts/make_requirements.py # 依存ロックファイル再生成
```

構成: `diffdesk/core/`(純Pythonロジック・web非依存をテストで担保)/ `diffdesk/web/`(FastAPI)/
`diffdesk/static/`(フロントエンド、ビルド不要のバニラJS)/ `diffdesk/cli.py`(CLI)。

## ライセンス

MIT
