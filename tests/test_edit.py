import pytest

from csvtool.core import (
    CsvToolError,
    Table,
    dedupe_rows,
    delete_column,
    delete_rows,
    insert_column,
    insert_row,
    rename_column,
    replace_all,
    search_cells,
    set_cell,
)


def make_table() -> Table:
    return Table(columns=["a", "b"], rows=[["1", "x"], ["2", "y"]])


def test_set_cell():
    t = set_cell(make_table(), 0, 1, "z")
    assert t.rows[0][1] == "z"
    with pytest.raises(CsvToolError):
        set_cell(t, 9, 0, "v")


def test_insert_delete_row():
    t = insert_row(make_table(), 1)
    assert t.rows[1] == ["", ""]
    t = delete_rows(t, [0, 1])
    assert t.rows == [["2", "y"]]


def test_insert_delete_rename_column():
    t = insert_column(make_table(), "c", 1)
    assert t.columns == ["a", "c", "b"]
    assert t.rows[0] == ["1", "", "x"]
    t = rename_column(t, "c", "d")
    assert t.columns[1] == "d"
    with pytest.raises(CsvToolError):
        rename_column(t, "d", "a")  # 重複
    t = delete_column(t, "d")
    assert t.columns == ["a", "b"]
    assert t.rows[0] == ["1", "x"]


def test_search_cells():
    t = Table(columns=["v", "w"], rows=[["abc", "ABC"], ["def", "abc"]])
    assert len(search_cells(t, "abc")) == 2
    assert len(search_cells(t, "abc", case_sensitive=False)) == 3
    assert len(search_cells(t, "abc", columns=["w"])) == 1
    assert len(search_cells(t, "^a.c$", regex=True)) == 2


def test_replace_all():
    t = Table(columns=["v"], rows=[["営業部"], ["営業第二部"]])
    t, n = replace_all(t, "営業部", "セールス部")
    assert n == 1 and t.rows[0][0] == "セールス部"
    t2 = Table(columns=["v"], rows=[["tel: 03-1234"], ["tel: 06-5678"]])
    t2, n2 = replace_all(t2, r"tel: 0(\d)", r"TEL:0\1", regex=True)
    assert n2 == 2 and t2.rows[0][0] == "TEL:03-1234"


def test_replace_bad_regex():
    with pytest.raises(CsvToolError):
        replace_all(Table(columns=["v"], rows=[["a"]]), "(", "x", regex=True)


def test_dedupe_rows():
    t = Table(columns=["a", "b"], rows=[["1", "x"], ["1", "x"], ["1", "y"]])
    t, removed = dedupe_rows(t)
    assert removed == 1
    assert t.rows == [["1", "x"], ["1", "y"]]
