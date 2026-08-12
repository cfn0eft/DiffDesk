"""v0.12.1: 数値表記の変換(整形op)と多対多の親A正規化のテスト。"""
import pytest

from diffdesk.core import (
    DiffDeskError,
    JunctionConfig,
    Table,
    build_junction_settings,
    clean_columns,
    infer_key_template,
    parse_migration_spec,
    verify_junction,
)
from diffdesk.core.clean import CLEAN_OPS, op_num_decimal, op_num_plain


class TestNumOps:
    def test_num_decimal(self):
        assert op_num_decimal("1550") == "1550.0"
        assert op_num_decimal("-3") == "-3.0"
        assert op_num_decimal("１５５０") == "1550.0"  # 全角→半角+.0
        assert op_num_decimal(" 1550 ") == "1550.0"  # 空白除去
        assert op_num_decimal("1550.0") == "1550.0"  # 既に小数点付きはそのまま
        assert op_num_decimal("abc") == "abc"
        assert op_num_decimal("") == ""
        assert op_num_decimal("12-3") == "12-3"

    def test_num_plain(self):
        assert op_num_plain("1550.0") == "1550"
        assert op_num_plain("250.50") == "250.5"
        assert op_num_plain("0001") == "0001"  # 先頭ゼロIDは不変
        assert op_num_plain("1550") == "1550"
        assert op_num_plain("abc.0") == "abc.0"

    def test_ops_registered(self):
        assert "num_decimal" in CLEAN_OPS and "num_plain" in CLEAN_OPS

    def test_clean_columns(self):
        t = Table(columns=["社員番号", "値"],
                  rows=[["1550", "x"], ["0001", "y"], ["abc", "z"]])
        out, changed = clean_columns(t, ["社員番号"], ["num_decimal"])
        assert [r[0] for r in out.rows] == ["1550.0", "0001.0", "abc"]
        assert changed == 2


class TestJunctionANormalize:
    def make(self):
        # 移行元は 1550 だが、移行先の複合キーは 1550.0 で作られている
        src = Table(columns=["社員番号", "検体"],
                    rows=[["1550", "AB123-45"], ["1551", "AB123-46"]])
        j = Table(columns=["Key__c"],
                  rows=[["REL-1550.0-AB123-45"], ["REL-1551.0-AB123-46"]])
        return src, j

    def test_a_regex_makes_keys_match(self):
        src, j = self.make()
        cfg = JunctionConfig.from_dict({
            "a_source_col": "社員番号", "b_source_col": "検体",
            "j_key_col": "Key__c", "key_template": "REL-{A}-{B}",
            "a_regex_pattern": r"^(\d+)$", "a_regex_replacement": r"\1.0",
        })
        r = verify_junction(src, None, None, j, cfg)
        assert r["junction"]["passed"] and r["passed"]

    def test_without_a_regex_fails(self):
        src, j = self.make()
        cfg = JunctionConfig.from_dict({
            "a_source_col": "社員番号", "b_source_col": "検体",
            "j_key_col": "Key__c", "key_template": "REL-{A}-{B}",
        })
        r = verify_junction(src, None, None, j, cfg)
        assert not r["junction"]["passed"]

    def test_infer_with_a_regex(self):
        src, j = self.make()
        r = infer_key_template(src, j, a_source_col="社員番号",
                               b_source_col="検体", j_key_col="Key__c",
                               a_regex_pattern=r"^(\d+)$",
                               a_regex_replacement=r"\1.0")
        assert r["template"] == "REL-{A}-{B}"
        assert r["coverage"] == 1.0

    def test_bad_a_regex(self):
        with pytest.raises(DiffDeskError):
            JunctionConfig.from_dict({
                "a_source_col": "x", "b_source_col": "y", "j_key_col": "k",
                "a_regex_pattern": "(",
            })


class TestSpecImportARegex:
    def test_a_normalize_rules_imported(self):
        jx = {
            "object": "J__c", "externalIdField": "K__c",
            "fields": [
                {"salesforceField": "K__c", "source": "composite",
                 "prefix": "REL-", "sourceColumns": ["社員番号", "検体"]},
                {"excelColumn": "社員番号", "salesforceField": "PA__r.ExtA__c",
                 "normalizeRules": [{"pattern": r"^(\d+)$", "replacement": r"\1.0"}],
                 "verifyExternalId": {"object": "PA__c", "field": "ExtA__c"}},
                {"excelColumn": "検体", "salesforceField": "PB__r.ExtB__c",
                 "verifyExternalId": {"object": "PB__c", "field": "ExtB__c"}},
            ],
        }
        r = build_junction_settings([parse_migration_spec(jx)])
        s = r["settings"]
        assert s["a_regex_pattern"] == r"^(\d+)$"
        assert s["a_regex_replacement"] == r"\1.0"


class TestValueRuleKnown:
    """v0.12.2: 値ルール型の既知差分(同じ差異の一括登録)。"""

    def make_diff(self):
        from diffdesk.core import ColumnPair, MappingConfig, diff_tables
        a = Table(columns=["id", "部署"],
                  rows=[["1", "営業"], ["2", "営業"], ["3", "営業"], ["4", "開発"]])
        b = Table(columns=["id", "部署"],
                  rows=[["1", "営業部"], ["2", "営業部"], ["3", "総務部"], ["4", "開発部"]])
        m = MappingConfig(pairs=[ColumnPair("id", "id", is_key=True),
                                 ColumnPair("部署", "部署")])
        return diff_tables(a, b, m)

    def test_value_rule_applies_to_all_rows(self):
        from diffdesk.core import apply_known_diffs, build_verification
        d = self.make_diff()
        assert d.summary["changed"] == 4
        out = apply_known_diffs(d, [
            {"type": "value", "col_a": "部署", "value_a": "営業", "value_b": "営業部"}])
        # 営業→営業部 の2行(id 1,2)だけが既知になり、営業→総務部/開発→開発部は残る
        assert out.summary["same"] == 2 and out.summary["changed"] == 2
        v = build_verification(out)
        assert v.known_cells == 2

    def test_value_rule_store_validation(self, tmp_path):
        from diffdesk.core import add_known_diff, load_known_diffs
        e = {"type": "value", "col_a": "部署", "value_a": "営業", "value_b": "営業部"}
        entries = add_known_diff(e, directory=tmp_path)
        assert len(entries) == 1 and "key" not in entries[0]
        entries = add_known_diff(e, directory=tmp_path)  # 重複無視
        assert len(entries) == 1
        with pytest.raises(DiffDeskError):
            add_known_diff({"type": "value", "col_a": "部署"}, directory=tmp_path)

    def test_cell_and_value_coexist(self):
        from diffdesk.core import apply_known_diffs
        d = self.make_diff()
        out = apply_known_diffs(d, [
            {"type": "value", "col_a": "部署", "value_a": "営業", "value_b": "営業部"},
            {"type": "cell", "key": ["4"], "col_a": "部署",
             "value_a": "開発", "value_b": "開発部"}])
        assert out.summary["same"] == 3 and out.summary["changed"] == 1
