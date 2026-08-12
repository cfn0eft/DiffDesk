"""v0.23.0 3ファイル比較(多段トレース)・注釈のテスト。"""
import pytest

from diffdesk.core import DiffDeskError, Table, load_notes, set_note, trace_diff, trace_table
from diffdesk.core.workspace import peek_undo, undo_last


def make_three():
    a = Table(columns=["ID", "数", "名前"], rows=[
        ["1", "1550", "山田"],   # 数: M→Bで変化(1550→1550.0だが正規化で同一視される)
        ["2", "200", "佐藤"],    # 名前: A→Mで変化
        ["3", "300", "鈴木"],    # 数: 両段階で変化
        ["4", "400", "高橋"],    # 変化なし
        ["5", "500", "田中"],    # Mに無い
    ], name="a.csv")
    m = Table(columns=["ID", "数", "名前"], rows=[
        ["1", "1550", "山田"],
        ["2", "200", "サトウ"],
        ["3", "301", "鈴木"],
        ["4", "400", "高橋"],
    ], name="m.csv")
    b = Table(columns=["ID", "数", "名前"], rows=[
        ["1", "1550.0", "山田"],
        ["2", "200", "サトウ"],
        ["3", "302", "鈴木"],
        ["4", "400", "高橋"],
    ], name="b.csv")
    return a, m, b


class TestTrace:
    def test_stages(self):
        a, m, b = make_three()
        r = trace_diff(a, "ID", m, "ID", b, "ID")
        # 1550→1550.0は数値同一視(既定)なので変化に数えない
        assert r["by_stage"]["a_m"] == 1   # 佐藤→サトウ
        assert r["by_stage"]["m_b"] == 0
        assert r["by_stage"]["both"] == 1  # 300→301→302
        assert r["missing_m"] == 1         # キー5
        assert r["matched"] == 4
        stages = {x["key"]: x["stage"] for x in r["rows"]}
        assert stages == {"2": "a_m", "3": "both"}

    def test_revert_stage(self):
        a = Table(columns=["ID", "v"], rows=[["1", "x"]])
        m = Table(columns=["ID", "v"], rows=[["1", "y"]])
        b = Table(columns=["ID", "v"], rows=[["1", "x"]])
        r = trace_diff(a, "ID", m, "ID", b, "ID")
        assert r["by_stage"]["revert"] == 1

    def test_column_name_fuzzy_match(self):
        a = Table(columns=["ID", "数"], rows=[["1", "100"]])
        m = Table(columns=["ID", "数"], rows=[["1", "100"]])
        b = Table(columns=["ID", "数"], rows=[["1", "999"]])  # 全角の列名でも対応
        b.columns = ["ID", "数"]
        r = trace_diff(a, "ID", m, "ID", b, "ID")
        assert r["by_stage"]["m_b"] == 1

    def test_no_common_columns(self):
        a = Table(columns=["ID", "x"], rows=[])
        m = Table(columns=["ID", "y"], rows=[])
        b = Table(columns=["ID", "z"], rows=[])
        with pytest.raises(DiffDeskError):
            trace_diff(a, "ID", m, "ID", b, "ID")

    def test_table_export(self):
        a, m, b = make_three()
        t = trace_table(trace_diff(a, "ID", m, "ID", b, "ID"))
        assert t.columns == ["キー", "列", "原本(A)", "中間(M)", "最終(B)", "変化した段階"]
        assert len(t.rows) == 2


class TestNotes:
    def test_set_update_delete(self, tmp_path):
        set_note(["0001"], "部門へ照会中", directory=tmp_path)
        notes = load_notes(directory=tmp_path)
        assert len(notes) == 1 and notes[0]["text"] == "部門へ照会中"
        set_note(["0001"], "確認済み", directory=tmp_path)
        notes = load_notes(directory=tmp_path)
        assert len(notes) == 1 and notes[0]["text"] == "確認済み"
        set_note(["0001"], "", directory=tmp_path)  # 空 = 削除
        assert load_notes(directory=tmp_path) == []

    def test_undo(self, tmp_path):
        set_note(["1"], "メモA", directory=tmp_path)
        set_note(["1"], "メモB", directory=tmp_path)
        assert "注釈の変更" in peek_undo(directory=tmp_path)["label"]
        undo_last(directory=tmp_path)
        assert load_notes(directory=tmp_path)[0]["text"] == "メモA"
        undo_last(directory=tmp_path)
        assert load_notes(directory=tmp_path) == []

    def test_validation(self, tmp_path):
        with pytest.raises(DiffDeskError):
            set_note([], "x", directory=tmp_path)
        # 同一内容の再設定はアンドゥを積まない
        set_note(["1"], "同じ", directory=tmp_path)
        set_note(["1"], "同じ", directory=tmp_path)
        assert peek_undo(directory=tmp_path)["count"] == 1
