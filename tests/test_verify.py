import pytest

from diffdesk.core import (
    ColumnPair,
    MappingConfig,
    Table,
    build_verification,
    build_verification_table,
    build_verification_xlsx,
    diff_tables,
    load_csv,
    load_excel,
    suggest_mapping,
)


def mapping() -> MappingConfig:
    return MappingConfig(pairs=[
        ColumnPair("社員番号", "EmployeeNumber__c", is_key=True),
        ColumnPair("氏名", "Name"),
        ColumnPair("メール", "Email"),
        ColumnPair("部署", "Department__c"),
    ])


@pytest.fixture
def diff(master_utf8, sf_export):
    return diff_tables(load_csv(master_utf8), load_csv(sf_export), mapping())


class TestVerification:
    def test_fixture_fails(self, diff):
        v = build_verification(diff)
        assert not v.passed
        assert v.only_a == 2 and v.changed == 2 and v.only_b == 1
        assert v.rows_a == 5 and v.rows_b == 4 and v.matched == 3
        assert len(v.problems) == 3

    def test_perfect_load_passes(self):
        a = Table(columns=["id", "v"], rows=[["1", "x"], ["2", "y"]])
        b = Table(columns=["id", "v"], rows=[["1", "x"], ["2", "y"]])
        m = MappingConfig(pairs=[ColumnPair("id", "id", is_key=True), ColumnPair("v", "v")])
        v = build_verification(diff_tables(a, b, m))
        assert v.passed and v.same == 2 and not v.problems

    def test_only_b_tolerance(self):
        a = Table(columns=["id", "v"], rows=[["1", "x"]])
        b = Table(columns=["id", "v"], rows=[["1", "x"], ["9", "既存"]])
        m = MappingConfig(pairs=[ColumnPair("id", "id", is_key=True), ColumnPair("v", "v")])
        d = diff_tables(a, b, m)
        assert not build_verification(d).passed
        v = build_verification(d, only_b_is_error=False)
        assert v.passed
        assert any(p.startswith("(許容)") for p in v.problems)

    def test_unmatchable_fails(self):
        a = Table(columns=["id", "v"], rows=[["1", "x"], ["1", "y"]])  # 重複キー
        b = Table(columns=["id", "v"], rows=[])
        m = MappingConfig(pairs=[ColumnPair("id", "id", is_key=True), ColumnPair("v", "v")])
        v = build_verification(diff_tables(a, b, m))
        assert not v.passed and v.unmatchable_a == 1

    def test_dict_shape(self, diff):
        d = build_verification(diff).to_dict()
        assert 0 <= d["match_rate"] <= 1
        assert d["passed"] is False


class TestVerificationReport:
    def test_table_only_problems(self, diff):
        t = build_verification_table(diff)
        assert len(t.rows) == 5  # 2 only_a + 2 changed + 1 only_b
        assert all(r[0] != "一致" for r in t.rows)
        t2 = build_verification_table(diff, only_b_is_error=False)
        assert len(t2.rows) == 4  # Bのみを除外

    def test_xlsx_report(self, diff):
        raw = build_verification_xlsx(diff)
        t = load_excel(raw, sheet="検証結果")
        assert "要確認" in t.columns[0] or any("要確認" in str(c) for c in t.columns)
        t2 = load_excel(raw, sheet="問題レコード")
        assert len(t2.rows) == 5


class TestSuggestMapping:
    def test_name_and_nfkc(self):
        a = Table(columns=["Name", "Email"], rows=[])
        b = Table(columns=["ｎａｍｅ", "Email"], rows=[])
        s = suggest_mapping(a, b)
        assert [(x.col_a, x.col_b, x.method) for x in s] == [
            ("Name", "ｎａｍｅ", "name"), ("Email", "Email", "name")]

    def test_value_based(self):
        a = Table(columns=["社員番号", "所属"], rows=[
            ["0001", "営業部"], ["0002", "開発部"], ["0003", "総務部"]])
        b = Table(columns=["EmployeeNumber__c", "Department__c"], rows=[
            ["0001", "営業部"], ["0002", "開発部"], ["0003", "人事部"]])
        s = suggest_mapping(a, b)
        by = {x.col_a: x for x in s}
        assert by["社員番号"].col_b == "EmployeeNumber__c"
        assert by["社員番号"].method == "value"
        assert by["所属"].col_b == "Department__c"

    def test_constant_column_excluded(self):
        a = Table(columns=["flag"], rows=[["Y"], ["Y"], ["Y"]])
        b = Table(columns=["Status__c"], rows=[["Y"], ["Y"], ["Y"]])
        assert suggest_mapping(a, b) == []

    def test_low_overlap_excluded(self):
        a = Table(columns=["x"], rows=[["a"], ["b"], ["c"], ["d"]])
        b = Table(columns=["y"], rows=[["a"], ["z"], ["w"], ["q"]])
        assert suggest_mapping(a, b) == []  # 重なり1/4 < 0.5

    def test_greedy_best_match(self):
        a = Table(columns=["メール"], rows=[["a@x.com"], ["b@x.com"]])
        b = Table(columns=["Backup__c", "Email"], rows=[
            ["a@x.com", "a@x.com"], ["old@x.com", "b@x.com"]])
        s = suggest_mapping(a, b)
        assert len(s) == 1
        assert s[0].col_b == "Email"  # 重なりが大きい方に割当


def test_fixture_value_mapping(master_utf8, sf_export):
    """フィクスチャ: 日本語ヘッダー vs SF API名でも値ベースで対応付けできる。"""
    a, b = load_csv(master_utf8), load_csv(sf_export)
    s = suggest_mapping(a, b)
    by = {x.col_a: x.col_b for x in s}
    assert by.get("社員番号") == "EmployeeNumber__c"
    assert by.get("氏名") == "Name"
