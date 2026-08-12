"""v0.22.0 参照整合性・PIIガード・AI仕分けのテスト。"""
import pytest

from diffdesk.core import (
    ColumnPair,
    DiffDeskError,
    MappingConfig,
    Table,
    build_known_prompt,
    detect_pii_in_diff,
    diff_tables,
    missing_rows_table,
    parse_known_answer,
    ref_check,
)
from diffdesk.core.pii import detect_pii_columns


class TestRefCheck:
    def make(self):
        child = Table(columns=["id", "部署コード"], rows=[
            ["1", "D01"], ["2", "D02"], ["3", "D99"], ["4", ""],
            ["5", "Ｄ０１"],  # 全角 → NFKCで一致
        ])
        master = Table(columns=["code", "name"], rows=[
            ["D01", "営業"], ["D02", "総務"], ["D03", "開発"],
        ])
        return child, master

    def test_summary(self):
        child, master = self.make()
        r = ref_check(child, "部署コード", master, "code")
        assert r["total"] == 5
        assert r["matched"] == 3  # D01, D02, Ｄ０１(NFKC)
        assert r["missing"] == 1 and r["blank"] == 1
        assert r["missing_values"] == [{"value": "D99", "count": 1}]
        assert r["master_values"] == 3

    def test_missing_rows_table(self):
        child, master = self.make()
        t = missing_rows_table(child, "部署コード", master, "code")
        assert len(t.rows) == 1
        assert t.rows[0][0] == "3"
        assert "エラー理由" in t.columns
        assert "D99" in t.rows[0][-1]

    def test_all_ok(self):
        child = Table(columns=["c"], rows=[["x"]])
        master = Table(columns=["c"], rows=[["x"], ["y"]])
        assert ref_check(child, "c", master, "c")["missing"] == 0


class TestPii:
    def test_by_column_name(self):
        cols = detect_pii_columns(["社員番号", "氏名", "メール", "部署"],
                                  [["1", "山田", "a@b.jp", "営業"]])
        kinds = {c["column"]: c["kind"] for c in cols}
        assert kinds == {"氏名": "氏名", "メール": "メールアドレス"}

    def test_by_values(self):
        rows = [[f"user{i}@example.com", f"090-1234-56{i:02d}", "x"]
                for i in range(5)]
        cols = detect_pii_columns(["c1", "c2", "c3"], rows)
        kinds = {c["column"]: c["kind"] for c in cols}
        assert kinds == {"c1": "メールアドレス", "c2": "電話番号"}

    def test_in_diff(self):
        a = Table(columns=["id", "氏名"], rows=[["1", "山田"]])
        b = Table(columns=["id", "Name"], rows=[["1", "山田"]])
        m = MappingConfig(pairs=[ColumnPair("id", "id", is_key=True),
                                 ColumnPair("氏名", "Name")])
        d = diff_tables(a, b, m)
        assert detect_pii_in_diff(d) == [{"column": "氏名", "kind": "氏名"}]


class TestAiAssist:
    def make_diff(self):
        a = Table(columns=["id", "性別", "数"], rows=[
            ["1", "男", "100"], ["2", "女", "200"], ["3", "男", "300"]])
        b = Table(columns=["id", "性別", "数"], rows=[
            ["1", "Male", "100"], ["2", "Female", "200"], ["3", "Male", "999"]])
        m = MappingConfig(pairs=[ColumnPair("id", "id", is_key=True),
                                 ColumnPair("性別", "性別"), ColumnPair("数", "数")])
        return diff_tables(a, b, m)

    def test_prompt(self):
        r = build_known_prompt(self.make_diff())
        assert r["count"] == 3  # 男→Male(2件), 女→Female, 300→999
        assert "男\tMale\t2件" in r["prompt"]
        assert "known" in r["prompt"] and "real" in r["prompt"]

    def test_prompt_empty_diff(self):
        a = Table(columns=["id"], rows=[["1"]])
        b = Table(columns=["id"], rows=[["1"]])
        m = MappingConfig(pairs=[ColumnPair("id", "id", is_key=True)])
        with pytest.raises(DiffDeskError):
            build_known_prompt(diff_tables(a, b, m))

    def test_parse_answer(self):
        d = self.make_diff()
        text = '''判定しました。
[{"no": 1, "verdict": "known", "reason": "コード変換"},
 {"no": 2, "verdict": "known", "reason": "コード変換"},
 {"no": 3, "verdict": "real", "reason": "数値が異なる"}]'''
        r = parse_known_answer(d, text)
        assert len(r["candidates"]) == 2
        assert r["real"] == 1 and r["rejected"] == []
        assert r["candidates"][0]["col"] == "性別"
        assert r["candidates"][0]["reason"] == "コード変換"

    def test_parse_rejects_bad_items(self):
        d = self.make_diff()
        text = '[{"no": 99, "verdict": "known"}, {"no": 1, "verdict": "maybe"}, "x"]'
        r = parse_known_answer(d, text)
        assert r["candidates"] == [] and len(r["rejected"]) == 3

    def test_parse_no_json(self):
        with pytest.raises(DiffDeskError):
            parse_known_answer(self.make_diff(), "JSONなしの回答")
