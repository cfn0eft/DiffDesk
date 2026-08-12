"""v0.18.0 監査ログ・検証パックのテスト。"""
import io
import zipfile

from diffdesk.core import (
    ColumnPair,
    MappingConfig,
    Table,
    add_known_diff,
    add_manual_link,
    build_verification_pack,
    diff_tables,
)
from diffdesk.core.audit import audit, audit_table, clear_audit, load_audit


class TestAudit:
    def test_append_and_load_newest_first(self, tmp_path):
        assert load_audit(directory=tmp_path) == []
        audit("照合実行", "a vs b", directory=tmp_path)
        audit("既知差分登録", "col=x", directory=tmp_path)
        records = load_audit(directory=tmp_path)
        assert len(records) == 2
        assert records[0]["action"] == "既知差分登録"  # 新しい順
        assert records[1]["detail"] == "a vs b"

    def test_limit(self, tmp_path):
        for i in range(10):
            audit("op", str(i), directory=tmp_path)
        assert len(load_audit(limit=3, directory=tmp_path)) == 3
        assert load_audit(limit=3, directory=tmp_path)[0]["detail"] == "9"

    def test_detail_truncated(self, tmp_path):
        audit("op", "x" * 1000, directory=tmp_path)
        assert len(load_audit(directory=tmp_path)[0]["detail"]) == 500

    def test_table_and_clear(self, tmp_path):
        audit("op", "d", directory=tmp_path)
        t = audit_table(directory=tmp_path)
        assert t.columns == ["日時", "操作", "内容"]
        assert t.rows[0][1] == "op"
        clear_audit(directory=tmp_path)
        assert load_audit(directory=tmp_path) == []

    def test_corrupt_line_skipped(self, tmp_path):
        audit("op", "ok", directory=tmp_path)
        with (tmp_path / "audit.jsonl").open("a", encoding="utf-8") as f:
            f.write("not-json\n")
        audit("op2", "ok2", directory=tmp_path)
        assert len(load_audit(directory=tmp_path)) == 2


class TestVerificationPack:
    def make_diff(self):
        a = Table(columns=["id", "v"], rows=[["1", "x"], ["2", "y"]], name="master.csv")
        b = Table(columns=["id", "v"], rows=[["1", "x"], ["2", "z"]], name="sf.csv")
        m = MappingConfig(pairs=[ColumnPair("id", "id", is_key=True),
                                 ColumnPair("v", "v")])
        return diff_tables(a, b, m)

    def test_pack_contents(self, tmp_path):
        add_known_diff({"type": "value", "col_a": "v", "value_a": "y",
                        "value_b": "z"}, directory=tmp_path)
        add_manual_link({"key_a": ["9"], "key_b": ["8"]}, directory=tmp_path)
        audit("照合実行", "master vs sf", directory=tmp_path)
        raw = build_verification_pack(
            self.make_diff(), project_name="テスト案件", version="0.18.0",
            directory=tmp_path)
        z = zipfile.ZipFile(io.BytesIO(raw))
        names = set(z.namelist())
        assert names == {
            "はじめにお読みください.txt", "照合レポート.csv", "検証レポート.xlsx",
            "共有用レポート.html", "既知差分.csv", "手動紐づけ.csv", "監査ログ.csv",
        }
        readme = z.read("はじめにお読みください.txt").decode("utf-8-sig")
        assert "テスト案件" in readme and "v0.18.0" in readme
        assert "master.csv" in readme
        known = z.read("既知差分.csv").decode("utf-8-sig")
        assert "値ルール" in known and "y" in known
        links = z.read("手動紐づけ.csv").decode("utf-8-sig")
        assert "9" in links
        auditcsv = z.read("監査ログ.csv").decode("utf-8-sig")
        assert "照合実行" in auditcsv
        html = z.read("共有用レポート.html").decode("utf-8")
        assert "DiffDesk" in html
        # xlsxはZIP(PK)形式
        assert z.read("検証レポート.xlsx")[:2] == b"PK"
