"""v0.10.0: 多対多(親A-中間-親B)移行検証のテスト。"""
import pytest

from diffdesk.core import DiffDeskError, JunctionConfig, Table, build_orphan_table, verify_junction


def make_config(**over):
    base = dict(
        a_source_col="会社コード", b_source_col="製品名",
        a_ext_col="CompanyCode__c", b_ext_col="ProductKey__c",
        j_key_col="RelKey__c", key_template="REL-{A}-{B}",
        required_col="数量",
    )
    base.update(over)
    return JunctionConfig.from_dict(base)


def make_source():
    # 会社×製品の多対多(重複行・空白行を含む)
    return Table(columns=["会社コード", "製品名", "数量"], rows=[
        ["C001", "製品 X", "10"],
        ["C001", "製品 X", "20"],     # 同じ組合せ(重複) → 中間は1件
        ["C001", "製品Y", "5"],
        ["C002", "製品 X", "3"],
        ["C002", "製品Z", ""],        # 必須列が空白 → 中間はスキップ(親は登録)
        ["C003", "", "9"],            # 製品名が空白 → 中間対象外
    ])


def extracts(*, drop_a=(), drop_b=(), drop_j=(), extra_j=()):
    a_keys = [k for k in ["C001", "C002", "C003"] if k not in drop_a]
    b_keys = [k for k in ["製品X", "製品Y", "製品Z"] if k not in drop_b]
    j_keys = [k for k in ["REL-C001-製品X", "REL-C001-製品Y", "REL-C002-製品X"]
              if k not in drop_j] + list(extra_j)
    return (
        Table(columns=["CompanyCode__c"], rows=[[k] for k in a_keys]),
        Table(columns=["ProductKey__c"], rows=[[k] for k in b_keys]),
        Table(columns=["RelKey__c"], rows=[[k] for k in j_keys]),
    )


class TestMacro:
    def test_all_match(self):
        # 正規化: 「製品 X」の空白を除去するルール
        cfg = make_config(b_regex_pattern=r"\s+", b_regex_replacement="")
        a, b, j = extracts()
        r = verify_junction(make_source(), a, b, j, cfg)
        assert r["parent_a"]["expected"] == 3 and r["parent_a"]["passed"]
        assert r["parent_b"]["expected"] == 3 and r["parent_b"]["passed"]
        # 中間: 重複1・必須空白1・製品名空白1を除いた3件
        assert r["junction"]["expected"] == 3 and r["junction"]["passed"]
        assert r["junction"]["skipped_required"] == 1
        assert r["junction"]["skipped_empty_pair"] == 1
        assert r["passed"]

    def test_missing_parent_reported(self):
        cfg = make_config(b_regex_pattern=r"\s+", b_regex_replacement="")
        a, b, j = extracts(drop_a=("C003",))
        r = verify_junction(make_source(), a, b, j, cfg)
        assert not r["parent_a"]["passed"]
        assert r["parent_a"]["missing"] == ["C003"]
        assert r["parent_a"]["diff"] == -1

    def test_extra_and_duplicate_actual(self):
        cfg = make_config(b_regex_pattern=r"\s+", b_regex_replacement="")
        a, b, j = extracts(extra_j=("REL-C009-製品X", "REL-C001-製品X"))
        r = verify_junction(make_source(), a, b, j, cfg)
        assert r["junction"]["extra"] == ["REL-C009-製品X"]
        assert r["junction"]["dup_actual"] == 1
        assert not r["junction"]["passed"]


class TestOrphanAnalysis:
    def test_cause_breakdown(self):
        cfg = make_config(b_regex_pattern=r"\s+", b_regex_replacement="")
        # 中間3件とも未取込。C001が親Aに無い、製品Yが親Bに無い
        a, b, j = extracts(drop_a=("C001",), drop_b=("製品Y",),
                           drop_j=("REL-C001-製品X", "REL-C001-製品Y", "REL-C002-製品X"))
        r = verify_junction(make_source(), a, b, j, cfg)
        causes = r["orphans"]["causes"]
        # REL-C001-製品X → 親A欠落 / REL-C001-製品Y → 両方欠落 / REL-C002-製品X → 親OK
        assert causes == {"missing_a": 1, "missing_b": 0,
                          "missing_both": 1, "parents_ok": 1, "unknown": 0}
        assert r["orphans"]["total"] == 3
        assert r["orphans"]["bottleneck"] in ("missing_a", "missing_both", "parents_ok")
        kinds = {s["cause"] for s in r["orphans"]["samples"]}
        assert kinds == {"missing_a", "missing_both", "parents_ok"}

    def test_orphan_table(self):
        cfg = make_config(b_regex_pattern=r"\s+", b_regex_replacement="")
        a, b, j = extracts(drop_j=("REL-C002-製品X",))
        r = verify_junction(make_source(), a, b, j, cfg)
        t = build_orphan_table(r, cfg)
        assert t.columns[0] == "複合キー"
        assert t.rows[0][0] == "REL-C002-製品X"
        assert "中間だけ未取込" in t.rows[0][3]


class TestRefIntegrity:
    def test_ref_errors(self):
        cfg = make_config(b_regex_pattern=r"\s+", b_regex_replacement="",
                          j_ref_a_col="RefA", j_ref_b_col="RefB")
        a, b, _ = extracts()
        j = Table(columns=["RelKey__c", "RefA", "RefB"], rows=[
            ["REL-C001-製品X", "C001", "製品X"],
            ["REL-C001-製品Y", "C001", "製品Y"],
            ["REL-C002-製品X", "C999", "製品X"],  # 親A参照が不正
        ])
        r = verify_junction(make_source(), a, b, j, cfg)
        assert r["ref_errors"] == {"bad_ref_a": 1, "bad_ref_b": 0}


class TestConfigValidation:
    def test_missing_required_field(self):
        with pytest.raises(DiffDeskError):
            JunctionConfig.from_dict({"a_source_col": "x"})

    def test_bad_template(self):
        with pytest.raises(DiffDeskError):
            make_config(key_template="REL-{A}")

    def test_bad_regex(self):
        with pytest.raises(DiffDeskError):
            make_config(b_regex_pattern="([")

    def test_missing_column_in_table(self):
        cfg = make_config(a_source_col="存在しない列")
        a, b, j = extracts()
        with pytest.raises(DiffDeskError):
            verify_junction(make_source(), a, b, j, cfg)
