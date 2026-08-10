import pytest

from diffdesk.core import (
    ColumnPair,
    DiffDeskError,
    DiffOptions,
    FilterCondition,
    MappingConfig,
    Profile,
    RowFilter,
    load_profile,
    profile_from_json,
    profile_to_json,
    save_profile,
)
from diffdesk.core.profile import list_profiles


def make_profile() -> Profile:
    return Profile(
        name="月次照合",
        mapping=MappingConfig(pairs=[
            ColumnPair("社員番号", "EmployeeNumber__c", is_key=True),
            ColumnPair("氏名", "Name", sf_field="Name"),
        ]),
        options=DiffOptions(ignore_case=True, numeric_tolerance=0.01),
        row_filter=RowFilter(conditions_a=[FilterCondition("部署", "eq", "営業部")]),
        external_id="社員番号",
    )


def test_json_roundtrip():
    p = make_profile()
    p2 = profile_from_json(profile_to_json(p))
    assert p2.name == p.name
    assert p2.mapping.pairs[0].is_key
    assert p2.options.numeric_tolerance == 0.01
    assert p2.row_filter.conditions_a[0].value == "営業部"
    assert p2.external_id == "社員番号"


def test_save_load_list(tmp_path):
    p = make_profile()
    path = save_profile(p, directory=tmp_path)
    assert path.exists()
    p2 = load_profile("月次照合", directory=tmp_path)
    assert p2.mapping.pairs[0].col_b == "EmployeeNumber__c"
    assert list_profiles(directory=tmp_path) == ["月次照合"]


def test_load_by_path(tmp_path):
    path = save_profile(make_profile(), directory=tmp_path)
    p = load_profile(str(path))
    assert p.name == "月次照合"


def test_invalid_name(tmp_path):
    p = make_profile()
    p.name = "../evil"
    with pytest.raises(DiffDeskError):
        save_profile(p, directory=tmp_path)


def test_invalid_json():
    with pytest.raises(DiffDeskError):
        profile_from_json("{not json")
    with pytest.raises(DiffDeskError):
        profile_from_json("{}")


def test_missing_profile(tmp_path):
    with pytest.raises(DiffDeskError):
        load_profile("なし", directory=tmp_path)


def test_core_is_web_free():
    import subprocess
    import sys
    code = "import diffdesk.core, sys; assert 'fastapi' not in sys.modules; assert 'uvicorn' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True, cwd=str(__import__("pathlib").Path(__file__).parent.parent))
