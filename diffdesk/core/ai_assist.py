"""Web版AI(コピペ)連携の拡張: 差異の仕分けプロンプト。

DiffDeskはAIに接続しない。プロンプト文字列の生成と、
貼り戻された回答テキストの解析だけを行う。
"""
from __future__ import annotations

import json

from .model import DiffDeskError, DiffResult

_MAX_TRIPLES = 200


def _extract_json_array(text: str):
    """テキストから最初の妥当なJSON配列を寛容に抽出する。"""
    start = text.find("[")
    data = None
    while start != -1 and data is None:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        pass
                    break
        if data is None:
            start = text.find("[", start + 1)
    return data


def distinct_changed_triples(diff: DiffResult, limit: int = _MAX_TRIPLES) -> list[dict]:
    """変更セルの (列, 値A, 値B) を件数付きで重複排除して返す(件数降順)。"""
    counts: dict[tuple[str, str, str], int] = {}
    for rd in diff.rows:
        if rd.status != "changed":
            continue
        for cd in rd.cell_diffs:
            key = (cd.col_a, cd.value_a, cd.value_b)
            counts[key] = counts.get(key, 0) + 1
    triples = [{"col": k[0], "value_a": k[1], "value_b": k[2], "count": n}
               for k, n in sorted(counts.items(), key=lambda kv: -kv[1])]
    return triples[:limit]


def build_known_prompt(diff: DiffResult, limit: int = _MAX_TRIPLES) -> dict:
    """差異の値の組を「容認できる差異か、真の相違か」仕分けさせるプロンプト。"""
    triples = distinct_changed_triples(diff, limit)
    if not triples:
        raise DiffDeskError("仕分け対象の差異(変更セル)がありません。")
    lines = ["番号\t列\t基準(A)の値\t比較(B)の値\t件数"]
    for i, t in enumerate(triples, 1):
        lines.append(f"{i}\t{t['col']}\t{t['value_a']}\t{t['value_b']}\t{t['count']}件")
    table = "\n".join(lines)
    prompt = f"""あなたはデータ移行のQA担当者です。移行元(A)と移行先(B)のデータ照合で見つかった差異の一覧です。
それぞれについて「システム移行時の仕様による変換・表記ゆれとして容認できる差異(known)」か
「データが本当に違う可能性がある差異(real)」かを判定してください。

# 差異一覧({len(triples)}種)
{table}

# 出力形式(この形式のJSON配列だけを出力。説明文は不要)
[{{"no": 番号, "verdict": "known" または "real", "reason": "判断理由を簡潔に"}}]

# 判断の目安
- 全角/半角・空白・大小文字・数値や日付の表記だけの違い → known
- コード値の体系的な変換(例: 男→Male、01→有効)と思われるもの → known
- 意味の異なる値・数値の桁違い・別人名など → real
- 迷う場合は real にする(安全側)"""
    return {"prompt": prompt, "count": len(triples), "triples": triples}


def parse_known_answer(diff: DiffResult, text: str,
                       limit: int = _MAX_TRIPLES) -> dict:
    """AI回答から known 判定の値の組を取り出す(実在する差異のみ)。

    返り値: {"candidates": [{col, value_a, value_b, count, reason}],
             "real": 件数, "rejected": [理由,...]}
    登録はしない(ユーザーが内容を確認して承認する)。
    """
    if not text or not text.strip():
        raise DiffDeskError("貼り付けられたテキストが空です。")
    data = _extract_json_array(text)
    if not isinstance(data, list):
        raise DiffDeskError(
            "JSON配列が見つかりませんでした。AIの回答全体をそのまま貼り付けてください。")
    triples = distinct_changed_triples(diff, limit)
    candidates, rejected = [], []
    real = 0
    seen: set[int] = set()
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            rejected.append(f"{i + 1}件目: 形式が不正です")
            continue
        try:
            no = int(item.get("no"))
        except (TypeError, ValueError):
            rejected.append(f"{i + 1}件目: 番号(no)がありません")
            continue
        if not (1 <= no <= len(triples)):
            rejected.append(f"{i + 1}件目: 番号 {no} は一覧にありません")
            continue
        if no in seen:
            rejected.append(f"{i + 1}件目: 番号 {no} が重複しています")
            continue
        seen.add(no)
        verdict = str(item.get("verdict", "")).strip().lower()
        if verdict == "real":
            real += 1
            continue
        if verdict != "known":
            rejected.append(f"{i + 1}件目: verdict は known / real で指定してください")
            continue
        t = triples[no - 1]
        candidates.append({**t, "reason": str(item.get("reason", ""))[:200]})
    return {"candidates": candidates, "real": real, "rejected": rejected}
