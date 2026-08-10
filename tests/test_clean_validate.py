import pytest

from diffdesk.core import (
    DiffDeskError,
    Table,
    ValidationRules,
    clean_columns,
    validate_table,
)


class TestClean:
    def test_trim(self):
        t = Table(columns=["v"], rows=[["　山田 　"]])
        t, n = clean_columns(t, ["v"], ["trim"])
        assert t.rows[0][0] == "山田" and n == 1

    def test_zen2han(self):
        t = Table(columns=["v"], rows=[["ＡＢＣ１２３ｶﾅ"]])
        t, _ = clean_columns(t, ["v"], ["zen2han"])
        assert t.rows[0][0] == "ABC123カナ"

    def test_han2zen(self):
        t = Table(columns=["v"], rows=[["ABC123"]])
        t, _ = clean_columns(t, ["v"], ["han2zen"])
        assert t.rows[0][0] == "ＡＢＣ１２３"

    def test_kana_zenkaku_only(self):
        t = Table(columns=["v"], rows=[["ﾔﾏﾀﾞabc１２３"]])
        t, _ = clean_columns(t, ["v"], ["kana_zenkaku"])
        assert t.rows[0][0] == "ヤマダabc１２３"  # 英数は変えない

    def test_kana_zenkaku_dakuten(self):
        t = Table(columns=["v"], rows=[["ﾊﾞｯﾊﾟ"]])
        t, _ = clean_columns(t, ["v"], ["kana_zenkaku"])
        assert t.rows[0][0] == "バッパ"

    def test_date_iso(self):
        cases = {
            "2020/4/1": "2020-04-01",
            "2020-04-01": "2020-04-01",
            "2020年4月1日": "2020-04-01",
            "20200401": "2020-04-01",
            "２０２０/４/１": "2020-04-01",
            "not a date": "not a date",
            "": "",
        }
        t = Table(columns=["v"], rows=[[k] for k in cases])
        t, _ = clean_columns(t, ["v"], ["date_iso"])
        assert [r[0] for r in t.rows] == list(cases.values())

    def test_ops_chained_and_counted(self):
        t = Table(columns=["v", "w"], rows=[[" ａ ", "b"], ["c", " ｄ "]])
        t, n = clean_columns(t, ["v"], ["trim", "zen2han"])
        assert t.rows[0][0] == "a"
        assert t.rows[1][1] == " ｄ "  # 対象外の列は不変
        assert n == 1

    def test_unknown_op(self):
        with pytest.raises(DiffDeskError):
            clean_columns(Table(columns=["v"], rows=[]), ["v"], ["nope"])


class TestValidate:
    def test_duplicate_key(self):
        t = Table(columns=["id"], rows=[["1"], ["1"], ["2"]])
        issues = validate_table(t, ValidationRules(key_columns=["id"]))
        assert len(issues) == 1
        assert issues[0].code == "duplicate_key" and issues[0].row == 2

    def test_required(self):
        t = Table(columns=["id", "name"], rows=[["1", ""], ["2", " "]])
        issues = validate_table(t, ValidationRules(required_columns=["name"]))
        assert [i.row for i in issues] == [1, 2]

    def test_email_format(self):
        t = Table(columns=["mail"], rows=[["a@b.co"], ["bad"], [""]])
        issues = validate_table(t, ValidationRules(formats={"mail": "email"}))
        assert len(issues) == 1 and issues[0].row == 2  # 空はスキップ

    def test_max_length(self):
        t = Table(columns=["v"], rows=[["12345"]])
        issues = validate_table(t, ValidationRules(max_lengths={"v": 4}))
        assert issues[0].code == "max_length"

    def test_number_and_date(self):
        t = Table(columns=["n", "d"], rows=[["1.5", "2020-01-01"], ["x", "2020/1/1"]])
        issues = validate_table(t, ValidationRules(
            formats={"n": "number", "d": "date_iso"}))
        assert len(issues) == 2

    def test_unknown_format(self):
        with pytest.raises(DiffDeskError):
            validate_table(Table(columns=["v"], rows=[]),
                           ValidationRules(formats={"v": "nope"}))
