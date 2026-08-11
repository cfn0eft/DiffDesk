import pytest
from fastapi.testclient import TestClient

import diffdesk.core.profile as profile_mod
from diffdesk.web.app import create_app
from diffdesk.web.sessions import SessionStore
from tests.conftest import load_fixture


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(profile_mod, "DEFAULT_PROFILE_DIR", tmp_path / "profiles")
    # ストアをテストごとに初期化
    import diffdesk.web.routes as routes_mod
    import diffdesk.web.sessions as sessions_mod
    fresh = SessionStore()
    monkeypatch.setattr(sessions_mod, "store", fresh)
    monkeypatch.setattr(routes_mod, "store", fresh)
    return TestClient(create_app())


def upload(client, name: str, content: bytes) -> dict:
    r = client.post("/api/files", files={"file": (name, content)})
    assert r.status_code == 200, r.text
    return r.json()


MAPPING = {"pairs": [
    {"col_a": "社員番号", "col_b": "EmployeeNumber__c", "is_key": True},
    {"col_a": "氏名", "col_b": "Name"},
    {"col_a": "メール", "col_b": "Email"},
    {"col_a": "部署", "col_b": "Department__c", "sf_field": "Busho__c"},
]}


class TestFiles:
    def test_upload_detects_cp932(self, client):
        info = upload(client, "master.csv", load_fixture("master_cp932.csv"))
        assert info["detected_encoding"] == "cp932"
        assert info["preview"]["columns"][0] == "氏名"
        assert info["preview"]["rows"][0][3] == "0001"  # 先頭ゼロ保持

    def test_upload_excel_lists_sheets(self, client):
        info = upload(client, "master.xlsx", load_fixture("master.xlsx"))
        assert info["sheets"] == ["社員マスタ", "タイトル付き"]
        assert info["preview"]["columns"][0] == "氏名"

    def test_reparse_with_sheet_and_header(self, client):
        info = upload(client, "master.xlsx", load_fixture("master.xlsx"))
        r = client.post(f"/api/files/{info['file_id']}/parse",
                        json={"sheet": "タイトル付き", "header_row": 2})
        assert r.status_code == 200
        assert r.json()["preview"]["columns"][0] == "氏名"

    def test_reparse_bad_encoding_400(self, client):
        info = upload(client, "master.csv", load_fixture("master_cp932.csv"))
        r = client.post(f"/api/files/{info['file_id']}/parse",
                        json={"encoding": "utf-8"})
        assert r.status_code == 400
        assert "エラー" not in r.json()["error"]["code"]  # 構造化エラー

    def test_get_paged(self, client):
        info = upload(client, "m.csv", load_fixture("master_utf8.csv"))
        r = client.get(f"/api/files/{info['file_id']}?offset=1&limit=2")
        body = r.json()
        assert body["total_rows"] == 5 and len(body["rows"]) == 2

    def test_put_table_and_export(self, client):
        info = upload(client, "m.csv", load_fixture("master_utf8.csv"))
        fid = info["file_id"]
        r = client.put(f"/api/files/{fid}/table",
                       json={"columns": ["a"], "rows": [["あ"]]})
        assert r.status_code == 200
        r = client.post(f"/api/export/table/{fid}",
                        json={"encoding": "cp932", "filename": "編集済"})
        assert r.status_code == 200
        assert r.content.decode("cp932") == "a\r\nあ\r\n"
        assert "%E7%B7%A8%E9%9B%86%E6%B8%88" in r.headers["content-disposition"]

    def test_export_unknown_encoding_400(self, client):
        info = upload(client, "m.csv", load_fixture("master_utf8.csv"))
        r = client.post(f"/api/export/table/{info['file_id']}",
                        json={"encoding": "nope-encoding"})
        assert r.status_code == 400
        assert "エンコーディング" in r.json()["error"]["message"]

    def test_upload_xls_clear_error(self, client):
        ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 16
        r = client.post("/api/files", files={"file": ("old.xls", ole)})
        assert r.status_code == 400
        assert ".xlsx" in r.json()["error"]["message"]

    def test_export_unencodable_400_with_locations(self, client):
        info = upload(client, "m.csv", "col\n𩸽\n".encode("utf-8"))
        r = client.post(f"/api/export/table/{info['file_id']}",
                        json={"encoding": "cp932"})
        assert r.status_code == 400
        assert r.json()["error"]["locations"][0]["row"] == 1

    def test_clean_validate_dedupe_replace(self, client):
        raw = "名前,日付\nＡＢＣ,2020/1/5\nＡＢＣ,2020/1/5\n".encode("utf-8")
        fid = upload(client, "x.csv", raw)["file_id"]
        r = client.post(f"/api/files/{fid}/dedupe")
        assert r.json()["removed"] == 1
        r = client.post(f"/api/files/{fid}/clean",
                        json={"columns": ["名前", "日付"], "ops": ["zen2han", "date_iso"]})
        assert r.json()["changed_cells"] == 2
        r = client.post(f"/api/files/{fid}/replace",
                        json={"query": "ABC", "replacement": "XYZ"})
        assert r.json()["replaced"] == 1
        r = client.post(f"/api/files/{fid}/validate",
                        json={"required_columns": ["名前"]})
        assert r.json()["count"] == 0

    def test_concat_and_enrich(self, client):
        f1 = upload(client, "a.csv", "id,v\n1,x\n".encode("utf-8"))["file_id"]
        f2 = upload(client, "b.csv", "id,w\n1,y\n".encode("utf-8"))["file_id"]
        r = client.post("/api/files/concat", json={"file_ids": [f1, f2]})
        assert r.status_code == 200
        assert r.json()["preview"]["total_rows"] == 2
        r = client.post(f"/api/files/{f1}/enrich",
                        json={"other_file_id": f2,
                              "key_pairs": [["id", "id"]], "add_columns": ["w"]})
        body = r.json()
        assert body["preview"]["columns"] == ["id", "v", "w"]
        assert body["unmatched"] == 0


class TestDiffFlow:
    def run_diff(self, client) -> tuple[str, dict]:
        fa = upload(client, "master.csv", load_fixture("master_cp932.csv"))["file_id"]
        fb = upload(client, "sf.csv", load_fixture("salesforce_export.csv"))["file_id"]
        r = client.post("/api/diff", json={
            "file_a": fa, "file_b": fb, "mapping": MAPPING,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        return body["diff_id"], body

    def test_automap(self, client):
        fa = upload(client, "a.csv", "Name,Email\n".encode("utf-8"))["file_id"]
        fb = upload(client, "b.csv", "ｎａｍｅ,Email,Extra\n".encode("utf-8"))["file_id"]
        r = client.post("/api/automap", json={"file_a": fa, "file_b": fb})
        body = r.json()
        assert body["by_name"] == 2
        assert any(p["col_a"] == "Email" and p["col_b"] == "Email" for p in body["pairs"])
        assert any(p["col_a"] == "Name" and p["col_b"] == "ｎａｍｅ" for p in body["pairs"])

    def test_automap_value_based(self, client):
        fa = upload(client, "master.csv", load_fixture("master_utf8.csv"))["file_id"]
        fb = upload(client, "sf.csv", load_fixture("salesforce_export.csv"))["file_id"]
        r = client.post("/api/automap", json={"file_a": fa, "file_b": fb})
        body = r.json()
        by = {p["col_a"]: p["col_b"] for p in body["pairs"]}
        # 名前が一致しない日本語↔SF API名でも辞書・値ベースで対応付けられる
        assert by["社員番号"] == "EmployeeNumber__c"
        assert by["氏名"] == "Name"
        assert by["メール"] == "Email"

    def test_verify_endpoint_and_export(self, client):
        diff_id, _ = TestDiffFlow().run_diff(client)
        v = client.get(f"/api/diff/{diff_id}/verify").json()
        assert v["passed"] is False and v["only_a"] == 2
        v2 = client.get(f"/api/diff/{diff_id}/verify?only_b_is_error=false").json()
        assert v2["only_b"] == 1 and v2["passed"] is False  # 未投入があるため依然NG
        r = client.post(f"/api/export/verify/{diff_id}", json={"format": "csv"})
        text = r.content.decode("utf-8-sig")
        assert len(text.strip().splitlines()) == 6  # ヘッダー+問題5行
        r = client.post(f"/api/export/verify/{diff_id}", json={"format": "xlsx"})
        assert r.content[:2] == b"PK"

    def test_diff_summary_and_rows(self, client):
        diff_id, body = self.run_diff(client)
        assert body["summary"]["changed"] == 2
        r = client.get(f"/api/diff/{diff_id}/rows?status=changed")
        rows = r.json()["rows"]
        assert len(rows) == 2
        assert rows[0]["cell_diffs"]

    def test_export_upsert(self, client):
        diff_id, _ = self.run_diff(client)
        r = client.post(f"/api/export/upsert/{diff_id}",
                        json={"external_id": "社員番号"})
        assert r.status_code == 200
        text = r.content.decode("utf-8-sig")
        assert text.splitlines()[0] == "EmployeeNumber__c,Name,Email,Busho__c"
        assert len(text.strip().splitlines()) == 5  # ヘッダー+4行

    def test_export_upsert_nothing_selected_400(self, client):
        diff_id, _ = self.run_diff(client)
        r = client.post(f"/api/export/upsert/{diff_id}",
                        json={"external_id": "社員番号",
                              "include_insert": False, "include_update": False})
        assert r.status_code == 400  # 全件出力ではなく明示エラー

    def test_export_delete_requires_id_mapping(self, client):
        diff_id, _ = self.run_diff(client)
        r = client.post(f"/api/export/delete/{diff_id}", json={})
        assert r.status_code == 400  # Id列がマッピングにない

    def test_export_sdl_and_reports(self, client):
        diff_id, _ = self.run_diff(client)
        assert "Busho__c=Busho__c" in client.get(f"/api/export/sdl/{diff_id}").text
        r = client.post(f"/api/export/report/{diff_id}", json={"format": "csv"})
        assert "状態" in r.content.decode("utf-8-sig")
        r = client.post(f"/api/export/report/{diff_id}", json={"format": "xlsx"})
        assert r.content[:2] == b"PK"

    def test_merge(self, client):
        diff_id, _ = self.run_diff(client)
        r = client.post(f"/api/diff/{diff_id}/merge", json={
            "choices": [{"key": ["0002"], "col_a": "メール", "use": "b"}],
        })
        body = r.json()
        row = next(row for row in body["preview"]["rows"] if row[0] == "0002")
        assert row[2] == "hanako-new@example.com"

    def test_diff_error_missing_key(self, client):
        fa = upload(client, "a.csv", "x\n1\n".encode("utf-8"))["file_id"]
        fb = upload(client, "b.csv", "y\n1\n".encode("utf-8"))["file_id"]
        r = client.post("/api/diff", json={
            "file_a": fa, "file_b": fb,
            "mapping": {"pairs": [{"col_a": "x", "col_b": "y"}]},
        })
        assert r.status_code == 400
        assert "キー" in r.json()["error"]["message"]


class TestV040Features:
    def test_clusters_and_apply(self, client):
        raw = "会社\n株式会社テスト\nテスト(株)\n別会社\n".encode("utf-8")
        fid = upload(client, "c.csv", raw)["file_id"]
        r = client.post(f"/api/files/{fid}/clusters", json={"column": "会社"}).json()
        assert r["count"] == 1
        mapping = {"テスト(株)": "株式会社テスト"}
        r = client.post(f"/api/files/{fid}/apply-map",
                        json={"column": "会社", "mapping": mapping}).json()
        assert r["changed"] == 1

    def test_error_analysis_and_retry(self, client):
        raw = ("氏名,ERROR\n山田,REQUIRED_FIELD_MISSING:必須項目\n"
               "鈴木,UNABLE_TO_LOCK_ROW:ロック\n").encode("utf-8")
        fid = upload(client, "error.csv", raw)["file_id"]
        r = client.post(f"/api/files/{fid}/analyze-errors").json()
        assert r["total_rows"] == 2 and len(r["categories"]) == 2
        res = client.post(f"/api/export/retry/{fid}", json={})
        text = res.content.decode("utf-8-sig")
        assert text.splitlines()[0] == "氏名"  # ERROR列除去
        assert len(text.strip().splitlines()) == 3

    def test_anonymize_creates_new_file(self, client):
        fid = upload(client, "m.csv", load_fixture("master_utf8.csv"))["file_id"]
        r = client.post(f"/api/files/{fid}/anonymize",
                        json={"spec": {"氏名": "name", "メール": "email"}}).json()
        assert r["changed"] == 10
        assert r["file_id"] != fid
        assert "@example.com" in r["preview"]["rows"][0][1]

    def test_split_column(self, client):
        raw = "氏名\n山田 太郎\n鈴木 花子\n".encode("utf-8")
        fid = upload(client, "s.csv", raw)["file_id"]
        r = client.post(f"/api/files/{fid}/split-column",
                        json={"column": "氏名", "delimiter": " "}).json()
        assert r["parts"] == 2
        assert r["preview"]["columns"] == ["氏名_1", "氏名_2"]

    def test_column_values_and_allowed_validation(self, client):
        fid = upload(client, "m.csv", load_fixture("master_utf8.csv"))["file_id"]
        r = client.post(f"/api/files/{fid}/column-values", json={"column": "部署"}).json()
        assert set(r["values"]) == {"営業部", "開発部", "総務部"}
        v = client.post(f"/api/files/{fid}/validate",
                        json={"allowed_values": {"部署": ["営業部", "開発部"]}}).json()
        assert v["count"] == 1  # 総務部が許可外

    def test_clean_ops_includes_fill_down(self, client):
        ops = {o["id"] for o in client.get("/api/clean-ops").json()["ops"]}
        assert {"fill_down", "digits_only", "alnum_han"} <= ops


class TestV050Features:
    def test_restore_export(self, client):
        diff_id, _ = TestDiffFlow().run_diff(client)
        r = client.post(f"/api/export/restore/{diff_id}", json={})
        text = r.content.decode("utf-8-sig")
        assert "hanako-new@example.com" in text  # 投入前のB値
        assert len(text.strip().splitlines()) == 3  # ヘッダー+changed2行

    def test_undo_delete(self, client):
        raw = ("ID,STATUS\na01x,Item Created\na01y,Item Updated\n").encode("utf-8")
        fid = upload(client, "success.csv", raw)["file_id"]
        r = client.post(f"/api/files/{fid}/undo-delete", json={})
        assert r.status_code == 200
        text = r.content.decode("utf-8-sig")
        assert text.strip().splitlines() == ["Id", "a01x"]
        assert r.headers["X-Skipped-Updates"] == "1"

    def test_html_report(self, client):
        diff_id, _ = TestDiffFlow().run_diff(client)
        r = client.post(f"/api/export/html/{diff_id}", json={})
        html_text = r.content.decode("utf-8")
        assert "<!DOCTYPE html>" in html_text and "要確認" in html_text

    def test_profile_and_baseline(self, client):
        fid = upload(client, "m.csv", load_fixture("master_utf8.csv"))["file_id"]
        p = client.post(f"/api/files/{fid}/profile", json={}).json()
        assert p["rows"] == 5
        client.post(f"/api/files/{fid}/save-baseline", json={"name": "月次"})
        assert client.get("/api/baselines").json()["baselines"] == ["月次"]
        w = client.post(f"/api/files/{fid}/compare-baseline",
                        json={"name": "月次"}).json()["warnings"]
        assert w[0]["level"] == "info"  # 同一ファイルなので変化なし

    def test_fuzzy_match_and_link(self, client):
        fa = upload(client, "a.csv", "氏名\n山田太郎\n鈴木花子\n".encode("utf-8"))["file_id"]
        fb = upload(client, "b.csv", "name\n山田 太郎\n別人\n".encode("utf-8"))["file_id"]
        r = client.post("/api/fuzzy-match", json={
            "file_a": fa, "file_b": fb, "pairs": [["氏名", "name"]], "threshold": 0.7,
        }).json()
        assert r["count"] == 1
        assert r["candidates"][0]["values_a"] == ["山田太郎"]
        r2 = client.post("/api/fuzzy-link", json={
            "file_a": fa, "file_b": fb, "matches": r["candidates"],
        }).json()
        assert r2["preview"]["columns"] == ["氏名", "name", "突合スコア"]

    def test_crosstab(self, client):
        raw = "群,性別\nG1,雄\nG1,雌\nG2,雄\n".encode("utf-8")
        fid = upload(client, "g.csv", raw)["file_id"]
        r = client.post(f"/api/files/{fid}/crosstab",
                        json={"row_col": "群", "col_col": "性別"}).json()
        assert r["table"]["columns"] == ["群\\性別", "雄", "雌", "(合計)"]

    def test_split_address(self, client):
        raw = "住所\n東京都港区芝1-2-3\n".encode("utf-8")
        fid = upload(client, "addr.csv", raw)["file_id"]
        r = client.post(f"/api/files/{fid}/split-address", json={"column": "住所"}).json()
        assert r["parsed"] == 1
        assert "住所_都道府県" in r["preview"]["columns"]

    def test_validate_ranges(self, client):
        raw = "ALT\n25\n70\n".encode("utf-8")
        fid = upload(client, "lab.csv", raw)["file_id"]
        r = client.post(f"/api/files/{fid}/validate",
                        json={"ranges": {"ALT": [10, 50]}}).json()
        assert r["count"] == 1 and "範囲外" in r["issues"][0]["message"]


class TestV060Features:
    def test_calc_column_and_recipe_roundtrip(self, client, monkeypatch, tmp_path):
        raw = "姓,名,部署\n山田, ＡＢ ,営業部\n鈴木,子,開発部\n".encode("utf-8")
        fid = upload(client, "r.csv", raw)["file_id"]
        # クレンジング → 計算列(結合) → 履歴確認 → レシピ保存 → 別ファイルに適用
        client.post(f"/api/files/{fid}/clean",
                    json={"columns": ["名"], "ops": ["trim", "zen2han"]})
        r = client.post(f"/api/files/{fid}/calc-column", json={
            "mode": "concat", "new_name": "氏名", "columns": ["姓", "名"],
            "separator": " "})
        assert "氏名" in r.json()["preview"]["columns"]
        rec = client.get(f"/api/files/{fid}/recipe").json()
        assert len(rec["ops"]) == 2
        assert any("クレンジング" in l for l in rec["labels"])
        client.post("/api/recipes", json={"name": "整形テスト", "file_id": fid})
        assert "整形テスト" in client.get("/api/recipes").json()["recipes"]

        fid2 = upload(client, "r2.csv", raw)["file_id"]
        r = client.post(f"/api/files/{fid2}/apply-recipe", json={"name": "整形テスト"})
        body = r.json()
        assert len(body["logs"]) == 2
        assert "氏名" in body["preview"]["columns"]
        assert body["preview"]["rows"][0][3] == "山田 AB"

    def test_conditional_calc(self, client):
        raw = "点数\n80\n40\n".encode("utf-8")
        fid = upload(client, "s.csv", raw)["file_id"]
        r = client.post(f"/api/files/{fid}/calc-column", json={
            "mode": "conditional", "new_name": "判定", "column": "点数",
            "op": "gte", "value": "60", "then_value": "合格", "else_value": "不合格"})
        rows = r.json()["preview"]["rows"]
        assert rows[0][1] == "合格" and rows[1][1] == "不合格"


class TestProfiles:
    def test_save_load_list_delete(self, client):
        profile = {
            "name": "月次",
            "mapping": MAPPING,
            "options": {"ignore_case": True},
            "external_id": "社員番号",
        }
        r = client.post("/api/profiles", json={"profile": profile})
        assert r.status_code == 200
        assert client.get("/api/profiles").json()["profiles"] == ["月次"]
        loaded = client.get("/api/profiles/月次").json()["profile"]
        assert loaded["mapping"]["pairs"][0]["is_key"]
        assert loaded["options"]["ignore_case"]
        client.delete("/api/profiles/月次")
        assert client.get("/api/profiles").json()["profiles"] == []


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "html" in r.text
