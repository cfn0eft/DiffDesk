"""v0.9.0機能(紐づけ精度担保: 類似度・提案・AI取込・永続化)のテスト。"""
import pytest

from diffdesk.core import (
    ColumnPair,
    DiffDeskError,
    MappingConfig,
    Table,
    add_manual_link,
    build_link_prompt,
    clear_manual_links,
    diff_tables,
    list_unmatched,
    load_manual_links,
    pair_similarity,
    parse_link_answer,
    remove_manual_link,
    suggest_links,
)


def make_diff():
    a = Table(columns=["id", "名前", "部署"],
              rows=[["1", "山田", "営業"], ["3", "佐藤一郎", "総務"],
                    ["4", "高橋花子", "開発"]])
    b = Table(columns=["id", "name", "dept"],
              rows=[["1", "山田", "営業"], ["9", "佐藤一郎", "総務"],
                    ["8", "全然違う人", "経理"]])
    m = MappingConfig(pairs=[
        ColumnPair("id", "id", is_key=True),
        ColumnPair("名前", "name"),
        ColumnPair("部署", "dept"),
    ])
    return diff_tables(a, b, m)


class TestPairSimilarity:
    def test_high_match(self):
        d = make_diff()
        r = pair_similarity(d, ["3"], ["9"])
        # 名前・部署は完全一致、キーのみ不一致
        assert r["matched"] == 2 and r["total"] == 3
        assert r["score"] > 0.6
        sims = {c["col_a"]: c["sim"] for c in r["columns"]}
        assert sims["名前"] == 1.0 and sims["部署"] == 1.0 and sims["id"] < 1.0

    def test_low_match(self):
        d = make_diff()
        r = pair_similarity(d, ["4"], ["8"])
        assert r["score"] < 0.4

    def test_missing_row_error(self):
        with pytest.raises(DiffDeskError):
            pair_similarity(make_diff(), ["999"], ["9"])

    def test_empty_columns_excluded(self):
        a = Table(columns=["id", "x", "y"], rows=[["1", "abc", ""]])
        b = Table(columns=["id", "x", "y"], rows=[["2", "abc", ""]])
        m = MappingConfig(pairs=[ColumnPair("id", "id", is_key=True),
                                 ColumnPair("x", "x"), ColumnPair("y", "y")])
        d = diff_tables(a, b, m)
        r = pair_similarity(d, ["1"], ["2"])
        assert r["total"] == 2  # yは両方空なので分母から除外


class TestSuggestLinks:
    def test_suggests_best_pair(self):
        d = make_diff()
        out = suggest_links(d, threshold=0.5)
        assert len(out) == 1
        assert out[0]["key_a"] == ["3"] and out[0]["key_b"] == ["9"]
        assert out[0]["score"] > 0.5
        assert "佐藤一郎" in out[0]["label_a"]

    def test_threshold_filters(self):
        d = make_diff()
        assert suggest_links(d, threshold=0.99) == []

    def test_one_to_one(self):
        a = Table(columns=["id", "v"], rows=[["1", "abc"], ["2", "abc"]])
        b = Table(columns=["id", "v"], rows=[["9", "abc"]])
        m = MappingConfig(pairs=[ColumnPair("id", "id", is_key=True),
                                 ColumnPair("v", "v")])
        d = diff_tables(a, b, m)
        out = suggest_links(d, threshold=0.3)
        assert len(out) == 1  # B側1行は1回しか使われない


class TestRankedUnmatched:
    def test_rank_for_sorts_by_score(self):
        d = make_diff()
        cands = list_unmatched(d, "b", rank_for=["3"])
        assert cands[0]["key"] == ["9"]  # 佐藤一郎同士が先頭
        assert cands[0]["score"] > cands[-1]["score"]


class TestLinkPrompt:
    def test_prompt_contains_rows_and_format(self):
        d = make_diff()
        r = build_link_prompt(d)
        assert r["rows_a"] == 2 and r["rows_b"] == 2
        assert "佐藤一郎" in r["prompt"] and "key_a" in r["prompt"]
        assert "JSON" in r["prompt"]

    def test_no_unmatched_error(self):
        a = Table(columns=["id"], rows=[["1"]])
        b = Table(columns=["id"], rows=[["1"]])
        m = MappingConfig(pairs=[ColumnPair("id", "id", is_key=True)])
        d = diff_tables(a, b, m)
        with pytest.raises(DiffDeskError):
            build_link_prompt(d)


class TestParseLinkAnswer:
    def test_parse_with_code_fence(self):
        d = make_diff()
        text = """はい、対応関係を分析しました。

```json
[{"key_a": ["3"], "key_b": ["9"], "confidence": 0.95, "reason": "氏名と部署が完全一致"}]
```
以上です。"""
        r = parse_link_answer(d, text)
        assert len(r["pairs"]) == 1 and r["rejected"] == []
        p = r["pairs"][0]
        assert p["key_a"] == ["3"] and p["key_b"] == ["9"]
        assert p["score"] == 0.95 and "氏名" in p["reason"]

    def test_string_keys_accepted(self):
        d = make_diff()
        r = parse_link_answer(d, '[{"key_a": "3", "key_b": "9"}]')
        assert r["pairs"][0]["key_a"] == ["3"]

    def test_invalid_keys_rejected(self):
        d = make_diff()
        r = parse_link_answer(
            d, '[{"key_a": ["999"], "key_b": ["9"]}, {"key_a": ["3"], "key_b": ["9"]}]')
        assert len(r["pairs"]) == 1
        assert len(r["rejected"]) == 1 and "999" in r["rejected"][0]

    def test_duplicates_rejected(self):
        d = make_diff()
        r = parse_link_answer(
            d, '[{"key_a": ["3"], "key_b": ["9"]}, {"key_a": ["3"], "key_b": ["8"]}]')
        assert len(r["pairs"]) == 1 and len(r["rejected"]) == 1

    def test_no_json_error(self):
        with pytest.raises(DiffDeskError):
            parse_link_answer(make_diff(), "JSONを含まない回答です")
        with pytest.raises(DiffDeskError):
            parse_link_answer(make_diff(), "   ")


class TestManualLinkStore:
    def test_crud_and_dedupe(self, tmp_path):
        e = {"key_a": ["3"], "key_b": ["9"], "note": "確認済み", "score": 0.95}
        entries = add_manual_link(e, directory=tmp_path)
        assert len(entries) == 1
        assert entries[0]["added_at"] and entries[0]["score"] == 0.95
        entries = add_manual_link(e, directory=tmp_path)  # 重複は無視
        assert len(entries) == 1
        assert len(load_manual_links(directory=tmp_path)) == 1
        assert remove_manual_link(0, directory=tmp_path) == []
        add_manual_link(e, directory=tmp_path)
        clear_manual_links(directory=tmp_path)
        assert load_manual_links(directory=tmp_path) == []

    def test_validation(self, tmp_path):
        with pytest.raises(DiffDeskError):
            add_manual_link({"key_a": [], "key_b": ["9"]}, directory=tmp_path)
        with pytest.raises(DiffDeskError):
            add_manual_link({"key_a": ["1"]}, directory=tmp_path)
