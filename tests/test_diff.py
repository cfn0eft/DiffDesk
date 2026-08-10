import pytest

from diffdesk.core import (
    ColumnPair,
    DiffDeskError,
    DiffOptions,
    FilterCondition,
    MappingConfig,
    RowFilter,
    Table,
    apply_filter,
    diff_tables,
    load_csv,
)


def mapping_master_sf() -> MappingConfig:
    return MappingConfig(pairs=[
        ColumnPair("社員番号", "EmployeeNumber__c", is_key=True),
        ColumnPair("氏名", "Name"),
        ColumnPair("メール", "Email"),
        ColumnPair("部署", "Department__c"),
    ])


def test_fixture_diff(master_utf8, sf_export):
    a, b = load_csv(master_utf8), load_csv(sf_export)
    result = diff_tables(a, b, mapping_master_sf())
    s = result.summary
    assert s == {
        "only_a": 2,   # 0004, 0005
        "only_b": 1,   # 0006
        "changed": 2,  # 0002(メール), 0003(部署)
        "same": 1,     # 0001
        "duplicates_a": 0, "duplicates_b": 0,
        "empty_key_a": 0, "empty_key_b": 0,
    }
    changed = [r for r in result.rows if r.status == "changed"]
    mail = next(r for r in changed if r.key == ("0002",))
    assert len(mail.cell_diffs) == 1
    assert mail.cell_diffs[0].value_a == "hanako@example.com"
    assert mail.cell_diffs[0].value_b == "hanako-new@example.com"


def test_row_order_a_first(master_utf8, sf_export):
    a, b = load_csv(master_utf8), load_csv(sf_export)
    result = diff_tables(a, b, mapping_master_sf())
    keys = [r.key[0] for r in result.rows]
    assert keys == ["0001", "0002", "0003", "0004", "0005", "0006"]


def test_composite_key():
    a = Table(columns=["姓", "名", "値"], rows=[["山田", "太郎", "1"], ["山田", "次郎", "2"]])
    b = Table(columns=["last", "first", "val"], rows=[["山田", "太郎", "1"], ["山田", "次郎", "9"]])
    m = MappingConfig(pairs=[
        ColumnPair("姓", "last", is_key=True),
        ColumnPair("名", "first", is_key=True),
        ColumnPair("値", "val"),
    ])
    r = diff_tables(a, b, m)
    assert r.summary["same"] == 1 and r.summary["changed"] == 1


def test_duplicate_keys_excluded_and_reported():
    a = Table(columns=["id", "v"], rows=[["1", "a"], ["1", "b"], ["2", "c"]])
    b = Table(columns=["id", "v"], rows=[["2", "c"]])
    m = MappingConfig(pairs=[ColumnPair("id", "id", is_key=True), ColumnPair("v", "v")])
    r = diff_tables(a, b, m)
    assert r.duplicates_a == [("1",)]
    assert r.summary["same"] == 1
    assert r.summary["only_a"] == 0  # 重複キーはonly_aに数えない


def test_empty_key_counted():
    a = Table(columns=["id", "v"], rows=[["", "x"], ["1", "y"]])
    b = Table(columns=["id", "v"], rows=[["1", "y"]])
    m = MappingConfig(pairs=[ColumnPair("id", "id", is_key=True), ColumnPair("v", "v")])
    r = diff_tables(a, b, m)
    assert r.empty_key_a == 1
    assert r.summary["same"] == 1


def test_normalization_in_keys_and_values():
    a = Table(columns=["id", "名前"], rows=[["００１", "ﾔﾏﾀﾞ "]])
    b = Table(columns=["id", "name"], rows=[["001", "ヤマダ"]])
    m = MappingConfig(pairs=[ColumnPair("id", "id", is_key=True), ColumnPair("名前", "name")])
    r = diff_tables(a, b, m, DiffOptions())  # NFKC+trim有効
    assert r.summary["same"] == 1
    # 正規化を切ると一致しない
    r2 = diff_tables(a, b, m, DiffOptions(trim=False, normalize_width=False))
    assert r2.summary["same"] == 0


def test_numeric_tolerance_option():
    a = Table(columns=["id", "額"], rows=[["1", "100.00"]])
    b = Table(columns=["id", "amt"], rows=[["1", "100"]])
    m = MappingConfig(pairs=[ColumnPair("id", "id", is_key=True), ColumnPair("額", "amt")])
    assert diff_tables(a, b, m).summary["changed"] == 1
    assert diff_tables(a, b, m, DiffOptions(numeric_tolerance=0.0)).summary["same"] == 1


def test_mapping_validation():
    a = Table(columns=["x"], rows=[])
    b = Table(columns=["y"], rows=[])
    with pytest.raises(DiffDeskError):
        diff_tables(a, b, MappingConfig(pairs=[]))
    with pytest.raises(DiffDeskError):
        diff_tables(a, b, MappingConfig(pairs=[ColumnPair("x", "y")]))  # キーなし
    with pytest.raises(DiffDeskError):
        diff_tables(a, b, MappingConfig(pairs=[ColumnPair("nope", "y", is_key=True)]))


class TestRowFilter:
    def test_apply_filter(self, master_utf8):
        t = load_csv(master_utf8)
        out = apply_filter(t, [FilterCondition("部署", "eq", "営業部")])
        assert len(out.rows) == 2

    def test_ops(self):
        t = Table(columns=["v"], rows=[["abc"], [""], ["xbc"]])
        assert len(apply_filter(t, [FilterCondition("v", "contains", "bc")]).rows) == 2
        assert len(apply_filter(t, [FilterCondition("v", "empty")]).rows) == 1
        assert len(apply_filter(t, [FilterCondition("v", "not_empty")]).rows) == 2
        assert len(apply_filter(t, [FilterCondition("v", "starts_with", "a")]).rows) == 1
        assert len(apply_filter(t, [FilterCondition("v", "regex", "^.bc$")]).rows) == 2

    def test_bad_regex(self):
        t = Table(columns=["v"], rows=[["a"]])
        with pytest.raises(DiffDeskError):
            apply_filter(t, [FilterCondition("v", "regex", "(")])

    def test_filter_in_diff(self, master_utf8, sf_export):
        a, b = load_csv(master_utf8), load_csv(sf_export)
        rf = RowFilter(conditions_a=[FilterCondition("部署", "eq", "営業部")])
        r = diff_tables(a, b, mapping_master_sf(), row_filter=rf)
        assert r.summary["only_a"] == 0  # 0004/0005は営業部でないので消える
        assert r.summary["same"] == 1 and r.summary["changed"] == 1
