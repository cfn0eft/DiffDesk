"""v0.21.0 前回照合との比較・プリフライト診断のテスト。"""
from diffdesk.core import (
    ColumnPair,
    MappingConfig,
    Table,
    compare_with_prev,
    diff_tables,
    preflight,
    save_run_snapshot,
)


def make_diff(rows_b):
    a = Table(columns=["id", "v"], rows=[["1", "x"], ["2", "y"], ["3", "z"]],
              name="master.csv")
    b = Table(columns=["id", "v"], rows=rows_b, name="sf.csv")
    m = MappingConfig(pairs=[ColumnPair("id", "id", is_key=True),
                             ColumnPair("v", "v")])
    return diff_tables(a, b, m)


class TestRunSnapshot:
    def test_no_prev_unavailable(self, tmp_path):
        d = make_diff([["1", "x"], ["2", "y"], ["3", "z"]])
        assert compare_with_prev(d, directory=tmp_path) == {"available": False}

    def test_new_resolved_continuing(self, tmp_path):
        # 1回目: 行2が相違、行3が欠落(Aのみ)
        d1 = make_diff([["1", "x"], ["2", "WRONG"]])
        save_run_snapshot(d1, directory=tmp_path)
        # 2回目: 行2は解消、行3は継続、行1が新たに相違
        d2 = make_diff([["1", "BROKEN"], ["2", "y"]])
        save_run_snapshot(d2, directory=tmp_path)
        # save 2回で .prev = 1回目 → d2との比較
        r = compare_with_prev(d2, directory=tmp_path)
        assert r["available"] and r["counts"] == {
            "new": 1, "resolved": 1, "continuing": 1}
        assert r["new"][0]["key"] == "1"
        assert r["new"][0]["col"] == "v" and r["new"][0]["value_b"] == "BROKEN"
        assert r["resolved"][0]["key"] == "2"
        assert r["continuing"][0]["key"] == "3"
        assert r["continuing"][0]["status"] == "only_a"

    def test_known_rows_not_counted(self, tmp_path):
        d1 = make_diff([["1", "x"], ["2", "y"], ["3", "z"]])
        save_run_snapshot(d1, directory=tmp_path)
        d2 = make_diff([["1", "x"], ["2", "WRONG"], ["3", "z"]])
        d2.rows[1].known = True  # 既知扱い → 問題に数えない
        save_run_snapshot(d2, directory=tmp_path)
        r = compare_with_prev(d2, directory=tmp_path)
        assert r["counts"] == {"new": 0, "resolved": 0, "continuing": 0}


class TestPreflight:
    def test_ok_case(self):
        a = Table(columns=["id", "v"], rows=[["1", "x"], ["2", "y"]])
        b = Table(columns=["id", "v"], rows=[["1", "x"], ["2", "z"]])
        checks = preflight(a, b)
        msgs = " / ".join(c["message"] for c in checks)
        assert "行数: A=2行 / B=2行" in msgs
        assert "キー候補: id" in msgs
        assert all(c["level"] != "warn" for c in checks)

    def test_row_count_warning(self):
        a = Table(columns=["id"], rows=[[str(i)] for i in range(100)])
        b = Table(columns=["id"], rows=[[str(i)] for i in range(30)])
        checks = preflight(a, b)
        assert any("行数差が大きい" in c["message"] and c["level"] == "warn"
                   for c in checks)

    def test_no_key_candidate(self):
        a = Table(columns=["v"], rows=[["x"], ["x"]])
        b = Table(columns=["v"], rows=[["y"], ["y"]])
        checks = preflight(a, b)
        assert any("行番号で比較" in c["message"] for c in checks)

    def test_partial_unique_warning(self):
        a = Table(columns=["id"], rows=[["1"], ["2"]])
        b = Table(columns=["id"], rows=[["1"], ["1"]])  # B側に重複
        checks = preflight(a, b)
        assert any("B側に重複" in c["message"] for c in checks)

    def test_duplicates_and_empty_column(self):
        a = Table(columns=["id", "memo"], rows=[["1", ""], ["1", ""]])
        b = Table(columns=["id", "memo"], rows=[["1", "x"]])
        checks = preflight(a, b)
        msgs = " / ".join(c["message"] for c in checks)
        assert "完全重複行が1行" in msgs
        assert "全行が空の列" in msgs

    def test_no_common_columns_info(self):
        a = Table(columns=["社員番号"], rows=[["1"]])
        b = Table(columns=["EmployeeNumber__c"], rows=[["1"]])
        checks = preflight(a, b)
        assert any("同名の列がありません" in c["message"] for c in checks)
