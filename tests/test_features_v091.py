"""v0.9.1: 数値表記の同一視(1551 = 1551.0)のテスト。"""
from diffdesk.core import ColumnPair, DiffOptions, MappingConfig, Table, diff_tables
from diffdesk.core.normalize import make_normalizer, values_equal


def norm(**kw):
    return make_normalizer(DiffOptions(**kw))


class TestNumericNormalize:
    def test_trailing_zero_equal(self):
        n = norm()
        assert values_equal("1551", "1551.0", n)
        assert values_equal("1551.0", "1551.00", n)
        assert values_equal("1551.5", "1551.50", n)
        assert values_equal("0", "0.0", n)
        assert values_equal("-3", "-3.0", n)

    def test_zero_variants(self):
        n = norm()
        assert values_equal("0", "-0.0", n)
        assert values_equal("0", "0.000", n)

    def test_leading_zero_ids_untouched(self):
        n = norm()
        # 小数点を含まないIDは一切触らない(先頭ゼロ保持の原則)
        assert not values_equal("0001", "1", n)
        # 小数点付きなら末尾ゼロだけ落ちる(先頭ゼロは残る)
        assert values_equal("0001", "0001.0", n)
        assert not values_equal("0001.0", "1", n)

    def test_non_numeric_untouched(self):
        n = norm()
        assert not values_equal("abc.0", "abc", n)
        assert not values_equal("12.3.4", "12.34", n)
        assert not values_equal("1,551", "1551.0", n)  # 桁区切りは対象外
        assert not values_equal("1551.5", "1551", n)   # 実際に値が違うものは差異のまま

    def test_fullwidth_numeric(self):
        n = norm()
        assert values_equal("1551", "1551.0", n)  # NFKC後に数値正規化

    def test_option_off(self):
        n = norm(normalize_numeric=False)
        assert not values_equal("1551", "1551.0", n)

    def test_options_roundtrip(self):
        o = DiffOptions.from_dict({"normalize_numeric": False})
        assert o.normalize_numeric is False
        assert DiffOptions.from_dict({}).normalize_numeric is True
        assert "normalize_numeric" in DiffOptions().to_dict()


class TestNumericDiff:
    def make(self, options=None):
        a = Table(columns=["id", "数量"], rows=[["1551", "12"], ["0002", "5"]])
        b = Table(columns=["Id", "Qty"], rows=[["1551.0", "12.0"], ["0002", "5"]])
        m = MappingConfig(pairs=[ColumnPair("id", "Id", is_key=True),
                                 ColumnPair("数量", "Qty")])
        return diff_tables(a, b, m, options)

    def test_key_and_value_match_by_default(self):
        d = self.make()
        # キー 1551 vs 1551.0 も一致し、数量 12 vs 12.0 も差異にならない
        assert d.summary == {"only_a": 0, "only_b": 0, "changed": 0, "same": 2,
                             "duplicates_a": 0, "duplicates_b": 0,
                             "empty_key_a": 0, "empty_key_b": 0}

    def test_option_off_reports_diff(self):
        d = self.make(DiffOptions(normalize_numeric=False))
        assert d.summary["only_a"] == 1 and d.summary["only_b"] == 1  # キー不一致
