"""v0.24.0 変換ルールGUI(照合適用)・案件の持ち出しのテスト。"""
import io
import zipfile

import pytest

from diffdesk.core import (
    ColumnPair,
    DiffDeskError,
    MappingConfig,
    Table,
    add_known_diff,
    add_manual_link,
    diff_tables,
    load_known_diffs,
    set_note,
)
from diffdesk.core import project as project_mod
from diffdesk.core.project import export_project, import_project
from diffdesk.core.workspace import load_notes


class TestTransformViaMapping:
    """GUIで作る変換dict(picklist/date/boolean)が照合に効くことの確認。"""

    def test_picklist_map(self):
        a = Table(columns=["id", "性別"], rows=[["1", "男"], ["2", "女"]])
        b = Table(columns=["id", "性別"], rows=[["1", "Male"], ["2", "Female"]])
        m = MappingConfig(pairs=[
            ColumnPair("id", "id", is_key=True),
            ColumnPair("性別", "性別", transform={
                "type": "picklist",
                "value_map": {"男": "Male", "女": "Female"}}),
        ])
        assert diff_tables(a, b, m).summary["same"] == 2

    def test_picklist_default(self):
        a = Table(columns=["id", "区分"], rows=[["1", "その他"]])
        b = Table(columns=["id", "区分"], rows=[["1", "Other"]])
        m = MappingConfig(pairs=[
            ColumnPair("id", "id", is_key=True),
            ColumnPair("区分", "区分", transform={
                "type": "picklist", "value_map": {"男": "Male"},
                "default_value": "Other"}),
        ])
        assert diff_tables(a, b, m).summary["same"] == 1

    def test_boolean(self):
        a = Table(columns=["id", "有効"], rows=[["1", "有"], ["2", "無"]])
        b = Table(columns=["id", "有効"], rows=[["1", "true"], ["2", "false"]])
        m = MappingConfig(pairs=[
            ColumnPair("id", "id", is_key=True),
            ColumnPair("有効", "有効", transform={
                "type": "boolean", "truthy_values": ["有"]}),
        ])
        assert diff_tables(a, b, m).summary["same"] == 2

    def test_date(self):
        a = Table(columns=["id", "日付"], rows=[["1", "2020/1/5"]])
        b = Table(columns=["id", "日付"], rows=[["1", "2020-01-05"]])
        m = MappingConfig(pairs=[
            ColumnPair("id", "id", is_key=True),
            ColumnPair("日付", "日付", transform={"type": "date"}),
        ])
        assert diff_tables(a, b, m).summary["same"] == 1


class TestProjectExportImport:
    def fill_project(self, root):
        d = project_mod.data_dir(root=root)
        add_known_diff({"type": "value", "col_a": "c", "value_a": "1",
                        "value_b": "1.0"}, directory=d)
        add_manual_link({"key_a": ["9"], "key_b": ["8"]}, directory=d)
        set_note(["0001"], "照会中", directory=d)

    def test_roundtrip(self, tmp_path):
        root_a = tmp_path / "pc_a"
        root_b = tmp_path / "pc_b"
        project_mod.create_project("試験X", root=root_a)
        self.fill_project(root_a)
        name, raw = export_project(root=root_a)
        assert name == "試験X"
        z = zipfile.ZipFile(io.BytesIO(raw))
        assert "diffdesk_project.json" in z.namelist()
        assert "known_diffs.json" in z.namelist()

        # 別PC(root_b)に取り込み
        cfg = import_project(raw, root=root_b)
        assert cfg["imported"] == "試験X"
        assert cfg["current"] == "試験X"
        d = project_mod.data_dir(root=root_b)
        assert len(load_known_diffs(directory=d)) == 1
        assert load_notes(directory=d)[0]["text"] == "照会中"

    def test_import_no_overwrite(self, tmp_path):
        project_mod.create_project("試験X", root=tmp_path)
        self.fill_project(tmp_path)
        _, raw = export_project(root=tmp_path)
        cfg = import_project(raw, root=tmp_path)  # 同じPCに再取込
        assert cfg["imported"] == "試験X(2)"
        assert "試験X" in cfg["names"] and "試験X(2)" in cfg["names"]

    def test_import_bad_zip(self, tmp_path):
        with pytest.raises(DiffDeskError):
            import_project(b"not a zip", root=tmp_path)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("random.txt", "x")
        with pytest.raises(DiffDeskError):
            import_project(buf.getvalue(), root=tmp_path)

    def test_import_ignores_traversal(self, tmp_path):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("diffdesk_project.json", '{"name": "悪意", "format": 1}')
            z.writestr("../evil.json", "[]")
            z.writestr("known_diffs.json", "[]")
        cfg = import_project(buf.getvalue(), root=tmp_path)
        assert cfg["imported"] == "悪意"
        assert not (tmp_path.parent / "evil.json").exists()
