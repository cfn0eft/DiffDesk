"""自己完結HTML照合レポート(単一ファイル・依存なし・フィルタ内蔵)。

メール添付やチャット共有向け。受け取った人はブラウザで開くだけで、
判定・進捗バー・列別の差異ランキング・変更セルの「旧 → 新」表示つきの
照合結果を閲覧できる(状態フィルタ・検索・印刷対応)。
"""
from __future__ import annotations

import html
import json
from datetime import datetime

from .known import column_diff_summary
from .model import DiffResult
from .verify import build_verification

_MAX_ROWS = 50_000


def _build_row_data(diff: DiffResult) -> list[dict]:
    """行ごとの表示データ。変更セルは [旧, 新]、既知セルは [旧, 新, "k"]。"""
    rows = []
    for rd in diff.rows[:_MAX_ROWS]:
        changed = {cd.col_a: cd for cd in rd.cell_diffs}
        known = {cd.col_a: cd for cd in rd.known_diffs}
        cells = []
        for i, p in enumerate(diff.mapping.pairs):
            va = rd.row_a[i] if rd.row_a else ""
            vb = rd.row_b[i] if rd.row_b else ""
            if p.col_a in changed:
                cd = changed[p.col_a]
                cells.append([cd.value_a, cd.value_b])
            elif p.col_a in known:
                kd = known[p.col_a]
                cells.append([kd.value_a, kd.value_b, "k"])
            else:
                cells.append(va if rd.row_a else vb)
        rows.append({
            "st": rd.status,
            "key": " / ".join(rd.key),
            "known": rd.known,
            "manual": rd.manual,
            "cells": cells,
        })
    return rows


def build_html_report(diff: DiffResult, *, only_b_is_error: bool = True) -> str:
    v = build_verification(diff, only_b_is_error=only_b_is_error)
    s = diff.summary
    total_rows = len(diff.rows)
    truncated = total_rows > _MAX_ROWS
    colsum = column_diff_summary(diff)
    max_colcount = max((c["count"] for c in colsum), default=1)

    columns = []
    for p in diff.mapping.pairs:
        label = p.col_a if p.col_a == p.col_b else f"{p.col_a} / {p.col_b}"
        columns.append({"label": label, "key": p.is_key})
    data = {"columns": columns, "rows": _build_row_data(diff)}

    match_rate = (v.same / v.rows_a * 100) if v.rows_a else 0.0
    pct_ok = (v.same / v.rows_a * 100) if v.rows_a else 0
    pct_ng = (v.changed / v.rows_a * 100) if v.rows_a else 0
    pct_miss = (v.only_a / v.rows_a * 100) if v.rows_a else 0

    verdict_class = "ok" if v.passed else "ng"
    verdict_text = ("✔ 照合OK — 件数・内容ともに期待どおりです" if v.passed
                    else "✖ 要確認 — 差異があります(下の内訳と明細を確認)")
    problems = "".join(
        f'<li class="{"allow" if p.startswith("(許容)") or p.startswith("(既知)") else "issue"}">'
        f"{html.escape(p)}</li>"
        for p in v.problems) or '<li class="allow">指摘事項はありません。</li>'

    cards = [
        ("基準 (A)", v.rows_a, "件", ""),
        ("比較 (B)", v.rows_b, "件", ""),
        ("完全一致", v.same, f"件 ({match_rate:.1f}%)", "c-ok"),
        ("値差異", v.changed, "件", "c-ng" if v.changed else ""),
        ("未投入 (Aのみ)", v.only_a, "件", "c-miss" if v.only_a else ""),
        ("想定外 (Bのみ)", v.only_b, "件", "c-ng" if v.only_b else ""),
    ]
    if v.known_rows or v.known_cells:
        cards.append(("既知 (容認済み)", v.known_rows + v.known_cells, "件", "c-known"))
    cards_html = "".join(
        f'<div class="card {cls}"><div class="num">{n}</div>'
        f'<div class="lab">{html.escape(label)} <span>{unit}</span></div></div>'
        for label, n, unit, cls in cards)

    colsum_html = "".join(
        f'<div class="colrow"><span class="colname">{html.escape(c["column"])}</span>'
        f'<span class="colbar"><i style="width:{c["count"] / max_colcount * 100:.0f}%"></i></span>'
        f'<b>{c["count"]}</b></div>'
        for c in colsum[:10]) or '<p class="dim">値差異はありません。</p>'

    norms = []
    if diff.options.trim:
        norms.append("空白除去")
    if diff.options.normalize_width:
        norms.append("全半角同一視")
    if diff.options.normalize_numeric:
        norms.append("数値同一視")
    if diff.options.ignore_case:
        norms.append("大小文字同一視")
    if diff.options.numeric_tolerance is not None:
        norms.append(f"許容誤差{diff.options.numeric_tolerance}")
    keys = " + ".join(p.col_a for p in diff.mapping.pairs if p.is_key)
    from .. import __version__
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>照合レポート — {html.escape(diff.name_a)} ⇔ {html.escape(diff.name_b)}</title>
<style>
:root{{--accent:#3d4a41;--border:#b7b2a6;--ok:#2c5e2c;--ng:#a33c34;--miss:#8a5a20}}
*{{box-sizing:border-box}}
body{{font-family:"Yu Gothic UI","Hiragino Sans","Noto Sans JP",sans-serif;font-size:13px;margin:0;background:#ece9e2;color:#222}}
header{{background:var(--accent);color:#fff;padding:10px 16px;display:flex;gap:14px;align-items:baseline;flex-wrap:wrap}}
header .t{{font-size:16px;font-weight:700}}
header .files{{opacity:.9}}
header .when{{margin-left:auto;font-size:11px;opacity:.75}}
main{{padding:14px;max-width:1500px;margin:0 auto}}
.verdict{{padding:12px 16px;font-size:17px;font-weight:700;border:1px solid;margin-bottom:12px}}
.verdict.ok{{background:#d9edd5;border-color:#4e8a47;color:#1f4a1b}}
.verdict.ng{{background:#f4d9d5;border-color:#b05248;color:#6d241b}}
.progress{{display:flex;height:18px;border:1px solid var(--border);background:#fff;overflow:hidden;margin-bottom:4px}}
.progress .p-ok{{background:#5a9a52}}.progress .p-ng{{background:#e0b93d}}.progress .p-miss{{background:#c05a4e}}
.progress-label{{font-size:12px;color:#555;margin-bottom:12px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin-bottom:12px}}
.card{{background:#f7f5f0;border:1px solid var(--border);padding:8px 12px}}
.card .num{{font-size:22px;font-weight:700}}
.card .lab{{font-size:11px;color:#666}}
.card.c-ok .num{{color:var(--ok)}}.card.c-ng .num{{color:var(--ng)}}
.card.c-miss .num{{color:var(--miss)}}.card.c-known .num{{color:#777}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}}
@media(max-width:900px){{.two{{grid-template-columns:1fr}}}}
.panel{{background:#f7f5f0;border:1px solid var(--border);padding:10px 12px}}
.panel h2{{margin:0 0 8px;font-size:13px;border-bottom:1px solid var(--border);padding-bottom:4px}}
.panel ul{{margin:0;padding-left:20px}}
.panel li{{margin:2px 0}}
li.issue{{color:#6d241b}}
li.allow{{color:#555}}
.colrow{{display:flex;gap:8px;align-items:center;margin:3px 0}}
.colname{{width:36%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.colbar{{flex:1;height:12px;background:#fff;border:1px solid var(--border)}}
.colbar i{{display:block;height:100%;background:#e0b93d}}
.dim{{color:#888}}
.bar{{display:flex;gap:8px;align-items:center;margin:10px 0 8px;flex-wrap:wrap}}
button{{border:1px solid #7a766c;background:#e8e5dd;padding:4px 12px;cursor:pointer;font-size:12px}}
button.on{{background:var(--accent);color:#fff}}
input{{border:1px solid #948f83;padding:4px 8px;font-size:12px}}
table{{border-collapse:collapse;width:100%;background:#fff;font-size:12px}}
th,td{{border:1px solid #d4d0c6;padding:3px 8px;text-align:left;white-space:nowrap;max-width:380px;overflow:hidden;text-overflow:ellipsis}}
th{{background:#d8d4c9;position:sticky;top:0;z-index:1}}
td.st{{font-weight:700;white-space:nowrap}}
tr.r-only_a td.st{{color:var(--miss)}}
tr.r-only_b td.st{{color:var(--ng)}}
tr.r-changed td.st{{color:#8a6d1a}}
tr.r-only_a td{{background:#f2ead9}}
tr.r-only_b td{{background:#f4d9d5}}
tr.r-changed td{{background:#fbf6e2}}
tr.r-known td{{background:#eceae4;color:#777}}
.diffcell{{background:#ffe9a8 !important}}
.old{{color:#8a2d25;text-decoration:line-through}}
.new{{color:#1f4a1b;font-weight:700}}
.kmark{{color:#888;font-size:11px}}
.wrap{{overflow:auto;max-height:72vh;border:1px solid var(--border)}}
.legend{{font-size:11px;color:#666;margin:6px 0}}
.legend i{{display:inline-block;width:10px;height:10px;margin:0 3px 0 10px;vertical-align:-1px;border:1px solid #999}}
footer{{padding:10px 16px;color:#6d675c;font-size:11px;display:flex;gap:16px;flex-wrap:wrap}}
@media print{{.bar,.wrap{{max-height:none;overflow:visible}}button,input{{display:none}}header .when{{display:block}}}}
</style></head><body>
<header><span class="t">DiffDesk 照合レポート</span>
<span class="files">{html.escape(diff.name_a)} ⇔ {html.escape(diff.name_b)}</span>
<span class="when">生成: {generated} / DiffDesk v{__version__}</span></header>
<main>
<div class="verdict {verdict_class}">{verdict_text}</div>
<div class="progress"><div class="p-ok" style="width:{pct_ok:.1f}%"></div>
<div class="p-ng" style="width:{pct_ng:.1f}%"></div>
<div class="p-miss" style="width:{pct_miss:.1f}%"></div></div>
<div class="progress-label"><b>{v.rows_a}レコード中 {v.same}件</b> が正しく登録済み({match_rate:.1f}%)
{f" — 値の相違 {v.changed}件" if v.changed else ""}{f" — 未投入 {v.only_a}件" if v.only_a else ""}</div>
<div class="cards">{cards_html}</div>
<div class="two">
<div class="panel"><h2>指摘事項</h2><ul>{problems}</ul></div>
<div class="panel"><h2>差異の多い項目(上位10)</h2>{colsum_html}</div>
</div>
<div class="bar">
<span>表示:</span>
<button class="f on" data-f="problem">要確認のみ</button>
<button class="f" data-f="">全て</button>
<button class="f" data-f="changed">変更</button>
<button class="f" data-f="only_a">Aのみ</button>
<button class="f" data-f="only_b">Bのみ</button>
<button class="f" data-f="same">一致</button>
<input id="q" placeholder="検索(全列部分一致)" size="28">
<span id="count"></span>
</div>
<div class="legend">凡例: 変更セルは <span class="old">旧値</span> → <span class="new">新値</span>。
背景 <i style="background:#fbf6e2"></i>変更 <i style="background:#f2ead9"></i>Aのみ(未投入)
<i style="background:#f4d9d5"></i>Bのみ(想定外) <i style="background:#eceae4"></i>既知(容認済み)</div>
<div class="wrap"><table id="t"><thead></thead><tbody></tbody></table></div>
{"<p>※ 明細は先頭" + format(_MAX_ROWS, ",") + "行までです(全" + format(total_rows, ",") + "行)。</p>" if truncated else ""}
</main>
<footer><span>キー: {html.escape(keys)}</span>
<span>正規化: {html.escape("・".join(norms) or "なし")}</span>
<span>A: {v.rows_a}件 / B: {v.rows_b}件</span>
<span>Generated by DiffDesk v{__version__}</span></footer>
<script>
const DATA = {json.dumps(data, ensure_ascii=False)};
const ST_JA = {{only_a: "Aのみ", only_b: "Bのみ", changed: "変更", same: "一致"}};
let filter = "problem", q = "";
const esc = s => String(s).replace(/[&<>"]/g, c => ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}})[c]);
document.querySelector("#t thead").innerHTML =
  "<tr><th>状態</th><th>キー</th>" +
  DATA.columns.map(c => "<th>" + (c.key ? "🔑 " : "") + esc(c.label) + "</th>").join("") + "</tr>";
function cellHtml(c) {{
  if (Array.isArray(c)) {{
    const known = c[2] === "k";
    return "<td class='" + (known ? "" : "diffcell") + "'>" +
      "<span class='old'>" + esc(c[0]) + "</span> → <span class='new'>" + esc(c[1]) + "</span>" +
      (known ? " <span class='kmark'>(既知)</span>" : "") + "</td>";
  }}
  return "<td>" + esc(c) + "</td>";
}}
function rowText(r) {{
  return (r.key + " " + r.cells.map(c => Array.isArray(c) ? c[0] + " " + c[1] : c).join(" ")).toLowerCase();
}}
function render() {{
  const ql = q.toLowerCase();
  const rows = DATA.rows.filter(r =>
    (filter === "" ||
     (filter === "problem" ? (r.st !== "same" && !r.known) : r.st === filter)) &&
    (!ql || rowText(r).includes(ql)));
  document.querySelector("#t tbody").innerHTML = rows.slice(0, 2000).map(r =>
    "<tr class='r-" + r.st + (r.known ? " r-known" : "") + "'>" +
    "<td class='st'>" + (r.known ? "既知" : ST_JA[r.st]) + (r.manual ? " ⇔" : "") + "</td>" +
    "<td>" + esc(r.key) + "</td>" +
    r.cells.map(cellHtml).join("") + "</tr>").join("");
  document.querySelector("#count").textContent =
    rows.length + "件" + (rows.length > 2000 ? "(先頭2000件を表示)" : "");
}}
document.querySelectorAll(".f").forEach(b => b.onclick = () => {{
  filter = b.dataset.f;
  document.querySelectorAll(".f").forEach(x => x.classList.toggle("on", x === b));
  render();
}});
document.querySelector("#q").oninput = e => {{ q = e.target.value; render(); }};
render();
</script>
</body></html>"""
