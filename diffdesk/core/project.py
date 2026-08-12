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


# ---------------------------------------------------------------- 持ち出し(エクスポート/インポート)
_EXPORT_FILES = ("known_diffs.json", "manual_links.json", "user_dict.json",
                 "notes.json", "history.json", "audit.jsonl", "projects.json")
_EXPORT_DIRS = ("snapshots", "sessions")


def export_project(*, root: Path | None = None) -> tuple[str, bytes]:
    """現在の案件のデータ一式をzipにする。(案件名, zipバイト列) を返す。"""
    import io
    import json as _json
    import zipfile
    from datetime import datetime

    cfg = _load(root)
    name = cfg["current"]
    d = data_dir(name, root=root)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("diffdesk_project.json", _json.dumps({
            "name": name,
            "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "format": 1,
        }, ensure_ascii=False))
        for fn in _EXPORT_FILES:
            if fn == "projects.json":
                continue  # 案件一覧そのものは含めない
            path = d / fn
            if path.exists():
                z.writestr(fn, path.read_bytes())
        for sub in _EXPORT_DIRS:
            subdir = d / sub
            if subdir.is_dir():
                for f in sorted(subdir.iterdir()):
                    if f.is_file():
                        z.writestr(f"{sub}/{f.name}", f.read_bytes())
    return name, buf.getvalue()


def import_project(data: bytes, *, root: Path | None = None) -> dict:
    """案件zipを新しい案件として取り込み、切り替える。

    既存案件は上書きしない(同名なら「名前(2)」のように別名を付ける)。
    """
    import io
    import json as _json
    import zipfile

    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise DiffDeskError("案件ファイル(zip)として読み込めませんでした。")
    try:
        meta = _json.loads(z.read("diffdesk_project.json").decode("utf-8"))
    except KeyError:
        raise DiffDeskError("DiffDeskの案件ファイルではありません(diffdesk_project.json がありません)。")

    base = str(meta.get("name") or "取り込んだ案件").strip() or "取り込んだ案件"
    cfg = _load(root)
    name = base
    n = 2
    while name in cfg["names"] or (
            name != DEFAULT_NAME and any(
                _safe_dirname(name) == _safe_dirname(x)
                for x in cfg["names"] if x != DEFAULT_NAME)):
        name = f"{base}({n})"
        n += 1
    create_project(name, root=root)
    d = data_dir(name, root=root)

    allowed = set(_EXPORT_FILES) - {"projects.json"}
    for info in z.infolist():
        if info.is_dir():
            continue
        parts = Path(info.filename).parts
        if ".." in parts or Path(info.filename).is_absolute():
            continue  # 不正なパスは無視
        if len(parts) == 1 and parts[0] in allowed:
            (d / parts[0]).write_bytes(z.read(info))
        elif len(parts) == 2 and parts[0] in _EXPORT_DIRS:
            sub = d / parts[0]
            sub.mkdir(parents=True, exist_ok=True)
            (sub / parts[1]).write_bytes(z.read(info))
    return {**_load(root), "imported": name}
