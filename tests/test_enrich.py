import pytest

from csvtool.core import (
    ColumnPair,
    CsvToolError,
    DiffOptions,
    MappingConfig,
    Table,
    apply_merge,
    concat_tables,
    diff_tables,
    vlookup_join,
)


class TestVlookup:
    def test_basic(self):
        a = Table(columns=["社員番号", "氏名"], rows=[["0001", "山田"], ["0009", "新人"]])
        b = Table(columns=["EmployeeNumber__c", "Id"],
                  rows=[["0001", "a01xxx"], ["0002", "a01yyy"]])
        out, unmatched = vlookup_join(
            a, b, key_pairs=[("社員番号", "EmployeeNumber__c")], add_columns=["Id"])
        assert out.columns == ["社員番号", "氏名", "Id"]
        assert out.rows[0] == ["0001", "山田", "a01xxx"]
        assert out.rows[1] == ["0009", "新人", ""]
        assert unmatched == 1

    def test_name_collision_suffixed(self):
        a = Table(columns=["id", "v"], rows=[["1", "x"]])
        b = Table(columns=["id", "v"], rows=[["1", "y"]])
        out, _ = vlookup_join(a, b, key_pairs=[("id", "id")], add_columns=["v"])
        assert out.columns == ["id", "v", "v_B"]
        assert out.rows[0] == ["1", "x", "y"]

    def test_normalized_key_match(self):
        a = Table(columns=["id"], rows=[["００１"]])
        b = Table(columns=["id", "x"], rows=[["001", "hit"]])
        out, unmatched = vlookup_join(a, b, key_pairs=[("id", "id")],
                                      add_columns=["x"], options=DiffOptions())
        assert unmatched == 0 and out.rows[0][-1] == "hit"

    def test_requires_args(self):
        t = Table(columns=["id"], rows=[])
        with pytest.raises(CsvToolError):
            vlookup_join(t, t, key_pairs=[], add_columns=["id"])


class TestConcat:
    def test_union(self):
        t1 = Table(columns=["a", "b"], rows=[["1", "2"]], name="f1")
        t2 = Table(columns=["b", "c"], rows=[["3", "4"]], name="f2")
        out = concat_tables([t1, t2])
        assert out.columns == ["a", "b", "c"]
        assert out.rows == [["1", "2", ""], ["", "3", "4"]]

    def test_strict_mismatch(self):
        t1 = Table(columns=["a"], rows=[])
        t2 = Table(columns=["b"], rows=[])
        with pytest.raises(CsvToolError):
            concat_tables([t1, t2], mode="strict")

    def test_empty(self):
        with pytest.raises(CsvToolError):
            concat_tables([])


class TestMerge:
    def make_diff(self):
        a = Table(columns=["id", "名前", "部署"],
                  rows=[["1", "山田", "営業"], ["2", "鈴木", "開発"], ["3", "新規", "総務"]])
        b = Table(columns=["id", "name", "dept"],
                  rows=[["1", "山田", "人事"], ["2", "鈴木", "開発"], ["9", "B側", "x"]])
        m = MappingConfig(pairs=[
            ColumnPair("id", "id", is_key=True),
            ColumnPair("名前", "name"),
            ColumnPair("部署", "dept"),
        ])
        return diff_tables(a, b, m)

    def test_default_takes_a(self):
        out = apply_merge(self.make_diff(), choices=[])
        assert out.columns == ["id", "名前", "部署"]
        assert ["1", "山田", "営業"] in out.rows      # 変更セルはデフォルトA
        assert ["3", "新規", "総務"] in out.rows      # only_aは含む
        assert not any(r[0] == "9" for r in out.rows)  # only_bは既定で含まない

    def test_choice_b(self):
        out = apply_merge(self.make_diff(),
                          choices=[{"key": ["1"], "col_a": "部署", "use": "b"}])
        assert ["1", "山田", "人事"] in out.rows

    def test_include_only_b(self):
        out = apply_merge(self.make_diff(), choices=[], include_only_b=True)
        assert ["9", "B側", "x"] in out.rows

    def test_bad_choice(self):
        with pytest.raises(CsvToolError):
            apply_merge(self.make_diff(),
                        choices=[{"key": ["1"], "col_a": "部署", "use": "c"}])
