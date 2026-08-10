import pytest

from csvtool.core import (
    ColumnPair,
    CsvToolError,
    MappingConfig,
    build_delete_table,
    build_report_table,
    build_sdl,
    build_upsert_table,
    build_xlsx_report,
    diff_tables,
    load_csv,
    load_excel,
)


def mapping_with_sf() -> MappingConfig:
    return MappingConfig(pairs=[
        ColumnPair("社員番号", "EmployeeNumber__c", is_key=True),
        ColumnPair("氏名", "Name"),
        ColumnPair("メール", "Email"),
        ColumnPair("部署", "Department__c", sf_field="Busho__c"),
    ])


@pytest.fixture
def diff(master_utf8, sf_export):
    return diff_tables(load_csv(master_utf8), load_csv(sf_export), mapping_with_sf())


class TestUpsert:
    def test_headers_renamed_and_values_from_a(self, diff):
        t = build_upsert_table(diff, external_id_col_a="社員番号")
        assert t.columns == ["EmployeeNumber__c", "Name", "Email", "Busho__c"]
        # changed行(0002)はAの値
        row = next(r for r in t.rows if r[0] == "0002")
        assert row[2] == "hanako@example.com"
        # only_a(0004, 0005) + changed(0002, 0003) = 4行
        assert len(t.rows) == 4

    def test_include_filter(self, diff):
        t = build_upsert_table(diff, external_id_col_a="社員番号", include={"only_a"})
        assert len(t.rows) == 2

    def test_external_id_must_be_key(self, diff):
        with pytest.raises(CsvToolError):
            build_upsert_table(diff, external_id_col_a="氏名")

    def test_external_id_must_exist(self, diff):
        with pytest.raises(CsvToolError):
            build_upsert_table(diff, external_id_col_a="なし")


class TestDelete:
    def test_delete_table(self, master_utf8, sf_export):
        m = MappingConfig(pairs=[
            ColumnPair("社員番号", "EmployeeNumber__c", is_key=True),
            ColumnPair("氏名", "Name"),
            ColumnPair("社員番号", "Id"),  # Id列をマッピングに含める
        ])
        d = diff_tables(load_csv(master_utf8), load_csv(sf_export), m)
        t = build_delete_table(d, id_col_b="Id")
        assert t.columns == ["Id"]
        assert t.rows == [["a01000000000006"]]

    def test_missing_id_column(self, diff):
        with pytest.raises(CsvToolError):
            build_delete_table(diff, id_col_b="Id")


class TestSdl:
    def test_sdl_content(self, diff):
        sdl = build_sdl(diff)
        assert "EmployeeNumber__c=EmployeeNumber__c" in sdl
        assert "Busho__c=Busho__c" in sdl

    def test_sdl_escapes_non_ascii(self):
        m = MappingConfig(pairs=[ColumnPair("番号", "番号", is_key=True)])
        from csvtool.core import DiffResult, DiffOptions
        d = DiffResult(mapping=m, options=DiffOptions(), rows=[],
                       duplicates_a=[], duplicates_b=[])
        sdl = build_sdl(d)
        assert "\\u756a\\u53f7" in sdl


class TestReport:
    def test_report_table(self, diff):
        t = build_report_table(diff)
        assert t.columns[0] == "状態"
        assert t.columns[1] == "キー:社員番号"
        assert len(t.rows) == 6
        changed = [r for r in t.rows if r[0] == "変更"]
        assert any("メール" in r[-1] for r in changed)

    def test_xlsx_report(self, diff):
        raw = build_xlsx_report(diff)
        # xlsxとして再読可能でサマリー件数が正しい
        t = load_excel(raw, sheet="サマリー")
        counts = {r[0]: r[1] for r in t.rows}
        assert counts["変更"] == "2"
        t2 = load_excel(raw, sheet="差分詳細")
        assert t2.columns[0] == "状態"
        assert len(t2.rows) == 6
