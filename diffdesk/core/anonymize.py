"""データ匿名化(sandbox・テスト環境への投入用マスキング)。

同じ入力値には同じダミー値を割り当てる(参照整合性を保つ)。
"""
from __future__ import annotations

from .model import DiffDeskError, Table

ANONYMIZE_MODES: dict[str, str] = {
    "name": "氏名(氏名00001 形式)",
    "company": "会社名(サンプル株式会社1 形式)",
    "email": "メール(user00001@example.com)",
    "phone": "電話番号(090-0000-0001 形式)",
    "text": "汎用テキスト(サンプル00001)",
    "number": "連番(1, 2, 3, ...)",
    "blank": "空欄にする",
}


def _fake(mode: str, n: int) -> str:
    if mode == "name":
        return f"氏名{n:05d}"
    if mode == "company":
        return f"サンプル株式会社{n}"
    if mode == "email":
        return f"user{n:05d}@example.com"
    if mode == "phone":
        return f"090-{n // 10000:04d}-{n % 10000:04d}"
    if mode == "text":
        return f"サンプル{n:05d}"
    if mode == "number":
        return str(n)
    if mode == "blank":
        return ""
    raise DiffDeskError(f"不明な匿名化モードです: {mode}", mode=mode)


def anonymize_columns(table: Table, spec: dict[str, str]) -> tuple[Table, int]:
    """指定列を匿名化した新しいTableと、変更セル数を返す。

    spec: {列名: モード}。空セルは空のまま。同じ値には同じダミー値を割り当てる。
    """
    for mode in spec.values():
        if mode not in ANONYMIZE_MODES:
            raise DiffDeskError(f"不明な匿名化モードです: {mode}", mode=mode)
    out = table.copy()
    out.name = f"{table.name or 'データ'}(匿名化)"
    changed = 0
    for column, mode in spec.items():
        i = out.col_index(column)
        mapping: dict[str, str] = {}
        for row in out.rows:
            v = row[i]
            if not v.strip():
                continue
            if v not in mapping:
                mapping[v] = _fake(mode, len(mapping) + 1)
            if row[i] != mapping[v]:
                row[i] = mapping[v]
                changed += 1
    return out, changed
