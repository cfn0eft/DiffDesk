"""v0.6.0機能(計算列・レシピ)のテスト。"""
import pytest

from diffdesk.core import (
    DiffDeskError,
    Table,
    apply_recipe,
    concat_columns,
    conditional_column,
    describe_op,
    list_recipes,
    load_recipe,
    save_recipe,
    substring_column,
)


class TestCalcColumns:
    def test_concat(self):
        t = Table(columns=["姓", "名"], rows=[["山田", "太郎"], ["鈴木", "花子"]])
        t = concat_columns(t, ["姓", "名"], "氏名", " ")
        assert t.columns == ["姓", "名", "氏名"]
        assert t.rows[0][2] == "山田 太郎"

    def test_concat_requires_two(self):
        t = Table(columns=["a"], rows=[])
        with pytest.raises(DiffDeskError):
            concat_columns(t, ["a"], "x")

    def test_substring(self):
        t = Table(columns=["コード"], rows=[["AB-1234"], ["CD-5"]])
        t = substring_column(t, "コード", "プレフィックス", 1, 2)
        assert [r[1] for r in t.rows] == ["AB", "CD"]
        t = substring_column(t, "コード", "後半", 4, None)
        assert [r[2] for r in t.rows] == ["1234", "5"]

    def test_conditional(self):
        t = Table(columns=["点数"], rows=[["80"], ["40"], ["x"]])
        t = conditional_column(t, "点数", "gte", "60", "判定", "合格", "不合格")
        assert [r[1] for r in t.rows] == ["合格", "不合格", "不合格"]

    def test_conditional_placeholder(self):
        t = Table(columns=["部署"], rows=[[""], ["営業部"]])
        t = conditional_column(t, "部署", "empty", "", "部署2", "未設定", "{値}")
        assert [r[1] for r in t.rows] == ["未設定", "営業部"]

    def test_duplicate_name_rejected(self):
        t = Table(columns=["a", "b"], rows=[])
        with pytest.raises(DiffDeskError):
            concat_columns(t, ["a", "b"], "a")


class TestRecipe:
    OPS = [
        {"op": "clean", "params": {"columns": ["名前"], "ops": ["trim", "zen2han"]}},
        {"op": "replace", "params": {"query": "営業部", "replacement": "セールス部"}},
        {"op": "conditional_column",
         "params": {"column": "名前", "op": "not_empty", "value": "",
                    "new_name": "有効", "then_value": "Y", "else_value": "N"}},
    ]

    def make_table(self):
        return Table(columns=["名前", "部署"],
                     rows=[[" ＡＢＣ ", "営業部"], ["", "開発部"]])

    def test_apply_recipe(self):
        t, logs = apply_recipe(self.make_table(), self.OPS)
        assert t.rows[0][0] == "ABC"
        assert t.rows[0][1] == "セールス部"
        assert t.columns[-1] == "有効"
        assert [r[2] for r in t.rows] == ["Y", "N"]
        assert len(logs) == 3

    def test_save_load_list(self, tmp_path):
        save_recipe("月次整形", self.OPS, directory=tmp_path)
        assert list_recipes(directory=tmp_path) == ["月次整形"]
        ops = load_recipe("月次整形", directory=tmp_path)
        assert ops == self.OPS
        t, _ = apply_recipe(self.make_table(), ops)
        assert t.rows[0][0] == "ABC"

    def test_unknown_op(self):
        with pytest.raises(DiffDeskError):
            apply_recipe(Table(columns=["a"], rows=[]), [{"op": "nope"}])

    def test_recipe_error_mentions_op(self):
        ops = [{"op": "clean", "params": {"columns": ["無い列"], "ops": ["trim"]}}]
        with pytest.raises(DiffDeskError) as ei:
            apply_recipe(Table(columns=["a"], rows=[]), ops)
        assert "クレンジング" in str(ei.value)

    def test_describe(self):
        assert "クレンジング" in describe_op(self.OPS[0])
        assert "名前" in describe_op(self.OPS[0])

    def test_empty_save_rejected(self, tmp_path):
        with pytest.raises(DiffDeskError):
            save_recipe("空", [], directory=tmp_path)
