"""v0.8.0機能(手動紐づけ)のテスト。"""
import pytest

from diffdesk.core import (
    ColumnPair,
    DiffDeskError,
    MappingConfig,
    Table,
    apply_known_diffs,
    apply_manual_pairs,
    build_upsert_table,
    build_verification,
    diff_tables,
    list_unmatched,
    validate_manual_pair,
)


def make_diff():
    a = Table(columns=["id", "名前", "部署"],
              rows=[["1", "山田", "営業"], ["2", "鈴木", "開発"], ["3", "新規", "総務"]])
    b = Table(columns=["id", "name", "dept"],
              rows=[["1", "山田", "人事"], ["2", "すずき", "開発x"], ["9", "新規", "総務"]])
    m = MappingConfig(pairs=[
        ColumnPair("id", "id", is_key=True),
        ColumnPair("名前", "name"),
        ColumnPair("部署", "dept"),
    ])
    return diff_tables(a, b, m)


class TestApplyManualPairs:
    def test_pair_merges_rows(self):
        d = make_diff()
        out = apply_manual_pairs(d, [{"key_a": ["3"], "key_b": ["9"]}])
        assert out.summary["only_a"] == 0 and out.summary["only_b"] == 0
        r = next(r for r in out.rows if r.key == ("3",))
        assert r.manual and r.key_b == ("9",)
        # キー列(3≠9)だけが相違、名前・部署は一致
        assert r.status == "changed"
        assert [cd.col_a for cd in r.cell_diffs] == ["id"]

    def test_original_diff_untouched(self):
        d = make_diff()
        apply_manual_pairs(d, [{"key_a": ["3"], "key_b": ["9"]}])
        assert d.summary["only_a"] == 1 and d.summary["only_b"] == 1

    def test_missing_rows_ignored(self):
        d = make_diff()
        out = apply_manual_pairs(d, [{"key_a": ["999"], "key_b": ["9"]},
                                     {"key_a": ["3"], "key_b": ["888"]}])
        assert out.summary["only_a"] == 1 and out.summary["only_b"] == 1

    def test_consumed_keys_not_reused(self):
        d = make_diff()
        out = apply_manual_pairs(d, [{"key_a": ["3"], "key_b": ["9"]},
                                     {"key_a": ["3"], "key_b": ["9"]}])
        assert sum(1 for r in out.rows if r.manual) == 1

    def test_row_order_preserved(self):
        d = make_diff()
        out = apply_manual_pairs(d, [{"key_a": ["3"], "key_b": ["9"]}])
        assert [r.key for r in out.rows] == [("1",), ("2",), ("3",)]

    def test_known_diff_applies_to_manual_pair(self):
        d = make_diff()
        out = apply_manual_pairs(d, [{"key_a": ["3"], "key_b": ["9"]}])
        out = apply_known_diffs(out, [
            {"type": "cell", "key": ["3"], "col_a": "id", "value_a": "3", "value_b": "9"},
        ])
        r = next(r for r in out.rows if r.key == ("3",))
        assert r.status == "same" and r.known and r.manual

    def test_verification_counts(self):
        d = make_diff()
        out = apply_manual_pairs(d, [{"key_a": ["3"], "key_b": ["9"]}])
        v = build_verification(out)
        assert v.only_a == 0 and v.only_b == 0
        assert v.matched == 3 and v.changed == 3

    def test_manual_pair_in_upsert(self):
        d = make_diff()
        out = apply_manual_pairs(d, [{"key_a": ["3"], "key_b": ["9"]}])
        t = build_upsert_table(out, external_id_col_a="id")
        keys = [r[0] for r in t.rows]
        assert keys == ["1", "2", "3"]  # 3はinsertではなくupdate候補になる


class TestListUnmatched:
    def test_sides(self):
        d = make_diff()
        ua = list_unmatched(d, "a")
        ub = list_unmatched(d, "b")
        assert [x["key"] for x in ua] == [["3"]]
        assert [x["key"] for x in ub] == [["9"]]
        assert "新規" in ua[0]["label"]

    def test_known_rows_excluded(self):
        d = make_diff()
        out = apply_known_diffs(d, [{"type": "row", "key": ["3"], "status": "only_a"}])
        assert list_unmatched(out, "a") == []

    def test_bad_side(self):
        with pytest.raises(DiffDeskError):
            list_unmatched(make_diff(), "x")


class TestValidate:
    def test_ok(self):
        p = validate_manual_pair({"key_a": ["1"], "key_b": ["2"], "extra": True})
        assert p == {"key_a": ["1"], "key_b": ["2"]}

    def test_bad(self):
        with pytest.raises(DiffDeskError):
            validate_manual_pair({"key_a": [], "key_b": ["2"]})
        with pytest.raises(DiffDeskError):
            validate_manual_pair({"key_a": ["1"], "key_b": [2]})
