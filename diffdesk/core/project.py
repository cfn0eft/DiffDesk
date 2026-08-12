"""案件(プロジェクト)切替。

既知差分・照合履歴・手動紐づけ・ユーザー辞書などのワークスペースデータを
案件ごとに分けて保存する。既定案件は従来どおり ~/.diffdesk/ 直下を使う
(過去のデータがそのまま既定案件として引き継がれる)。
その他の案件は ~/.diffdesk/projects/<案件名>/ 配下。
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from . import profile as _profile
from .model import DiffDeskError

DEFAULT_NAME = "既定"
_MAX_NAME = 50
_SAFE = re.compile(r'[\\/:*?"<>|\s.]+')


def _root(root: Path | None = None) -> Path:
    d = root or _profile.DEFAULT_PROFILE_DIR.parent
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_dirname(name: str) -> str:
    s = _SAFE.sub("_", name).strip("_")
    return s or "project"


def _load(root: Path | None = None) -> dict:
    path = _root(root) / "projects.json"
    names: list[str] = []
    current = DEFAULT_NAME
    if path.exists():
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            names = [str(n) for n in d.get("names", [])]
            current = str(d.get("current", DEFAULT_NAME))
        except json.JSONDecodeError:
            pass
    if DEFAULT_NAME not in names:
        names.insert(0, DEFAULT_NAME)
    if current not in names:
        current = DEFAULT_NAME
    return {"current": current, "names": names}


def _save(cfg: dict, root: Path | None = None) -> None:
    (_root(root) / "projects.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")


def list_projects(*, root: Path | None = None) -> dict:
    """{"current": 現在の案件名, "names": [案件名, ...]}"""
    return _load(root)


def data_dir(name: str | None = None, *, root: Path | None = None) -> Path:
    """案件のデータ保存先。省略時は現在の案件。"""
    cfg = _load(root)
    name = name or cfg["current"]
    base = _root(root)
    if name == DEFAULT_NAME:
        return base
    d = base / "projects" / _safe_dirname(name)
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_project(name: str, *, root: Path | None = None) -> dict:
    name = str(name).strip()
    if not name:
        raise DiffDeskError("案件名を入力してください。")
    if len(name) > _MAX_NAME:
        raise DiffDeskError(f"案件名は{_MAX_NAME}文字以内にしてください。")
    cfg = _load(root)
    if name in cfg["names"]:
        raise DiffDeskError(f"案件「{name}」は既に存在します。")
    if name != DEFAULT_NAME and any(
            _safe_dirname(name) == _safe_dirname(n)
            for n in cfg["names"] if n != DEFAULT_NAME):
        raise DiffDeskError("保存フォルダ名が同じになる案件が既にあります。別の名前にしてください。")
    cfg["names"].append(name)
    cfg["current"] = name  # 作成した案件へ切替
    _save(cfg, root)
    data_dir(name, root=root)
    return cfg


def switch_project(name: str, *, root: Path | None = None) -> dict:
    cfg = _load(root)
    if name not in cfg["names"]:
        raise DiffDeskError(f"案件がありません: {name}")
    cfg["current"] = name
    _save(cfg, root)
    return cfg


def delete_project(name: str, *, root: Path | None = None) -> dict:
    """案件を削除する(保存データごと)。既定案件は削除不可。"""
    if name == DEFAULT_NAME:
        raise DiffDeskError("既定の案件は削除できません。")
    cfg = _load(root)
    if name not in cfg["names"]:
        raise DiffDeskError(f"案件がありません: {name}")
    cfg["names"].remove(name)
    if cfg["current"] == name:
        cfg["current"] = DEFAULT_NAME
    _save(cfg, root)
    d = _root(root) / "projects" / _safe_dirname(name)
    if d.exists():
        shutil.rmtree(d)
    return cfg
