"""v0.12.0: 親抽出の任意化・関係ビュー・キー形式自動推定のテスト。"""
import pytest

from diffdesk.core import (
    DiffDeskError,
    JunctionConfig,
    Table,
    infer_key_template,
    verify_junction,
)


def make_config(**over):
    base = dict(
        a_source_col="会社", b_source_col="製品",
        j_key_col="Key__c", key_template="REL-{A}-{B}",
    )
    base.update(over)
    return JunctionConfig.from_dict(base)


def make_source():
    return Table(columns=["会社", "製品"], rows=[
        ["C1", "P1"], ["C1", "P2"], ["C2", "P1"],
    ])


def jx(keys):
    return Table(columns=["Key__c"], rows=[[k] for k in keys])


class TestOptionalParents:
    def test_two_files_only(self):
        r = verify_junction(make_source(), None, None,
                            jx(["REL-C1-P1", "REL-C1-P2"]), make_config())
        assert r["parent_a"] is None and r["parent_b"] is None
        assert r["junction"]["expected"] == 3
        assert r["junction"]["missing"] == ["REL-C2-P1"]
        # 親抽出がないので原因は不明
        assert r["orphans"]["causes"]["unknown"] == 1
        assert not r["passed"]

    def test_one_parent_only(self):
        a = Table(columns=["Ext__c"], rows=[["C1"]])  # C2欠落
        cfg = make_config(a_ext_col="Ext__c")
        r = verify_junction(make_source(), a, None,
                            jx(["REL-C1-P1", "REL-C1-P2"]), cfg)
        assert r["parent_a"] is not None and r["parent_b"] is None
        # C2はA欠落と判定できる(B側は不明でもA欠落が確定)
        assert r["orphans"]["causes"]["missing_a"] == 1

    def test_parent_without_ext_col_error(self):
        a = Table(columns=["Ext__c"], rows=[["C1"]])
        with pytest.raises(DiffDeskError):
            verify_junction(make_source(), a, None, jx([]), make_config())

    def test_passed_two_files(self):
        r = verify_junction(make_source(), None, None,
                            jx(["REL-C1-P1", "REL-C1-P2", "REL-C2-P1"]),
                            make_config())
        assert r["passed"]


class TestRelations:
    def test_groups_and_statuses(self):
        r = verify_junction(make_source(), None, None,
                            jx(["REL-C1-P1", "REL-C9-P9"]), make_config())
        rel = r["relations"]
        by_a = {g["a"]: g for g in rel["groups"]}
        # C1: P1=ok, P2=missing / C2: P1=missing / C9: extra(逆変換で分解)
        assert by_a["C1"]["ok"] == 1 and by_a["C1"]["ng"] == 1
        items = {i["b"]: i for i in by_a["C1"]["items"]}
        assert items["P1"]["status"] == "ok"
        assert items["P2"]["status"] == "missing"
        assert by_a["C2"]["items"][0]["status"] == "missing"
        assert by_a["C9"]["items"][0] == {"b": "P9", "key": "REL-C9-P9",
                                          "status": "extra"}
        assert rel["total_groups"] == 3 and not rel["truncated"]
        # 問題のあるグループが先頭
        assert rel["groups"][0]["ng"] > 0

    def test_unparsed_extra(self):
        r = verify_junction(make_source(), None, None,
                            jx(["REL-C1-P1", "REL-C1-P2", "REL-C2-P1",
                                "オカシナキー"]), make_config())
        rel = r["relations"]
        assert rel["unparsed_extra"] == ["オカシナキー"]
        assert rel["unparsed_extra_count"] == 1

    def test_cause_attached_to_missing(self):
        a = Table(columns=["Ext__c"], rows=[["C1"]])
        b = Table(columns=["ExtB__c"], rows=[["P1"], ["P2"]])
        cfg = make_config(a_ext_col="Ext__c", b_ext_col="ExtB__c")
        r = verify_junction(make_source(), a, b, jx(["REL-C1-P1", "REL-C1-P2"]), cfg)
        g = next(g for g in r["relations"]["groups"] if g["a"] == "C2")
        assert g["items"][0]["cause"] == "missing_a"


class TestInferTemplate:
    def test_infer_with_prefix(self):
        src = make_source()
        j = jx(["REL-C1-P1", "REL-C1-P2", "REL-C2-P1"])
        r = infer_key_template(src, j, a_source_col="会社",
                               b_source_col="製品", j_key_col="Key__c")
        assert r["template"] == "REL-{A}-{B}"
        assert r["coverage"] == 1.0

    def test_infer_plain(self):
        src = make_source()
        j = jx(["C1_P1", "C1_P2"])
        r = infer_key_template(src, j, a_source_col="会社",
                               b_source_col="製品", j_key_col="Key__c")
        assert r["template"] == "{A}_{B}"
        assert r["coverage"] < 1.0  # C2-P1は実例に無い

    def test_no_match(self):
        src = make_source()
        j = jx(["XXX", "YYY"])
        r = infer_key_template(src, j, a_source_col="会社",
                               b_source_col="製品", j_key_col="Key__c")
        assert r["template"] is None

    def test_empty_error(self):
        with pytest.raises(DiffDeskError):
            infer_key_template(Table(columns=["会社", "製品"], rows=[]),
                               jx(["K"]), a_source_col="会社",
                               b_source_col="製品", j_key_col="Key__c")
