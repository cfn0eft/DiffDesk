"""v0.20.0 差異の自動分類のテスト。"""
from diffdesk.core import (
    ColumnPair,
    MappingConfig,
    Table,
    classify_diff,
    classify_value_pair,
    diff_tables,
    value_rules_for_cause,
)


class TestClassifyValuePair:
    def test_same(self):
        assert classify_value_pair("a", "a") == "same"

    def test_space(self):
        assert classify_value_pair("山田 太郎", "山田太郎") == "space"
        assert classify_value_pair(" abc ", "abc") == "space"

    def test_width(self):
        assert classify_value_pair("ﾔﾏﾀﾞ", "ヤマダ") == "width"
        assert classify_value_pair("ＡＢＣ", "ABC") == "width"

    def test_case(self):
        assert classify_value_pair("Tokyo", "TOKYO") == "case"

    def test_numeric(self):
        assert classify_value_pair("1550", "1550.0") == "numeric"
        assert classify_value_pair("100.50", "100.5") == "numeric"

    def test_date(self):
        assert classify_value_pair("2020/1/5", "2020-01-05") == "date"

    def test_zeropad(self):
        assert classify_value_pair("1", "0001") == "zeropad"
        # 0001はnumericの_canon_decimalでは変わらない(小数点なし)ことの確認
        assert classify_value_pair("0001", "1") == "zeropad"

    def test_combo(self):
        # 全角+空白の複合
        assert classify_value_pair("ＡＢＣ Ｄ", "ABCD") == "combo"

    def test_real(self):
        assert classify_value_pair("山田", "佐藤") == "real"
        assert classify_value_pair("100", "200") == "real"
        assert classify_value_pair("", "x") == "real"


class TestClassifyDiff:
    def make_diff(self):
        a = Table(columns=["id", "名前", "数", "日付"], rows=[
            ["1", "山田 太郎", "100", "2020/1/5"],
            ["2", "佐藤花子", "200.0", "2021/2/6"],
            ["3", "鈴木一郎", "300", "2022/3/7"],
        ], name="a.csv")
        b = Table(columns=["id", "名前", "数", "日付"], rows=[
            ["1", "山田太郎", "100", "2020-01-05"],   # space + date
            ["2", "佐藤花子", "200", "2021-02-06"],   # numeric + date
            ["3", "田中次郎", "300", "2022/3/7"],     # real
        ], name="b.csv")
        m = MappingConfig(pairs=[
            ColumnPair("id", "id", is_key=True), ColumnPair("名前", "名前"),
            ColumnPair("数", "数"), ColumnPair("日付", "日付"),
        ])
        # 正規化を全部切って差異を出す
        from diffdesk.core import DiffOptions
        opts = DiffOptions(trim=False, normalize_width=False,
                           normalize_numeric=False)
        return diff_tables(a, b, m, opts)

    def test_counts_and_order(self):
        r = classify_diff(self.make_diff())
        by = {c["cause"]: c for c in r["causes"]}
        assert r["total"] == 5
        assert by["space"]["count"] == 1
        assert by["numeric"]["count"] == 1
        assert by["date"]["count"] == 2
        assert by["real"]["count"] == 1
        # CAUSES順(realが最後)
        assert [c["cause"] for c in r["causes"]] == ["space", "numeric", "date", "real"]

    def test_columns_and_samples(self):
        r = classify_diff(self.make_diff())
        date = next(c for c in r["causes"] if c["cause"] == "date")
        assert date["columns"] == {"日付": 2}
        assert date["rule_count"] == 2
        assert len(date["samples"]) == 2

    def test_value_rules_for_cause(self):
        d = self.make_diff()
        rules = value_rules_for_cause(d, "date")
        assert len(rules) == 2
        assert all(r["type"] == "value" and r["col_a"] == "日付" for r in rules)
        assert value_rules_for_cause(d, "zeropad") == []


class TestFindFreePort:
    def test_skips_busy_port(self):
        import socket
        from diffdesk.__main__ import _find_free_port
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        busy = s.getsockname()[1]
        try:
            free = _find_free_port("127.0.0.1", busy)
            assert free is not None and free != busy
        finally:
            s.close()

    def test_free_port_returned_as_is(self):
        import socket
        from diffdesk.__main__ import _find_free_port
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        p = s.getsockname()[1]
        s.close()
        assert _find_free_port("127.0.0.1", p) == p
