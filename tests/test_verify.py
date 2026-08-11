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
        assert [(x.col_a, x.col_b) for x in s] == [
            ("Name", "ｎａｍｅ"), ("Email", "Email")]

    def test_value_based(self):
        a = Table(columns=["キー", "所属"], rows=[
            ["A-1", "営業部"], ["A-2", "開発部"], ["A-3", "総務部"]])
        b = Table(columns=["ExtKey__c", "Busho__c"], rows=[
            ["A-1", "営業部"], ["A-2", "開発部"], ["A-3", "人事部"]])
        s = suggest_mapping(a, b)
        by = {x.col_a: x for x in s}
        assert by["キー"].col_b == "ExtKey__c"
        assert by["所属"].col_b == "Busho__c"

    def test_dictionary_name_match_without_values(self):
        """値が無くても辞書+トークン分解で日本語↔SF API名を対応付けられる。"""
        a = Table(columns=["社員番号", "氏名", "メールアドレス", "電話番号", "入社日"], rows=[])
        b = Table(columns=["EmployeeNumber__c", "Name", "Email", "Phone", "HireDate__c"], rows=[])
        by = {x.col_a: x.col_b for x in suggest_mapping(a, b)}
        assert by == {
            "社員番号": "EmployeeNumber__c",
            "氏名": "Name",
            "メールアドレス": "Email",
            "電話番号": "Phone",
            "入社日": "HireDate__c",
        }

    def test_value_match_survives_sf_reformatting(self):
        """SF側で日付・数値の表記が変わっても値ベースで対応できる。"""
        a = Table(columns=["開始", "額"], rows=[
            ["2020/4/1", "1000"], ["2021/10/15", "2500.0"], ["2019/1/7", "99"]])
        b = Table(columns=["StartDate__c", "Kingaku__c"], rows=[
            ["2020-04-01", "1000.0"], ["2021-10-15", "2500"], ["2019-01-07", "99"]])
        by = {x.col_a: x.col_b for x in suggest_mapping(a, b)}
        assert by.get("開始") == "StartDate__c"
        assert by.get("額") == "Kingaku__c"

    def test_constant_column_excluded(self):
        a = Table(columns=["flag"], rows=[["Y"], ["Y"], ["Y"]])
        b = Table(columns=["Zk__c"], rows=[["Y"], ["Y"], ["Y"]])
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
        assert s[0].col_b == "Email"  # 名前+値の両証拠がある方を優先

    def test_name_and_value_combined_beats_name_only(self):
        """同名列が複数あっても、値の証拠がある方に割り当てる。"""
        a = Table(columns=["日付"], rows=[["2020/1/1"], ["2020/2/1"]])
        b = Table(columns=["EndDate__c", "StartDate__c"], rows=[
            ["2099-12-31", "2020-01-01"], ["2099-12-31", "2020-02-01"]])
        s = suggest_mapping(a, b)
        assert s[0].col_b == "StartDate__c"
        assert s[0].method == "name+value"


def test_key_candidate_detection(master_utf8, sf_export):
    """両側で値がユニークな列ペアがキー候補として報告される。"""
    a, b = load_csv(master_utf8), load_csv(sf_export)
    s = suggest_mapping(a, b)
    by = {x.col_a: x for x in s}
    assert by["社員番号"].key_candidate  # 両側ユニーク
    assert not by["部署"].key_candidate  # 部署は重複あり


def test_fixture_value_mapping(master_utf8, sf_export):
    """フィクスチャ: 日本語ヘッダー vs SF API名でも値ベースで対応付けできる。"""
    a, b = load_csv(master_utf8), load_csv(sf_export)
    s = suggest_mapping(a, b)
    by = {x.col_a: x.col_b for x in s}
    assert by.get("社員番号") == "EmployeeNumber__c"
    assert by.get("氏名") == "Name"
