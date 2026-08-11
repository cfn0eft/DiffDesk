"""v0.5.0機能(ロールバック・健康診断・あいまい突合・住所・HTML・クロス集計・範囲)のテスト。"""
import pytest

from diffdesk.core import (
    ColumnPair,
    DiffDeskError,
    MappingConfig,
    Table,
    ValidationRules,
    build_html_report,
    build_restore_table,
    build_undo_delete_table,
    compare_profiles,
    crosstab,
    diff_tables,
    fuzzy_match,
    build_linked_table,
    load_csv,
    profile_table,
    split_address,
    split_address_column,
    validate_table,
)


def mapping() -> MappingConfig:
    return MappingConfig(pairs=[
        ColumnPair("社員番号", "EmployeeNumber__c", is_key=True),
        ColumnPair("氏名", "Name"),
        ColumnPair("メール", "Email"),
        ColumnPair("部署", "Department__c", sf_field="Busho__c"),
    ])


@pytest.fixture
def diff(master_utf8, sf_export):
    return diff_tables(load_csv(master_utf8), load_csv(sf_export), mapping())


class TestRollback:
    def test_restore_table_uses_b_values(self, diff):
        t = build_restore_table(diff)
        assert t.columns == ["EmployeeNumber__c", "Name", "Email", "Busho__c"]
        assert len(t.rows) == 2  # changed行のみ
        row = next(r for r in t.rows if r[0] == "0002")
        assert row[2] == "hanako-new@example.com"  # 投入前(B)の値

    def test_restore_requires_changes(self):
        a = Table(columns=["id", "v"], rows=[["1", "x"]])
        d = diff_tables(a, a, MappingConfig(pairs=[
            ColumnPair("id", "id", is_key=True), ColumnPair("v", "v")]))
        with pytest.raises(DiffDeskError):
            build_restore_table(d)

    def test_undo_delete_from_success(self):
        s = Table(columns=["ID", "STATUS", "Name"],
                  rows=[["a01x", "Item Created", "新規"],
                        ["a01y", "Item Updated", "更新"],
                        ["a01z", "Item Created", "新規2"]])
        undo, skipped = build_undo_delete_table(s)
        assert undo.columns == ["Id"]
        assert [r[0] for r in undo.rows] == ["a01x", "a01z"]
        assert skipped == 1

    def test_undo_delete_requires_id(self):
        with pytest.raises(DiffDeskError):
            build_undo_delete_table(Table(columns=["Name"], rows=[["x"]]))


class TestHealthProfile:
    def test_profile(self, master_utf8):
        p = profile_table(load_csv(master_utf8))
        assert p["rows"] == 5
        by = {c["name"]: c for c in p["columns"]}
        assert by["部署"]["unique"] == 3
        assert by["社員番号"]["type"] == "数値" or by["社員番号"]["type"] == "文字列"
        assert by["入社日"]["type"] == "日付"
        assert by["氏名"]["empty_rate"] == 0.0

    def test_compare_detects_changes(self, master_utf8):
        base = profile_table(load_csv(master_utf8))
        cur_table = load_csv(master_utf8)
        # 行数を大幅減+部署に未知の値+新列
        cur_table.rows = cur_table.rows[:2]
        cur_table.rows[0][cur_table.col_index("部署")] = "未知部署"
        cur_table.columns.append("新列")
        for r in cur_table.rows:
            r.append("x")
        warnings = compare_profiles(base, profile_table(cur_table))
        text = " ".join(w["message"] for w in warnings)
        assert "行数" in text and "新しい列" in text and "未知部署" in text

    def test_compare_no_changes(self, master_utf8):
        p = profile_table(load_csv(master_utf8))
        warnings = compare_profiles(p, p)
        assert warnings[0]["level"] == "info"


class TestFuzzy:
    def test_fuzzy_match_typos(self):
        a = Table(columns=["氏名", "電話"], rows=[
            ["山田太郎", "090-1111-2222"], ["鈴木花子", "080-3333-4444"], ["独自太郎", "000"]])
        b = Table(columns=["name", "tel"], rows=[
            ["山田 太郎", "09011112222"], ["鈴木花子", "080-3333-4444"], ["別人", "999"]])
        cands = fuzzy_match(a, b, pairs=[("氏名", "name"), ("電話", "tel")], threshold=0.7)
        pairs = {(c.index_a, c.index_b) for c in cands}
        assert (0, 0) in pairs and (1, 1) in pairs
        assert not any(ia == 2 for ia, _ in pairs)

    def test_linked_table(self):
        a = Table(columns=["氏名"], rows=[["山田"]])
        b = Table(columns=["氏名"], rows=[["山田"]])
        out = build_linked_table(a, b, [{"index_a": 0, "index_b": 0, "score": 0.9}])
        assert out.columns == ["氏名", "氏名_B", "突合スコア"]
        assert out.rows[0] == ["山田", "山田", "0.9"]

    def test_requires_pairs(self):
        t = Table(columns=["x"], rows=[])
        with pytest.raises(DiffDeskError):
            fuzzy_match(t, t, pairs=[])


class TestAddress:
    def test_split_address_full(self):
        r = split_address("〒100-0001 東京都千代田区千代田1-1 パレスビル3F")
        assert r == {"zip": "100-0001", "prefecture": "東京都",
                     "city": "千代田区", "rest": "千代田1-1 パレスビル3F"}

    def test_split_address_seirei(self):
        r = split_address("神奈川県横浜市西区みなとみらい2-2-1")
        assert r["prefecture"] == "神奈川県"
        assert r["city"] == "横浜市西区"

    def test_split_address_gun(self):
        r = split_address("愛知県愛知郡東郷町春木1")
        assert r["city"] == "愛知郡東郷町"

    def test_split_column(self):
        t = Table(columns=["住所"], rows=[["東京都港区芝1-2-3"], ["大阪府大阪市北区梅田1"]])
        t, parsed = split_address_column(t, "住所")
        assert parsed == 2
        assert t.columns == ["住所_郵便番号", "住所_都道府県", "住所_市区町村", "住所_以降"]
        assert t.rows[0][1] == "東京都" and t.rows[0][2] == "港区"

    def test_split_column_no_address(self):
        t = Table(columns=["v"], rows=[["ただの文字列"]])
        with pytest.raises(DiffDeskError):
            split_address_column(t, "v")


class TestHtmlReport:
    def test_html_selfcontained(self, diff):
        html_text = build_html_report(diff)
        assert "<!DOCTYPE html>" in html_text
        assert "hanako-new@example.com" in html_text
        assert "要確認" in html_text
        assert "http" not in html_text.split("</head>")[0].lower().replace("http-equiv", "")  # 外部参照なし


class TestCrosstab:
    def test_two_way(self):
        t = Table(columns=["群", "性別"], rows=[
            ["G1", "雄"], ["G1", "雄"], ["G1", "雌"], ["G2", "雌"]])
        out = crosstab(t, "群", "性別")
        assert out.columns == ["群\\性別", "雄", "雌", "(合計)"]
        g1 = next(r for r in out.rows if r[0] == "G1")
        assert g1 == ["G1", "2", "1", "3"]
        total = next(r for r in out.rows if r[0] == "(合計)")
        assert total == ["(合計)", "2", "2", "4"]

    def test_one_way(self):
        t = Table(columns=["群"], rows=[["G1"], ["G1"], ["G2"]])
        out = crosstab(t, "群")
        assert out.rows[0] == ["G1", "2"]


class TestRanges:
    def test_range_check(self):
        t = Table(columns=["ALT"], rows=[["25"], ["70"], ["5"], ["abc"], [""]])
        issues = validate_table(t, ValidationRules(ranges={"ALT": [10, 50]}))
        assert len(issues) == 3
        assert issues[0].row == 2 and "範囲外" in issues[0].message
        assert issues[1].row == 3
        assert "数値ではない" in issues[2].message

    def test_one_sided(self):
        t = Table(columns=["体重"], rows=[["-1"], ["100"]])
        issues = validate_table(t, ValidationRules(ranges={"体重": [0, None]}))
        assert len(issues) == 1 and issues[0].row == 1
