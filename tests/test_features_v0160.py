"""v0.16.0 案件切替・統一アンドゥのテスト。"""
import pytest

from diffdesk.core import (
    DiffDeskError,
    add_known_diff,
    add_manual_link,
    add_user_pairs,
    load_known_diffs,
    load_manual_links,
    load_user_dict,
    remove_known_diff,
)
from diffdesk.core import project as project_mod
from diffdesk.core.workspace import peek_undo, undo_last


class TestProjects:
    def test_default_project(self, tmp_path):
        cfg = project_mod.list_projects(root=tmp_path)
        assert cfg["current"] == "既定"
        assert cfg["names"] == ["既定"]
        # 既定案件のデータフォルダはルート直下(過去データ互換)
        assert project_mod.data_dir(root=tmp_path) == tmp_path

    def test_create_and_switch(self, tmp_path):
        cfg = project_mod.create_project("試験A 移行検証", root=tmp_path)
        assert cfg["current"] == "試験A 移行検証"
        assert "試験A 移行検証" in cfg["names"]
        d = project_mod.data_dir(root=tmp_path)
        assert d != tmp_path and d.is_dir()
        assert d.parent == tmp_path / "projects"
        cfg = project_mod.switch_project("既定", root=tmp_path)
        assert cfg["current"] == "既定"
        assert project_mod.data_dir(root=tmp_path) == tmp_path

    def test_create_validation(self, tmp_path):
        with pytest.raises(DiffDeskError):
            project_mod.create_project("", root=tmp_path)
        with pytest.raises(DiffDeskError):
            project_mod.create_project("x" * 51, root=tmp_path)
        project_mod.create_project("案件1", root=tmp_path)
        with pytest.raises(DiffDeskError):
            project_mod.create_project("案件1", root=tmp_path)  # 重複

    def test_switch_unknown(self, tmp_path):
        with pytest.raises(DiffDeskError):
            project_mod.switch_project("ない案件", root=tmp_path)

    def test_delete(self, tmp_path):
        project_mod.create_project("消す案件", root=tmp_path)
        d = project_mod.data_dir("消す案件", root=tmp_path)
        (d / "known_diffs.json").write_text("[]", encoding="utf-8")
        cfg = project_mod.delete_project("消す案件", root=tmp_path)
        assert cfg["current"] == "既定"
        assert not d.exists()
        with pytest.raises(DiffDeskError):
            project_mod.delete_project("既定", root=tmp_path)

    def test_data_isolated_between_projects(self, tmp_path):
        d_default = project_mod.data_dir("既定", root=tmp_path)
        project_mod.create_project("案件X", root=tmp_path)
        d_x = project_mod.data_dir("案件X", root=tmp_path)
        add_known_diff({"type": "value", "col_a": "c", "value_a": "1",
                        "value_b": "1.0"}, directory=d_x)
        assert len(load_known_diffs(directory=d_x)) == 1
        assert load_known_diffs(directory=d_default) == []


class TestUndo:
    def test_empty_stack(self, tmp_path):
        assert peek_undo(directory=tmp_path)["count"] == 0
        with pytest.raises(DiffDeskError):
            undo_last(directory=tmp_path)

    def test_undo_known_add(self, tmp_path):
        add_known_diff({"type": "value", "col_a": "c", "value_a": "1",
                        "value_b": "1.0"}, directory=tmp_path)
        info = peek_undo(directory=tmp_path)
        assert info["count"] == 1 and "既知差分の追加" in info["label"]
        label = undo_last(directory=tmp_path)
        assert "既知差分の追加" in label
        assert load_known_diffs(directory=tmp_path) == []
        assert peek_undo(directory=tmp_path)["count"] == 0

    def test_undo_known_delete_restores(self, tmp_path):
        add_known_diff({"type": "value", "col_a": "c", "value_a": "1",
                        "value_b": "1.0"}, directory=tmp_path)
        remove_known_diff(0, directory=tmp_path)
        assert load_known_diffs(directory=tmp_path) == []
        undo_last(directory=tmp_path)  # 削除の取り消し
        assert len(load_known_diffs(directory=tmp_path)) == 1

    def test_undo_manual_and_dict(self, tmp_path):
        add_manual_link({"key_a": ["1"], "key_b": ["2"]}, directory=tmp_path)
        add_user_pairs([{"col_a": "a", "col_b": "b"}], directory=tmp_path)
        assert peek_undo(directory=tmp_path)["count"] == 2
        assert "辞書" in undo_last(directory=tmp_path)
        assert load_user_dict(directory=tmp_path) == []
        assert "手動紐づけ" in undo_last(directory=tmp_path)
        assert load_manual_links(directory=tmp_path) == []

    def test_undo_stack_order_multiple(self, tmp_path):
        for i in range(3):
            add_known_diff({"type": "value", "col_a": "c", "value_a": str(i),
                            "value_b": f"{i}.0"}, directory=tmp_path)
        undo_last(directory=tmp_path)
        assert len(load_known_diffs(directory=tmp_path)) == 2
        undo_last(directory=tmp_path)
        assert len(load_known_diffs(directory=tmp_path)) == 1

    def test_duplicate_add_not_recorded(self, tmp_path):
        entry = {"type": "value", "col_a": "c", "value_a": "1", "value_b": "1.0"}
        add_known_diff(entry, directory=tmp_path)
        add_known_diff(entry, directory=tmp_path)  # 重複は無視される
        assert peek_undo(directory=tmp_path)["count"] == 1
