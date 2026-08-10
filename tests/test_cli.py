import json
from pathlib import Path

import pytest

from diffdesk.cli import run_cli
from diffdesk.core import (
    ColumnPair,
    MappingConfig,
    Profile,
    load_csv,
    save_profile,
)


@pytest.fixture
def profile_path(tmp_path) -> Path:
    p = Profile(
        name="test",
        mapping=MappingConfig(pairs=[
            ColumnPair("社員番号", "EmployeeNumber__c", is_key=True),
            ColumnPair("氏名", "Name"),
            ColumnPair("メール", "Email"),
            ColumnPair("部署", "Department__c"),
        ]),
        external_id="社員番号",
    )
    return save_profile(p, directory=tmp_path)


def test_diff_command(fixtures_dir, profile_path, capsys):
    rc = run_cli([
        "diff",
        str(fixtures_dir / "master_utf8.csv"),
        str(fixtures_dir / "salesforce_export.csv"),
        "--profile", str(profile_path), "--json",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    summary = json.loads(out.strip().splitlines()[-1])
    assert summary["changed"] == 2 and summary["only_a"] == 2


def test_diff_check_exit_code(fixtures_dir, profile_path):
    rc = run_cli([
        "diff", str(fixtures_dir / "master_utf8.csv"),
        str(fixtures_dir / "salesforce_export.csv"),
        "--profile", str(profile_path), "--check",
    ])
    assert rc == 1


def test_upsert_command(fixtures_dir, profile_path, tmp_path):
    out = tmp_path / "upsert.csv"
    sdl = tmp_path / "map.sdl"
    rc = run_cli([
        "upsert", str(fixtures_dir / "master_utf8.csv"),
        str(fixtures_dir / "salesforce_export.csv"),
        "--profile", str(profile_path), "--out", str(out), "--sdl", str(sdl),
    ])
    assert rc == 0
    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # utf-8-sig
    t = load_csv(raw)
    assert t.columns == ["EmployeeNumber__c", "Name", "Email", "Department__c"]
    assert len(t.rows) == 4
    assert "EmployeeNumber__c=EmployeeNumber__c" in sdl.read_text()


def test_upsert_excel_input(fixtures_dir, profile_path, tmp_path):
    out = tmp_path / "upsert.csv"
    rc = run_cli([
        "upsert", str(fixtures_dir / "master.xlsx"),
        str(fixtures_dir / "salesforce_export.csv"),
        "--profile", str(profile_path), "--out", str(out),
    ])
    assert rc == 0
    assert len(load_csv(out.read_bytes()).rows) == 4


def test_verify_command(fixtures_dir, profile_path, tmp_path, capsys):
    report = tmp_path / "verify.xlsx"
    rc = run_cli([
        "verify", str(fixtures_dir / "master_utf8.csv"),
        str(fixtures_dir / "salesforce_export.csv"),
        "--profile", str(profile_path), "--report", str(report),
    ])
    assert rc == 1  # 差異あり
    out = capsys.readouterr().out
    assert "要確認" in out and "未投入" in out
    assert report.read_bytes()[:2] == b"PK"


def test_verify_command_pass(fixtures_dir, tmp_path):
    # 同一ファイル同士の比較=全件一致で合格(終了コード0)
    p = Profile(name="self", mapping=MappingConfig(pairs=[
        ColumnPair("社員番号", "社員番号", is_key=True),
        ColumnPair("氏名", "氏名"),
    ]))
    path = save_profile(p, directory=tmp_path)
    rc = run_cli([
        "verify", str(fixtures_dir / "master_utf8.csv"),
        str(fixtures_dir / "master_utf8.csv"),
        "--profile", str(path),
    ])
    assert rc == 0


def test_simple_mapping_json_with_external_id(fixtures_dir, tmp_path, capsys):
    """単純対応表JSON+--external-idでキー指定なしでも動く。"""
    mapping = tmp_path / "map.json"
    mapping.write_text(
        '{"社員番号": "EmployeeNumber__c", "氏名": "Name", "メール": "Email"}',
        encoding="utf-8")
    rc = run_cli([
        "verify", str(fixtures_dir / "master_utf8.csv"),
        str(fixtures_dir / "salesforce_export.csv"),
        "--profile", str(mapping), "--external-id", "社員番号",
    ])
    assert rc == 1  # フィクスチャは差異ありなので要確認
    assert "未投入" in capsys.readouterr().out


def test_convert_encoding(fixtures_dir, tmp_path):
    out = tmp_path / "out.csv"
    rc = run_cli([
        "convert", str(fixtures_dir / "master_cp932.csv"),
        "--out", str(out), "--out-encoding", "utf-8",
    ])
    assert rc == 0
    assert "氏名" in out.read_bytes().decode("utf-8")


def test_convert_to_xlsx(fixtures_dir, tmp_path):
    out = tmp_path / "out.xlsx"
    rc = run_cli(["convert", str(fixtures_dir / "master_utf8.csv"), "--out", str(out)])
    assert rc == 0
    from diffdesk.core import load_excel
    assert load_excel(out.read_bytes()).columns[0] == "氏名"


def test_validate_command(fixtures_dir, capsys):
    rc = run_cli([
        "validate", str(fixtures_dir / "master_utf8.csv"),
        "--keys", "社員番号", "--required", "氏名",
        "--format", "メール=email",
    ])
    assert rc == 0  # フィクスチャは問題なし


def test_validate_finds_issues(tmp_path):
    f = tmp_path / "bad.csv"
    f.write_text("id,mail\n1,ok@example.com\n1,bad\n", encoding="utf-8")
    rc = run_cli(["validate", str(f), "--keys", "id", "--format", "mail=email"])
    assert rc == 1


def test_concat_command(fixtures_dir, tmp_path):
    out = tmp_path / "merged.csv"
    rc = run_cli([
        "concat", str(fixtures_dir / "master_utf8.csv"),
        str(fixtures_dir / "master_cp932.csv"), "--out", str(out),
    ])
    assert rc == 0
    assert len(load_csv(out.read_bytes()).rows) == 10


def test_missing_file_error(profile_path, capsys):
    rc = run_cli([
        "diff", "nope.csv", "nope2.csv", "--profile", str(profile_path),
    ])
    assert rc == 2
    assert "エラー" in capsys.readouterr().err
