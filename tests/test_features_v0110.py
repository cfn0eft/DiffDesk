"""v0.11.0: 移行定義JSONの取り込みと変換再現照合のテスト。"""
import pytest

from diffdesk.core import (
    ColumnPair,
    DiffDeskError,
    MappingConfig,
    Table,
    apply_transform,
    build_junction_settings,
    build_mapping_pairs,
    diff_tables,
    parse_migration_spec,
)
from diffdesk.core.transform import canon_date

PARENT_SPEC = {
    "object": "Parent_A__c",
    "externalIdField": "ExtA__c",
    "deduplicateBy": "SrcID",
    "fields": [
        {"excelColumn": "SrcID", "salesforceField": "Name", "type": "string"},
        {"excelColumn": "SrcID", "salesforceField": "ExtA__c", "type": "string"},
        {"excelColumn": "区分", "salesforceField": "Kind__c", "type": "picklist",
         "valueMap": {"甲": "TypeA", "乙": "TypeB"}, "defaultValue": ""},
        {"excelColumn": "有効", "salesforceField": "Active__c", "type": "boolean",
         "truthyValues": ["○", "はい"], "defaultValue": "false"},
        {"excelColumn": "開始日", "salesforceField": "Start__c", "type": "date"},
        {"salesforceField": "IsActive__c", "constantValue": "true", "type": "boolean"},
    ],
}

JUNCTION_SPEC = {
    "object": "Junction__c",
    "externalIdField": "CompKey__c",
    "skipIfBlank": ["親B番号"],
    "fields": [
        {"salesforceField": "CompKey__c", "source": "composite",
         "prefix": "REL-", "sourceColumns": ["SrcID", "親B番号"]},
        {"excelColumn": "SrcID", "salesforceField": "PA__r.ExtA__c",
         "type": "string",
         "verifyExternalId": {"object": "Parent_A__c", "field": "ExtA__c"}},
        {"excelColumn": "親B番号", "salesforceField": "PB__r.ExtB__c",
         "type": "string",
         "normalizeRules": [{"pattern": r".*([A-Z]{2}[0-9]{3}).*",
                             "replacement": r"\1"}],
         "verifyExternalId": {"object": "Parent_B__c", "field": "ExtB__c"}},
    ],
}


class TestTransform:
    def test_value_map(self):
        t = {"value_map": {"甲": "TypeA"}, "default_value": ""}
        assert apply_transform("甲", t) == "TypeA"
        assert apply_transform("未知", t) == ""  # マップ外はdefault

    def test_value_map_no_default_keeps_value(self):
        t = {"value_map": {"甲": "TypeA"}}
        assert apply_transform("未知", t) == "未知"

    def test_truthy(self):
        t = {"truthy_values": ["○", "はい"], "default_value": "false"}
        assert apply_transform("○", t) == "true"
        assert apply_transform("×", t) == "false"

    def test_regex_chain(self):
        t = {"regex_rules": [{"pattern": r"\s+", "replacement": ""},
                             {"pattern": r"^X-", "replacement": ""}]}
        assert apply_transform("X- AB 123", t) == "AB123"

    def test_canon_date(self):
        assert canon_date("2021/10/15") == "2021-10-15"
        assert canon_date("2021-10-15") == "2021-10-15"
        assert canon_date("2021年1月5日") == "2021-01-05"
        assert canon_date("2021/10/15 0:00") == "2021-10-15"
        assert canon_date("メモ") == "メモ"


class TestTransformDiff:
    def test_transformed_columns_match(self):
        a = Table(columns=["SrcID", "区分", "有効", "開始日"],
                  rows=[["P1", "甲", "○", "2021/10/15"]])
        b = Table(columns=["ExtA__c", "Kind__c", "Active__c", "Start__c"],
                  rows=[["P1", "TypeA", "true", "2021-10-15"]])
        spec = parse_migration_spec(PARENT_SPEC)
        pairs = [p for p in build_mapping_pairs(spec)
                 if p["col_b"] != "Name"]  # Name行は列名重複のため除外
        m = MappingConfig(pairs=[ColumnPair.from_dict(p) for p in pairs])
        d = diff_tables(a, b, m)
        assert d.summary["same"] == 1 and d.summary["changed"] == 0

    def test_wrong_mapped_value_is_diff(self):
        a = Table(columns=["SrcID", "区分"], rows=[["P1", "甲"]])
        b = Table(columns=["ExtA__c", "Kind__c"], rows=[["P1", "TypeB"]])  # 甲→TypeAのはず
        m = MappingConfig(pairs=[
            ColumnPair("SrcID", "ExtA__c", is_key=True),
            ColumnPair("区分", "Kind__c",
                       transform={"value_map": {"甲": "TypeA"}, "default_value": ""}),
        ])
        d = diff_tables(a, b, m)
        assert d.summary["changed"] == 1


class TestParseSpec:
    def test_parse_parent(self):
        spec = parse_migration_spec(PARENT_SPEC)
        assert spec["object"] == "Parent_A__c"
        assert spec["external_id_field"] == "ExtA__c"
        assert len(spec["constants"]) == 1
        pairs = {p["col_b"]: p for p in spec["pairs"]}
        assert pairs["ExtA__c"]["is_key"]
        assert not pairs["Name"]["is_key"]
        assert pairs["Kind__c"]["transform"]["value_map"]["甲"] == "TypeA"
        assert pairs["Active__c"]["transform"]["truthy_values"] == ["○", "はい"]
        assert pairs["Start__c"]["transform"]["type"] == "date"
        # 純粋なstring列は変換なし
        assert pairs["Name"]["transform"] is None

    def test_parse_junction_composite(self):
        spec = parse_migration_spec(JUNCTION_SPEC)
        assert spec["composite"] == {
            "target_field": "CompKey__c", "prefix": "REL-",
            "source_columns": ["SrcID", "親B番号"]}
        assert spec["skip_if_blank"] == ["親B番号"]

    def test_invalid_spec(self):
        with pytest.raises(DiffDeskError):
            parse_migration_spec({"fields": "not-a-list"})
        with pytest.raises(DiffDeskError):
            parse_migration_spec({"fields": [{"excelColumn": "x"}]})  # sfなし
        with pytest.raises(DiffDeskError):
            parse_migration_spec({
                "fields": [{"salesforceField": "K__c", "source": "composite",
                            "sourceColumns": ["one"]}]})  # 2列未満

    def test_bad_regex_rejected(self):
        bad = {"fields": [{"excelColumn": "x", "salesforceField": "X__c",
                           "normalizeRules": [{"pattern": "(", "replacement": ""}]}]}
        with pytest.raises(DiffDeskError):
            parse_migration_spec(bad)


class TestJunctionSettings:
    def test_build_settings(self):
        specs = [parse_migration_spec(PARENT_SPEC),
                 parse_migration_spec(JUNCTION_SPEC)]
        r = build_junction_settings(specs)
        s = r["settings"]
        assert s["a_source_col"] == "SrcID" and s["b_source_col"] == "親B番号"
        assert s["key_template"] == "REL-{A}-{B}"
        assert s["a_ext_col"] == "ExtA__c" and s["b_ext_col"] == "ExtB__c"
        assert s["j_key_col"] == "CompKey__c"
        assert s["required_col"] == "親B番号"
        assert s["b_regex_pattern"] == r".*([A-Z]{2}[0-9]{3}).*"
        assert s["b_regex_replacement"] == r"\1"
        assert s["j_ref_a_col"] == "PA__r.ExtA__c"
        assert r["warnings"] == []

    def test_no_junction_error(self):
        with pytest.raises(DiffDeskError):
            build_junction_settings([parse_migration_spec(PARENT_SPEC)])
