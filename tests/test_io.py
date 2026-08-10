import pytest

from diffdesk.core import (
    DiffDeskError,
    EncodingWriteError,
    Table,
    detect_delimiter,
    detect_encoding,
    list_sheets,
    load_csv,
    load_excel,
    load_table,
    write_csv,
    write_xlsx,
)
from tests.conftest import load_fixture


class TestDetectEncoding:
    def test_utf8_bom(self):
        enc, conf = detect_encoding(b"\xef\xbb\xbfa,b\r\n")
        assert enc == "utf-8-sig" and conf == 1.0

    def test_utf8_japanese(self):
        enc, _ = detect_encoding("氏名,メール\r\n".encode("utf-8"))
        assert enc == "utf-8"

    def test_cp932(self):
        enc, _ = detect_encoding("氏名,メール\r\n山田①,x\r\n".encode("cp932"))
        assert enc == "cp932"

    def test_cp932_extension_chars(self):
        enc, _ = detect_encoding("㈱テスト,①②③\r\n".encode("cp932"))
        assert enc == "cp932"

    def test_ascii_is_utf8(self):
        enc, _ = detect_encoding(b"a,b,c\r\n1,2,3\r\n")
        assert enc == "utf-8"


class TestDetectDelimiter:
    def test_comma(self):
        assert detect_delimiter("a,b,c\n1,2,3\n") == ","

    def test_tab(self):
        assert detect_delimiter("a\tb\tc\n1\t2\t3\n") == "\t"

    def test_semicolon(self):
        assert detect_delimiter("a;b;c\n1;2;3\n") == ";"

    def test_quoted_commas_in_tab_file(self):
        assert detect_delimiter('a\tb\n"x,y"\tz\n') == "\t"

    def test_empty_defaults_comma(self):
        assert detect_delimiter("") == ","


class TestLoadCsv:
    def test_leading_zeros_preserved(self, master_utf8):
        t = load_csv(master_utf8)
        col = t.col_index("社員番号")
        assert t.rows[0][col] == "0001"

    def test_cp932_roundtrip(self, master_cp932):
        t = load_csv(master_cp932)
        assert t.source_encoding == "cp932"
        assert t.columns[0] == "氏名"
        assert t.rows[4][0] == "田中④子"

    def test_bom_stripped(self):
        t = load_csv(load_fixture("master_utf8_bom.csv"))
        assert t.columns[0] == "氏名"  # BOMがヘッダーに混入しない

    def test_tsv(self):
        t = load_csv(load_fixture("master_tab.tsv"))
        assert t.columns == ["氏名", "メール", "部署", "社員番号", "入社日"]
        assert len(t.rows) == 5

    def test_encoding_override(self, master_cp932):
        with pytest.raises(DiffDeskError):
            load_csv(master_cp932, encoding="utf-8")

    def test_duplicate_and_empty_headers(self):
        raw = "名前,,名前\r\na,b,c\r\n".encode("utf-8")
        t = load_csv(raw)
        assert t.columns == ["名前", "列2", "名前_2"]

    def test_ragged_rows_padded(self):
        raw = "a,b,c\r\n1,2\r\n1,2,3,4\r\n".encode("utf-8")
        t = load_csv(raw)
        assert t.columns == ["a", "b", "c", "列4"]
        assert t.rows[0] == ["1", "2", "", ""]
        assert t.rows[1] == ["1", "2", "3", "4"]

    def test_header_row_offset(self):
        raw = "タイトル行\r\na,b\r\n1,2\r\n".encode("utf-8")
        t = load_csv(raw, header_row=1)
        assert t.columns == ["a", "b"]
        assert t.rows == [["1", "2"]]


class TestExcel:
    def test_load_first_sheet(self):
        t = load_excel(load_fixture("master.xlsx"))
        assert t.sheet == "社員マスタ"
        assert t.columns[0] == "氏名"
        assert t.rows[0][t.col_index("社員番号")] == "0001"

    def test_sheet_selection_and_header_row(self):
        t = load_excel(load_fixture("master.xlsx"), sheet="タイトル付き", header_row=1)
        assert t.columns[0] == "氏名"
        assert len(t.rows) == 5

    def test_list_sheets(self):
        assert list_sheets(load_fixture("master.xlsx")) == ["社員マスタ", "タイトル付き"]

    def test_unknown_sheet(self):
        with pytest.raises(DiffDeskError):
            load_excel(load_fixture("master.xlsx"), sheet="なし")

    def test_load_table_dispatch(self, master_utf8):
        t1 = load_table(load_fixture("master.xlsx"), "master.xlsx")
        t2 = load_table(master_utf8, "master.csv")
        assert t1.columns == t2.columns


class TestWriteCsv:
    def test_utf8_sig_bom_and_crlf(self):
        t = Table(columns=["a", "b"], rows=[["1", "あ"]])
        raw = write_csv(t, encoding="utf-8-sig")
        assert raw.startswith(b"\xef\xbb\xbf")
        assert b"\r\n" in raw

    def test_cp932(self):
        t = Table(columns=["氏名"], rows=[["山田①"]])
        raw = write_csv(t, encoding="cp932")
        assert raw.decode("cp932") == "氏名\r\n山田①\r\n"

    def test_cp932_unencodable_reports_location(self):
        t = Table(columns=["名前"], rows=[["OK"], ["𩸽です"]])  # 𩸽はCP932外
        with pytest.raises(EncodingWriteError) as ei:
            write_csv(t, encoding="cp932")
        locs = ei.value.details["locations"]
        assert locs[0]["row"] == 2 and locs[0]["column"] == "名前"

    def test_cp932_replace_mode(self):
        t = Table(columns=["名前"], rows=[["𩸽です"]])
        raw = write_csv(t, encoding="cp932", errors="replace")
        assert "です" in raw.decode("cp932")

    def test_roundtrip(self, master_utf8):
        t = load_csv(master_utf8)
        raw = write_csv(t, encoding="cp932")
        t2 = load_csv(raw)
        assert t2.columns == t.columns
        assert t2.rows == t.rows


def test_write_xlsx_roundtrip():
    t = Table(columns=["氏名", "番号"], rows=[["山田", "0001"]])
    raw = write_xlsx(t)
    t2 = load_excel(raw)
    assert t2.columns == ["氏名", "番号"]
    assert t2.rows == [["山田", "0001"]]
