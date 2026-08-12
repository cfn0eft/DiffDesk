"""v0.14.0 キーなし比較(行番号 / 行の内容)のテスト。"""
import pytest

from diffdesk.core import (
    ColumnPair,
    DiffDeskError,
    DiffOptions,
    MappingConfig,
    Table,
    diff_tables,
)


def make_mapping(key_mode: str) -> MappingConfig:
    return MappingConfig(pairs=[
        ColumnPair("名前", "name"),
        ColumnPair("値", "val"),
    ], key_mode=key_mode)


class TestRowNumberMode:
    def test_equal_length_pairing(self):
        a = Table(columns=["名前", "値"], rows=[["山田", "1"], ["佐藤", "2"]])
        b = Table(columns=["name", "val"], rows=[["山田", "1"], ["佐藤", "9"]])
        r = diff_tables(a, b, make_mapping("row_number"))
        assert r.summary["same"] == 1
        assert r.summary["changed"] == 1
        changed = next(row for row in r.rows if row.status == "changed")
        assert changed.cell_diffs[0].value_a == "2"
        assert changed.cell_diffs[0].value_b == "9"

    def test_keys_are_row_numbers_in_order(self):
        a = Table(columns=["名前", "値"], rows=[["a", "1"], ["b", "2"], ["c", "3"]])
        b = Table(columns=["name", "val"], rows=[["a", "1"], ["b", "2"], ["c", "3"]])
        r = diff_tables(a, b, make_mapping("row_number"))
        assert [row.key for row in r.rows] == [("行1",), ("行2",), ("行3",)]

    def test_longer_a_tail_becomes_only_a(self):
        a = Table(columns=["名前", "値"], rows=[["a", "1"], ["b", "2"], ["c", "3"]])
        b = Table(columns=["name", "val"], rows=[["a", "1"]])
        r = diff_tables(a, b, make_mapping("row_number"))
        assert r.summary == {
            "only_a": 2, "only_b": 0, "changed": 0, "same": 1,
            "duplicates_a": 0, "duplicates_b": 0,
            "empty_key_a": 0, "empty_key_b": 0,
        }
        tail = [row for row in r.rows if row.status == "only_a"]
        assert [row.key for row in tail] == [("行2",), ("行3",)]
        assert all(row.row_b is None for row in tail)

    def test_longer_b_tail_becomes_only_b(self):
        a = Table(columns=["名前", "値"], rows=[["a", "1"]])
        b = Table(columns=["name", "val"], rows=[["a", "1"], ["x", "8"], ["y", "9"]])
        r = diff_tables(a, b, make_mapping("row_number"))
        assert r.summary["only_b"] == 2
        assert r.summary["same"] == 1
        tail = [row for row in r.rows if row.status == "only_b"]
        assert [row.key for row in tail] == [("行2",), ("行3",)]
        assert all(row.row_a is None for row in tail)

    def test_zero_padded_keys_for_10_plus_rows(self):
        a = Table(columns=["名前", "値"], rows=[[f"r{i}", str(i)] for i in range(12)])
        b = Table(columns=["name", "val"], rows=[[f"r{i}", str(i)] for i in range(12)])
        r = diff_tables(a, b, make_mapping("row_number"))
        keys = [row.key[0] for row in r.rows]
        assert keys[0] == "行01"
        assert keys[-1] == "行12"
        # ソートしても行順が保たれる桁揃え
        assert sorted(keys) == keys

    def test_normalization_applies_to_values(self):
        a = Table(columns=["名前", "値"], rows=[["山田", "1551"]])
        b = Table(columns=["name", "val"], rows=[["山田", "1551.0"]])
        r = diff_tables(a, b, make_mapping("row_number"))
        assert r.summary["same"] == 1
        off = DiffOptions(normalize_numeric=False)
        assert diff_tables(a, b, make_mapping("row_number"), off).summary["changed"] == 1

    def test_no_duplicate_or_empty_key_reports(self):
        a = Table(columns=["名前", "値"], rows=[["", ""], ["", ""]])
        b = Table(columns=["name", "val"], rows=[["", ""], ["", ""]])
        r = diff_tables(a, b, make_mapping("row_number"))
        assert r.duplicates_a == [] and r.duplicates_b == []
        assert r.empty_key_a == 0 and r.empty_key_b == 0
        assert r.summary["same"] == 2

    def test_empty_tables(self):
        a = Table(columns=["名前", "値"], rows=[])
        b = Table(columns=["name", "val"], rows=[])
        r = diff_tables(a, b, make_mapping("row_number"))
        assert r.rows == []


class TestContentMode:
    def test_matching_rows_same_regardless_of_order(self):
        a = Table(columns=["名前", "値"], rows=[["山田", "1"], ["佐藤", "2"]])
        b = Table(columns=["name", "val"], rows=[["佐藤", "2"], ["山田", "1"]])
        r = diff_tables(a, b, make_mapping("content"))
        assert r.summary["same"] == 2
        assert r.summary["changed"] == 0

    def test_non_matching_rows_split_only_a_only_b(self):
        a = Table(columns=["名前", "値"], rows=[["山田", "1"], ["佐藤", "2"]])
        b = Table(columns=["name", "val"], rows=[["山田", "1"], ["佐藤", "9"]])
        r = diff_tables(a, b, make_mapping("content"))
        # 内容比較では changed は出ない: 不一致は only_a / only_b に分かれる
        assert r.summary["changed"] == 0
        assert r.summary["same"] == 1
        assert r.summary["only_a"] == 1
        assert r.summary["only_b"] == 1

    def test_duplicate_content_rows_reported(self):
        a = Table(columns=["名前", "値"], rows=[["山田", "1"], ["山田", "1"]])
        b = Table(columns=["name", "val"], rows=[["山田", "1"]])
        r = diff_tables(a, b, make_mapping("content"))
        assert r.duplicates_a == [("山田", "1")]

    def test_normalization_applies_to_content_keys(self):
        a = Table(columns=["名前", "値"], rows=[["ﾔﾏﾀﾞ ", "100.0"]])
        b = Table(columns=["name", "val"], rows=[["ヤマダ", "100"]])
        r = diff_tables(a, b, make_mapping("content"))
        assert r.summary["same"] == 1


class TestKeyModeValidation:
    def test_keyless_allowed_for_row_number_and_content(self):
        a = Table(columns=["x"], rows=[["1"]])
        b = Table(columns=["y"], rows=[["1"]])
        for mode in ("row_number", "content"):
            m = MappingConfig(pairs=[ColumnPair("x", "y")], key_mode=mode)
            assert diff_tables(a, b, m).summary["same"] == 1

    def test_columns_mode_still_requires_key(self):
        a = Table(columns=["x"], rows=[])
        b = Table(columns=["y"], rows=[])
        m = MappingConfig(pairs=[ColumnPair("x", "y")], key_mode="columns")
        with pytest.raises(DiffDeskError):
            diff_tables(a, b, m)

    def test_bad_key_mode_rejected(self):
        a = Table(columns=["x"], rows=[])
        b = Table(columns=["y"], rows=[])
        m = MappingConfig(pairs=[ColumnPair("x", "y", is_key=True)], key_mode="fuzzy")
        with pytest.raises(DiffDeskError):
            diff_tables(a, b, m)

    def test_key_mode_roundtrip(self):
        m = MappingConfig(pairs=[ColumnPair("x", "y")], key_mode="row_number")
        d = m.to_dict()
        assert d["key_mode"] == "row_number"
        m2 = MappingConfig.from_dict(d)
        assert m2.key_mode == "row_number"
        # 省略時は従来どおり columns
        assert MappingConfig.from_dict({"pairs": []}).key_mode == "columns"
