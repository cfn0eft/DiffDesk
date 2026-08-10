"""プロファイル(マッピング設定等)のJSON入出力。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .model import DiffDeskError, Profile

DEFAULT_PROFILE_DIR = Path.home() / ".diffdesk" / "profiles"

_NAME_RE = re.compile(r"^[\w\-ぁ-んァ-ヶ一-龠々ー]{1,64}$")


def profile_to_json(profile: Profile) -> str:
    return json.dumps(profile.to_dict(), ensure_ascii=False, indent=2)


def profile_from_json(text: str) -> Profile:
    """プロファイルJSONを読み込む。柔軟な形式を受け付ける:

    1. 完全なプロファイル形式 {"mapping": {"pairs": [...]}, ...}
    2. ペア配列のみ {"pairs": [...]} または [...]
    3. 単純な対応表 {"A列名": "B列名", ...}(外部ツール・AIが出力しやすい形式)
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise DiffDeskError(f"プロファイルのJSONが不正です: {e}")
    if isinstance(data, list):
        data = {"name": "imported", "mapping": {"pairs": data}}
    elif isinstance(data, dict) and "mapping" not in data:
        if isinstance(data.get("pairs"), list):
            data = {"name": str(data.get("name", "imported")),
                    "mapping": {"pairs": data["pairs"]}}
        elif data and all(isinstance(v, str) for v in data.values()):
            data = {"name": "imported", "mapping": {"pairs": [
                {"col_a": k, "col_b": v} for k, v in data.items()]}}
    return Profile.from_dict(data)


def _safe_path(name: str, directory: Path) -> Path:
    if not _NAME_RE.match(name):
        raise DiffDeskError(
            "プロファイル名には英数字・ひらがな・カタカナ・漢字・-・_ のみ使えます(64文字まで)。",
            name=name,
        )
    return directory / f"{name}.json"


def save_profile(profile: Profile, *, directory: Path | None = None) -> Path:
    directory = directory or DEFAULT_PROFILE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = _safe_path(profile.name, directory)
    path.write_text(profile_to_json(profile), encoding="utf-8")
    return path


def load_profile(name_or_path: str, *, directory: Path | None = None) -> Profile:
    directory = directory or DEFAULT_PROFILE_DIR
    p = Path(name_or_path)
    if p.suffix == ".json" and (p.is_absolute() or p.exists()):
        path = p
    else:
        path = _safe_path(name_or_path, directory)
    if not path.exists():
        raise DiffDeskError(f"プロファイルが見つかりません: {name_or_path}")
    return profile_from_json(path.read_text(encoding="utf-8"))


def list_profiles(*, directory: Path | None = None) -> list[str]:
    directory = directory or DEFAULT_PROFILE_DIR
    if not directory.exists():
        return []
    return sorted(p.stem for p in directory.glob("*.json"))


def delete_profile(name: str, *, directory: Path | None = None) -> None:
    directory = directory or DEFAULT_PROFILE_DIR
    path = _safe_path(name, directory)
    if path.exists():
        path.unlink()
