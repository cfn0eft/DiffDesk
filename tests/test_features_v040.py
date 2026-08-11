"""v0.4.0で追加した機能(表記ゆれ・エラーファイル・匿名化・許可値・整形)のテスト。"""
import pytest

from diffdesk.core import (
    ColumnPair,
    DiffDeskError,
    DiffOptions,
    DiffResult,
    MappingConfig,
    Table,
    ValidationRules,
    analyze_errors,
    anonymize_columns,
    apply_value_map,
    build_retry_table,
    build_sdl,
    clean_columns,
    cluster_column,
    fingerprint,
    split_column,
    validate_table,
)


class TestCluster:
    def test_fingerprint_variants(self):
        assert fingerprint("株式会社テスト") == fingerprint("テスト(株)")
        assert fingerprint("ﾃｽﾄ株式会社") == fingerprint("テスト")
        assert fingerprint("ABC Corp.") == fingerprint("abc corp")
        assert fingerprint("山田 太郎") == fingerprint("山田太郎")

    def test_cluster_column(self):
        t = Table(columns=["会社"], rows=[
            ["株式会社テスト"], ["テスト(株)"], ["株式会社テスト"],
            ["別会社"], ["山田商店"],
        ])
        clusters = cluster_column(t, "会社")
        assert len(clusters) == 1
        c = clusters[0]
        assert c.suggested == "株式会社テスト"  # 最頻値
        assert {v for v, _ in c.values} == {"株式会社テスト", "テスト(株)"}

    def test_apply_value_map(self):
        t = Table(columns=["会社"], rows=[["テスト(株)"], ["株式会社テスト"]])
        t, changed = apply_value_map(t, "会社", {"テスト(株)": "株式会社テスト"})
        assert changed == 1
        assert all(r[0] == "株式会社テスト" for r in t.rows)


class TestLoaderErrors:
    def make_error_table(self):
        return Table(
            columns=["氏名", "メール", "ERROR"],
            rows=[
                ["山田", "a@x.com", "REQUIRED_FIELD_MISSING:必須項目がありません: [Busho__c]"],
                ["鈴木", "bad", "INVALID_EMAIL_ADDRESS: Email: invalid email address: bad"],
                ["佐藤", "c@x.com", "REQUIRED_FIELD_MISSING:必須項目がありません: [Busho__c]"],
            ])

    def test_analyze(self):
        a = analyze_errors(self.make_error_table())
        assert a.error_column == "ERROR"
        assert a.total_rows == 3
        assert a.categories[0]["label"] == "必須項目が未入力"
        assert a.categories[0]["count"] == 2

    def test_analyze_requires_error_column(self):
        with pytest.raises(DiffDeskError):
            analyze_errors(Table(columns=["a"], rows=[["x"]]))

    def test_retry_table_drops_meta_columns(self):
        t = self.make_error_table()
        t.columns.append("STATUS")
        for r in t.rows:
            r.append("Error")
        retry = build_retry_table(t)
        assert retry.columns == ["氏名", "メール"]
        assert len(retry.rows) == 3


class TestAnonymize:
    def test_consistent_mapping(self):
        t = Table(columns=["氏名", "メール"], rows=[
            ["山田", "yamada@x.com"], ["鈴木", "suzuki@x.com"], ["山田", "yamada@x.com"]])
        out, changed = anonymize_columns(t, {"氏名": "name", "メール": "email"})
        assert out.rows[0][0] == out.rows[2][0]  # 同じ入力→同じダミー
        assert out.rows[0][0] != out.rows[1][0]
        assert out.rows[0][1].endswith("@example.com")
        assert changed == 6
        # 元テーブルは不変
        assert t.rows[0][0] == "山田"

    def test_empty_kept(self):
        t = Table(columns=["v"], rows=[[""]])
        out, changed = anonymize_columns(t, {"v": "name"})
        assert out.rows[0][0] == "" and changed == 0

    def test_unknown_mode(self):
        with pytest.raises(DiffDeskError):
            anonymize_columns(Table(columns=["v"], rows=[]), {"v": "nope"})


class TestAllowedValues:
    def test_allowed_values(self):
        t = Table(columns=["部署"], rows=[["営業部"], ["開発部"], ["営業"]])
        issues = validate_table(t, ValidationRules(
            allowed_values={"部署": ["営業部", "開発部"]}))
        assert len(issues) == 1
        assert issues[0].code == "allowed_values" and issues[0].row == 3


class TestCleanOps:
    def test_fill_down(self):
        t = Table(columns=["部署"], rows=[["営業部"], [""], [" "], ["開発部"], [""]])
        t, changed = clean_columns(t, ["部署"], ["fill_down"])
        assert [r[0] for r in t.rows] == ["営業部", "営業部", "営業部", "開発部", "開発部"]
        assert changed == 3

    def test_digits_only(self):
        t = Table(columns=["電話"], rows=[["03-1234-5678"], ["(090) 1111 2222"], ["０３−１２３４"]])
        t, _ = clean_columns(t, ["電話"], ["digits_only"])
        assert [r[0] for r in t.rows] == ["0312345678", "09011112222", "031234"]


class TestSplitColumn:
    def test_split(self):
        t = Table(columns=["氏名", "他"], rows=[["山田 太郎", "x"], ["鈴木 花子 J", "y"], ["単独", "z"]])
        t, parts = split_column(t, "氏名", " ")
        assert parts == 3
        assert t.columns == ["氏名_1", "氏名_2", "氏名_3", "他"]
        assert t.rows[0] == ["山田", "太郎", "", "x"]
        assert t.rows[2] == ["単独", "", "", "z"]

    def test_no_delimiter_found(self):
        t = Table(columns=["v"], rows=[["abc"]])
        with pytest.raises(DiffDeskError):
            split_column(t, "v", ",")


def test_sdl_escapes_relationship_colon():
    """親参照(Account:ExtId__c)の.sdl出力でコロンがエスケープされる。"""
    m = MappingConfig(pairs=[
        ColumnPair("取引先外部ID", "AccountRef", is_key=True, sf_field="Account:ExtId__c")])
    d = DiffResult(mapping=m, options=DiffOptions(), rows=[],
                   duplicates_a=[], duplicates_b=[])
    sdl = build_sdl(d)
    assert "Account\\:ExtId__c=Account\\:ExtId__c" in sdl
