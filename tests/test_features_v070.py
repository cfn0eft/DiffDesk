"""v0.7.0機能(既知差分・列サマリー・履歴・ユーザー辞書)のテスト。"""
import pytest

from diffdesk.core import (
    ColumnPair,
    DiffDeskError,
    MappingConfig,
    Table,
    add_known_diff,
    add_user_pairs,
    append_history,
    apply_known_diffs,
    build_upsert_table,
    build_verification,
    column_diff_summary,
    diff_tables,
    load_history,
    load_known_diffs,
    load_user_dict,
    remove_known_diff,
    remove_user_pair,
    suggest_mapping,
)


def make_diff():
    a = Table(columns=["id", "名前", "部署"],
              rows=[["1", "山田", "営業"], ["2", "鈴木", "開発"], ["3", "新規", "総務"]])
    b = Table(columns=["id", "name", "dept"],
              rows=[["1", "山田", "人事"], ["2", "すずき", "開発x"], ["9", "B側", "x"]])
    m = MappingConfig(pairs=[
        ColumnPair("id", "id", is_key=True),
        ColumnPair("名前", "name"),
        ColumnPair("部署", "dept"),
    ])
    return diff_tables(a, b, m)


class TestApplyKnown:
    def test_cell_known_partial(self):
        d = make_diff()
        entries = [{"type": "cell", "key": ["2"], "col_a": "名前",
                    "value_a": "鈴木", "value_b": "すずき"}]
        out = apply_known_diffs(d, entries)
        r2 = next(r for r in out.rows if r.key == ("2",))
        assert r2.status == "changed"          # 部署の差異が残る
        assert len(r2.cell_diffs) == 1
        assert len(r2.known_diffs) == 1

    def test_cell_known_all_becomes_same(self):
        d = make_diff()
        entries = [{"type": "cell", "key": ["1"], "col_a": "部署",
                    "value_a": "営業", "value_b": "人事"}]
        out = apply_known_diffs(d, entries)
        r1 = next(r for r in out.rows if r.key == ("1",))
        assert r1.status == "same" and r1.known
        v = build_verification(out)
        assert v.known_cells == 1

    def test_row_known_missing(self):
        d = make_diff()
        entries = [{"type": "row", "key": ["3"], "status": "only_a"},
                   {"type": "row", "key": ["9"], "status": "only_b"}]
        out = apply_known_diffs(d, entries)
        v = build_verification(out)
        assert v.only_a == 0 and v.only_b == 0
        assert v.known_rows == 2
        # 値差異が残っているのでまだNG
        assert not v.passed

    def test_all_known_passes(self):
        d = make_diff()
        entries = [
            {"type": "cell", "key": ["1"], "col_a": "部署", "value_a": "営業", "value_b": "人事"},
            {"type": "cell", "key": ["2"], "col_a": "名前", "value_a": "鈴木", "value_b": "すずき"},
            {"type": "cell", "key": ["2"], "col_a": "部署", "value_a": "開発", "value_b": "開発x"},
            {"type": "row", "key": ["3"], "status": "only_a"},
            {"type": "row", "key": ["9"], "status": "only_b"},
        ]
        out = apply_known_diffs(d, entries)
        assert build_verification(out).passed

    def test_known_excluded_from_upsert(self):
        d = make_diff()
        entries = [
            {"type": "cell", "key": ["1"], "col_a": "部署", "value_a": "営業", "value_b": "人事"},
            {"type": "row", "key": ["3"], "status": "only_a"},
        ]
        out = apply_known_diffs(d, entries)
        t = build_upsert_table(out, external_id_col_a="id")
        keys = [r[0] for r in t.rows]
        assert "1" not in keys  # 全差分既知→update対象外
        assert "3" not in keys  # 欠落容認→insert対象外
        assert keys == ["2"]

    def test_value_mismatch_not_applied(self):
        d = make_diff()
        entries = [{"type": "cell", "key": ["1"], "col_a": "部署",
                    "value_a": "営業", "value_b": "違う値"}]  # value_b不一致
        out = apply_known_diffs(d, entries)
        r1 = next(r for r in out.rows if r.key == ("1",))
        assert r1.status == "changed"  # 適用されない


class TestColumnSummary:
    def test_ranking(self):
        s = column_diff_summary(make_diff())
        assert s[0]["count"] >= s[-1]["count"]
        by = {x["column"]: x["count"] for x in s}
        assert by == {"部署": 2, "名前": 1}


class TestWorkspaceStores:
    def test_known_crud(self, tmp_path):
        e = {"type": "cell", "key": ["1"], "col_a": "c", "value_a": "a", "value_b": "b"}
        entries = add_known_diff(e, directory=tmp_path)
        assert len(entries) == 1 and entries[0]["added_at"]
        entries = add_known_diff(e, directory=tmp_path)  # 重複は無視
        assert len(entries) == 1
        assert len(load_known_diffs(directory=tmp_path)) == 1
        assert remove_known_diff(0, directory=tmp_path) == []

    def test_known_validation(self, tmp_path):
        with pytest.raises(DiffDeskError):
            add_known_diff({"type": "nope"}, directory=tmp_path)
        with pytest.raises(DiffDeskError):
            add_known_diff({"type": "row", "key": ["1"], "status": "changed"},
                           directory=tmp_path)

    def test_history(self, tmp_path):
        append_history({"name_a": "a", "match_rate": 0.5}, directory=tmp_path)
        append_history({"name_a": "b", "match_rate": 0.9}, directory=tmp_path)
        h = load_history(directory=tmp_path)
        assert h[0]["name_a"] == "b"  # 新しい順
        assert h[0]["at"]

    def test_user_dict(self, tmp_path):
        add_user_pairs([{"col_a": "検体番号", "col_b": "SampleNo__c"},
                        {"col_a": "検体番号", "col_b": "SampleNo__c"}],  # 重複
                       directory=tmp_path)
        entries = load_user_dict(directory=tmp_path)
        assert len(entries) == 1
        assert remove_user_pair(0, directory=tmp_path) == []


class TestUserDictMapping:
    def test_dict_pair_wins(self):
        a = Table(columns=["検体番号"], rows=[["S-1"], ["S-2"]])
        b = Table(columns=["SampleNo__c", "Other__c"], rows=[["S-1", "S-1"], ["S-2", "S-2"]])
        # 辞書なしでは値ベースでどちらかに付く(不定)が、辞書指定で確実に固定される
        s = suggest_mapping(a, b, user_pairs=[("検体番号", "SampleNo__c")])
        assert s[0].col_b == "SampleNo__c"
        assert s[0].method == "辞書" and s[0].confidence == 1.0
