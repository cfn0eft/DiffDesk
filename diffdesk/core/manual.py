"""手動紐づけ: Aのみ行とBのみ行をユーザー操作でペアにする。

キーが一致しなかったレコード同士(例: 移行でIDが振り直された、キーの表記が
違う)を「同じレコード」として突き合わせたいときに使う。ペアにした行は
全列(キー列含む)を比較し、changed/same の通常行として扱われる。
元の DiffResult は変更せず、適用済みのコピーを返す。

正確性担保のための道具も持つ:
- pair_similarity: 2行の列ごとの類似度と合算スコア(紐づけ前の確認用)
- suggest_links: 未対応行同士のおすすめ候補(スコア順・1対1割当)
- build_link_prompt / parse_link_answer: Web版の対話AIに貼るプロンプトの生成と
  回答JSONの取り込み(ツール自体はAIを呼ばない。コピペ連携のみ)
"""
from __future__ import annotations

import json
from dataclasses import replace

from .fuzzy import _similarity
from .mapping_suggest import _canon_value
from .model import CellDiff, DiffDeskError, DiffResult, RowDiff
from .normalize import make_normalizer, values_equal


def validate_manual_pair(pair: dict) -> dict:
    """{"key_a": [...], "key_b": [...]} を検証して正規形にする。"""
    key_a = pair.get("key_a")
    key_b = pair.get("key_b")
    if (not isinstance(key_a, list) or not key_a
            or not all(isinstance(v, str) for v in key_a)):
        raise DiffDeskError("key_a は文字列のリストで指定してください。")
    if (not isinstance(key_b, list) or not key_b
            or not all(isinstance(v, str) for v in key_b)):
        raise DiffDeskError("key_b は文字列のリストで指定してください。")
    return {"key_a": list(key_a), "key_b": list(key_b)}


def apply_manual_pairs(diff: DiffResult, pairs: list[dict]) -> DiffResult:
    """手動ペアを適用したDiffResultのコピーを返す。

    各ペアの key_a に一致する only_a 行と key_b に一致する only_b 行を
    1件のペア行(manual=True)に統合する。該当行が見つからないペアは無視
    (差分の再実行で行が消えた場合など)。
    """
    if not pairs:
        return diff
    normalizer = make_normalizer(diff.options)
    cols_a = [p.col_a for p in diff.mapping.pairs]
    cols_b = [p.col_b for p in diff.mapping.pairs]

    by_key_a = {r.key: r for r in diff.rows if r.status == "only_a"}
    by_key_b = {r.key: r for r in diff.rows if r.status == "only_b"}
    merged: dict[tuple[str, ...], RowDiff] = {}  # key_a -> ペア行
    consumed_b: set[tuple[str, ...]] = set()

    for p in pairs:
        ka, kb = tuple(p["key_a"]), tuple(p["key_b"])
        ra, rb = by_key_a.get(ka), by_key_b.get(kb)
        if ra is None or rb is None or ka in merged or kb in consumed_b:
            continue
        cell_diffs = [
            CellDiff(col_a=cols_a[i], col_b=cols_b[i],
                     value_a=ra.row_a[i], value_b=rb.row_b[i])
            for i in range(len(cols_a))
            if not values_equal(ra.row_a[i], rb.row_b[i], normalizer,
                                diff.options.numeric_tolerance)
        ]
        merged[ka] = RowDiff(
            key=ka, status="changed" if cell_diffs else "same",
            row_a=ra.row_a, row_b=rb.row_b, cell_diffs=cell_diffs,
            manual=True, key_b=kb,
        )
        consumed_b.add(kb)

    if not merged:
        return diff

    rows: list[RowDiff] = []
    for r in diff.rows:
        if r.status == "only_a" and r.key in merged:
            rows.append(merged[r.key])
        elif r.status == "only_b" and r.key in consumed_b:
            continue
        else:
            rows.append(r)
    return replace(diff, rows=rows)


def _row_similarity(vals_a: list[str], vals_b: list[str]) -> tuple[float, list[float]]:
    """2行の正規化済み値リストの類似度(合算スコア, 列ごと)。両方空の列は分母から除外。"""
    details = []
    filled = []
    for x, y in zip(vals_a, vals_b):
        cx, cy = _canon_value(x), _canon_value(y)
        sim = _similarity(cx, cy)
        details.append(sim)
        if cx or cy:  # 両方空の列は判断材料にならないので分母から除外
            filled.append(sim)
    score = sum(filled) / len(filled) if filled else 0.0
    return score, details


def pair_similarity(diff: DiffResult, key_a: list[str], key_b: list[str]) -> dict:
    """未対応行ペアの列ごとの類似度(紐づけ確認ダイアログ用)。

    キー列も含めて全列を比較する。返り値:
    {"columns": [{col_a, col_b, value_a, value_b, sim}], "score": 0-1,
     "matched": 類似度1.0の列数, "total": 比較列数(両方空を除く)}
    """
    ra = next((r for r in diff.rows
               if r.status == "only_a" and r.key == tuple(key_a)), None)
    rb = next((r for r in diff.rows
               if r.status == "only_b" and r.key == tuple(key_b)), None)
    if ra is None or rb is None:
        raise DiffDeskError("指定された未対応行が見つかりません(差分を再実行した場合は選び直してください)。")
    score, details = _row_similarity(ra.row_a, rb.row_b)
    columns = []
    matched = total = 0
    for i, p in enumerate(diff.mapping.pairs):
        va, vb = ra.row_a[i], rb.row_b[i]
        sim = details[i]
        if _canon_value(va) or _canon_value(vb):
            total += 1
            if sim >= 0.999:
                matched += 1
        columns.append({"col_a": p.col_a, "col_b": p.col_b,
                        "value_a": va, "value_b": vb, "sim": round(sim, 3)})
    return {"columns": columns, "score": round(score, 3),
            "matched": matched, "total": total}


_SUGGEST_MAX_PAIRS = 250_000  # 総当たり比較の上限(超えたらブロッキング)


def suggest_links(diff: DiffResult, threshold: float = 0.5,
                  limit: int = 50) -> list[dict]:
    """未対応の only_a × only_b からおすすめ紐づけ候補を返す(スコア順・1対1)。"""
    rows_a = [r for r in diff.rows if r.status == "only_a" and not r.known]
    rows_b = [r for r in diff.rows if r.status == "only_b" and not r.known]
    if not rows_a or not rows_b:
        return []
    key_flags = [p.is_key for p in diff.mapping.pairs]

    def preview(vals):
        vs = [v for f, v in zip(key_flags, vals) if not f and v][:2]
        return "、".join(x[:20] for x in vs)

    # 組合せが多すぎる場合は先頭の値列の1文字でブロッキング(fuzzy.pyと同じ発想)
    use_block = len(rows_a) * len(rows_b) > _SUGGEST_MAX_PAIRS
    first_val_idx = next((i for i, f in enumerate(key_flags) if not f), 0)
    blocks: dict[str, list[int]] = {}
    if use_block:
        for j, rb in enumerate(rows_b):
            blocks.setdefault(_canon_value(rb.row_b[first_val_idx])[:1], []).append(j)

    scored = []
    for i, ra in enumerate(rows_a):
        targets = (blocks.get(_canon_value(ra.row_a[first_val_idx])[:1], ())
                   if use_block else range(len(rows_b)))
        for j in targets:
            rb = rows_b[j]
            score, _ = _row_similarity(ra.row_a, rb.row_b)
            if score >= threshold:
                scored.append((score, i, j))

    scored.sort(key=lambda t: -t[0])
    used_a: set[int] = set()
    used_b: set[int] = set()
    out = []
    for score, i, j in scored:
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        ra, rb = rows_a[i], rows_b[j]
        out.append({"key_a": list(ra.key), "key_b": list(rb.key),
                    "score": round(score, 3),
                    "label_a": " / ".join(ra.key) + (" | " + preview(ra.row_a) if preview(ra.row_a) else ""),
                    "label_b": " / ".join(rb.key) + (" | " + preview(rb.row_b) if preview(rb.row_b) else "")})
        if len(out) >= limit:
            break
    return out


def build_link_prompt(diff: DiffResult, limit: int = 100) -> dict:
    """Web版の対話AI(Gemini等)に貼り付ける紐づけ判定プロンプトを生成する。

    ツールはAIを呼ばない。生成した文字列をユーザーがブラウザで貼り付け、
    返ってきたJSONを parse_link_answer で取り込む。
    """
    rows_a = [r for r in diff.rows if r.status == "only_a" and not r.known][:limit]
    rows_b = [r for r in diff.rows if r.status == "only_b" and not r.known][:limit]
    if not rows_a or not rows_b:
        raise DiffDeskError("紐づけ対象の未対応行がありません(Aのみ/Bのみの両方が必要です)。")
    cols_a = [p.col_a for p in diff.mapping.pairs]
    cols_b = [p.col_b for p in diff.mapping.pairs]

    def tsv(rows, side):
        cols = cols_a if side == "a" else cols_b
        lines = ["キー\t" + "\t".join(cols)]
        for r in rows:
            vals = r.row_a if side == "a" else r.row_b
            lines.append("/".join(r.key) + "\t" + "\t".join(vals))
        return "\n".join(lines)

    prompt = f"""あなたはデータ照合の専門家です。2つの表があり、表Aの各行に対応すると思われる行を表Bから探してください。
キー(ID)は振り直されている可能性があるため、キー以外の値(氏名・日付・数値など)の内容で判断してください。

# 表A(基準・未対応 {len(rows_a)}行)
{tsv(rows_a, "a")}

# 表B(比較・未対応 {len(rows_b)}行)
{tsv(rows_b, "b")}

# 出力形式(この形式のJSON配列だけを出力。説明文は不要)
[{{"key_a": ["表Aのキー"], "key_b": ["表Bのキー"], "confidence": 0.0〜1.0, "reason": "判断理由を簡潔に"}}]

# ルール
- 対応が確実または有力な組だけを出力する(無理にすべての行を対応させない)
- 1行は最大1回しか使わない(1対1)
- キーが複合キー(スラッシュ区切り)の場合は "/" で分割した配列にする"""
    return {"prompt": prompt, "rows_a": len(rows_a), "rows_b": len(rows_b)}


def parse_link_answer(diff: DiffResult, text: str) -> dict:
    """AI回答テキストからJSON配列を寛容に抽出し、実在する未対応行の組だけ返す。

    返り値: {"pairs": [{key_a, key_b, score(=confidence), reason}], "rejected": ["理由", ...]}
    """
    if not text or not text.strip():
        raise DiffDeskError("貼り付けられたテキストが空です。")
    # コードフェンスや前後の文を無視して最初のJSON配列を探す
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
    if not isinstance(data, list):
        raise DiffDeskError(
            "JSON配列が見つかりませんでした。AIの回答全体をそのまま貼り付けてください。")

    keys_a = {r.key for r in diff.rows if r.status == "only_a" and not r.known}
    keys_b = {r.key for r in diff.rows if r.status == "only_b" and not r.known}
    pairs, rejected = [], []
    seen_a, seen_b = set(), set()
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            rejected.append(f"{i + 1}件目: 形式が不正です")
            continue
        ka = item.get("key_a")
        kb = item.get("key_b")
        if isinstance(ka, str):
            ka = ka.split("/")
        if isinstance(kb, str):
            kb = kb.split("/")
        try:
            norm = validate_manual_pair({"key_a": ka, "key_b": kb})
        except DiffDeskError:
            rejected.append(f"{i + 1}件目: キーの形式が不正です")
            continue
        ta, tb = tuple(norm["key_a"]), tuple(norm["key_b"])
        if ta not in keys_a:
            rejected.append(f"{i + 1}件目: 基準(A)に未対応キー {'/'.join(ta)} がありません")
            continue
        if tb not in keys_b:
            rejected.append(f"{i + 1}件目: 比較(B)に未対応キー {'/'.join(tb)} がありません")
            continue
        if ta in seen_a or tb in seen_b:
            rejected.append(f"{i + 1}件目: {'/'.join(ta)} または {'/'.join(tb)} が重複しています")
            continue
        seen_a.add(ta)
        seen_b.add(tb)
        conf = item.get("confidence")
        score = round(float(conf), 3) if isinstance(conf, (int, float)) else None
        pairs.append({"key_a": norm["key_a"], "key_b": norm["key_b"],
                      "score": score,
                      "reason": str(item.get("reason", ""))[:200]})
    return {"pairs": pairs, "rejected": rejected}


def list_unmatched(diff: DiffResult, side: str, limit: int = 1000,
                   rank_for: list[str] | None = None) -> list[dict]:
    """紐づけ相手の候補(未対応の only_a / only_b 行)を返す。

    side="a" なら only_a 行、side="b" なら only_b 行。既知(容認済み)の行は除く。
    各要素は {"key": [...], "label": "キー | 先頭の値…"}。

    rank_for に反対側の未対応行のキーを渡すと、その行との類似度を score として
    付与し一致率の高い順に並べ替える(詳細画面の「相手を選んで紐づけ」用)。
    """
    if side not in ("a", "b"):
        raise DiffDeskError("side は a または b を指定してください。")
    status = f"only_{side}"
    key_flags = [p.is_key for p in diff.mapping.pairs]
    base_vals = None
    if rank_for is not None:
        opp = "only_b" if side == "a" else "only_a"
        base = next((r for r in diff.rows
                     if r.status == opp and r.key == tuple(rank_for)), None)
        if base is not None:
            base_vals = base.row_a if opp == "only_a" else base.row_b
    out = []
    for r in diff.rows:
        if r.status != status or r.known:
            continue
        vals = r.row_a if side == "a" else r.row_b
        preview = [v for f, v in zip(key_flags, vals) if not f and v][:2]
        label = " / ".join(r.key)
        if preview:
            label += " | " + "、".join(x[:20] for x in preview)
        entry = {"key": list(r.key), "label": label}
        if base_vals is not None:
            score, _ = _row_similarity(base_vals, vals) if side == "b" \
                else _row_similarity(vals, base_vals)
            entry["score"] = round(score, 3)
        out.append(entry)
        if len(out) >= limit:
            break
    if base_vals is not None:
        out.sort(key=lambda e: -e.get("score", 0))
    return out
