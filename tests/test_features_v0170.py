"""v0.17.0 作業セッション保存/復元のテスト。"""
import pytest

from diffdesk.core import DiffDeskError
from diffdesk.core.worksession import (
    decode_raw,
    delete_worksession,
    encode_raw,
    list_worksessions,
    load_worksession,
    save_worksession,
)


def make_payload():
    return {
        "files": [
            {"filename": "a.csv", "raw_b64": encode_raw("id,v\n1,x\n".encode("utf-8")),
             "parse_params": {"encoding": "utf-8", "header_row": 1}, "role": "a"},
            {"filename": "b.csv", "raw_b64": encode_raw("id,v\n1,y\n".encode("utf-8")),
             "parse_params": {"encoding": "utf-8", "header_row": 1}, "role": "b"},
        ],
        "mapping": {"pairs": [{"col_a": "id", "col_b": "id", "is_key": True}],
                    "key_mode": "columns"},
        "options": {"trim": True},
        "row_filter": {"conditions_a": [], "conditions_b": []},
    }


class TestWorksession:
    def test_save_list_load_delete(self, tmp_path):
        meta = save_worksession("8月照合 作業中", make_payload(), directory=tmp_path)
        assert meta["name"] == "8月照合 作業中"
        assert len(meta["files"]) == 2
        assert meta["size"] > 0

        sessions = list_worksessions(directory=tmp_path)
        assert len(sessions) == 1
        assert sessions[0]["files"][0]["role"] == "a"

        data = load_worksession("8月照合 作業中", directory=tmp_path)
        assert data["version"] == 1
        assert decode_raw(data["files"][0]["raw_b64"]) == "id,v\n1,x\n".encode("utf-8")
        assert data["mapping"]["key_mode"] == "columns"

        delete_worksession("8月照合 作業中", directory=tmp_path)
        assert list_worksessions(directory=tmp_path) == []

    def test_overwrite_same_name(self, tmp_path):
        save_worksession("s1", make_payload(), directory=tmp_path)
        p2 = make_payload()
        p2["options"] = {"trim": False}
        save_worksession("s1", p2, directory=tmp_path)
        assert len(list_worksessions(directory=tmp_path)) == 1
        assert load_worksession("s1", directory=tmp_path)["options"] == {"trim": False}

    def test_validation(self, tmp_path):
        with pytest.raises(DiffDeskError):
            save_worksession("", make_payload(), directory=tmp_path)
        with pytest.raises(DiffDeskError):
            save_worksession("x" * 51, make_payload(), directory=tmp_path)
        with pytest.raises(DiffDeskError):
            save_worksession("s", {"files": []}, directory=tmp_path)
        with pytest.raises(DiffDeskError):
            load_worksession("ない", directory=tmp_path)
        with pytest.raises(DiffDeskError):
            delete_worksession("ない", directory=tmp_path)

    def test_binary_roundtrip(self, tmp_path):
        payload = make_payload()
        blob = bytes(range(256)) * 10  # xlsx等のバイナリ相当
        payload["files"][0]["raw_b64"] = encode_raw(blob)
        save_worksession("bin", payload, directory=tmp_path)
        data = load_worksession("bin", directory=tmp_path)
        assert decode_raw(data["files"][0]["raw_b64"]) == blob
