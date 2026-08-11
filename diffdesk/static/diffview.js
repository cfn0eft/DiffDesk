// 差分結果の表示、マージ選択、エクスポート
import {
  $, $$, api, downloadResponse, escapeHtml, postJson, showDialog, state, toast,
} from "/static/common.js";

const PAGE_SIZE = 200;
let currentStatus = "";
let currentOffset = 0;
let currentTotal = 0;

const STATUS_JA = { only_a: "Aのみ", only_b: "Bのみ", changed: "変更", same: "一致" };

export function renderDiff() {
  const d = state.diff;
  $("#diff-empty").hidden = !!d;
  $("#diff-body").hidden = !d;
  if (!d) return;
  const s = d.summary;
  $("#summary-cards").innerHTML = [
    ["only_a", "Aのみ (insert候補)"], ["changed", "変更 (update候補)"],
    ["only_b", "Bのみ"], ["same", "一致"],
  ].map(([k, label]) =>
    `<div class="stat ${k}"><div class="num">${s[k]}</div><div class="hint">${label}</div></div>`
  ).join("");

  // フィルタボタンに件数を表示
  const total = s.only_a + s.only_b + s.changed + s.same;
  const labels = { "": ["全て", total], only_a: ["Aのみ", s.only_a],
                   only_b: ["Bのみ", s.only_b], changed: ["変更", s.changed],
                   same: ["一致", s.same] };
  $$(".statusfilter").forEach(b => {
    const [name, count] = labels[b.dataset.status];
    b.textContent = `${name} (${count})`;
  });

  const warnings = [];
  if (s.duplicates_a) warnings.push(`ファイルAにキー重複が${s.duplicates_a}件あります(照合対象外)。例: ${d.duplicates_a.slice(0, 5).map(k => k.join("/")).join(", ")}`);
  if (s.duplicates_b) warnings.push(`ファイルBにキー重複が${s.duplicates_b}件あります(照合対象外)。例: ${d.duplicates_b.slice(0, 5).map(k => k.join("/")).join(", ")}`);
  if (s.empty_key_a) warnings.push(`ファイルAにキーが空の行が${s.empty_key_a}行あります(照合対象外)。`);
  if (s.empty_key_b) warnings.push(`ファイルBにキーが空の行が${s.empty_key_b}行あります(照合対象外)。`);
  $("#diff-warnings").innerHTML = warnings.map(w =>
    `<div class="card"><span class="badge warn">警告</span> ${escapeHtml(w)}</div>`).join("");

  currentStatus = "";
  currentOffset = 0;
  $$(".statusfilter").forEach(b =>
    b.classList.toggle("active", b.dataset.status === ""));
  renderStatusbar();
  loadVerification();
  loadColumnsSummary();
  loadHistory();
  loadKnownList();
  loadRows();
}

// ---------------------------------------------------------------- 列ごとの差異サマリー
async function loadColumnsSummary() {
  const d = state.diff;
  if (!d) return;
  try {
    const r = await (await api(`/api/diff/${d.diff_id}/columns-summary`)).json();
    if (!r.columns.length) {
      $("#columns-summary").innerHTML = "";
      return;
    }
    $("#columns-summary").innerHTML =
      `<span class="hint">差異の多い項目:</span> ` +
      r.columns.map(c =>
        `<button class="mini colsum" title="クリックで変更行のみ表示">${escapeHtml(c.column)} (${c.count})</button>`
      ).join(" ");
    $$("#columns-summary .colsum").forEach(b => b.onclick = () => {
      currentStatus = "changed";
      currentOffset = 0;
      $$(".statusfilter").forEach(x =>
        x.classList.toggle("active", x.dataset.status === "changed"));
      loadRows();
    });
  } catch { /* 表示のみなので無視 */ }
}

// ---------------------------------------------------------------- 照合履歴
async function loadHistory() {
  try {
    const r = await (await api("/api/history?limit=30")).json();
    if (!r.history.length) {
      $("#history-list").innerHTML = `<p class="hint">まだ履歴がありません。</p>`;
      return;
    }
    $("#history-list").innerHTML =
      `<table><thead><tr><th>日時</th><th>基準(A)</th><th>比較(B)</th>` +
      `<th>一致率</th><th>変更</th><th>未登録</th><th>判定</th></tr></thead><tbody>` +
      r.history.map(h => {
        const pct = (h.match_rate * 100).toFixed(1);
        return `<tr><td>${escapeHtml(h.at)}</td><td>${escapeHtml(h.name_a)}</td>` +
          `<td>${escapeHtml(h.name_b)}</td>` +
          `<td><div class="trendbar"><div style="width:${pct}%"></div></div> ${pct}%</td>` +
          `<td>${h.changed}</td><td>${h.only_a}</td>` +
          `<td>${h.passed ? "✔" : "✖"}</td></tr>`;
      }).join("") + `</tbody></table>`;
  } catch { /* 無視 */ }
}
$("#history-refresh").onclick = loadHistory;
$("#history-clear").onclick = async () => {
  await api("/api/history", { method: "DELETE" });
  loadHistory();
  toast("照合履歴を削除しました");
};

// ---------------------------------------------------------------- 既知差分の管理
async function loadKnownList() {
  try {
    const r = await (await api("/api/known-diffs")).json();
    if (!r.entries.length) {
      $("#known-list").innerHTML = `<p class="hint">登録済みの既知差分はありません。</p>`;
      return;
    }
    $("#known-list").innerHTML =
      `<table><thead><tr><th>種類</th><th>キー</th><th>内容</th><th>登録日</th><th></th></tr></thead><tbody>` +
      r.entries.map((e, i) => {
        const desc = e.type === "cell"
          ? `${escapeHtml(e.col_a)}: ${escapeHtml(e.value_a)} → ${escapeHtml(e.value_b)}`
          : (e.status === "only_a" ? "比較先に無い(未登録を容認)" : "基準に無い(存在を容認)");
        return `<tr><td>${e.type === "cell" ? "セル差分" : "欠落"}</td>` +
          `<td>${escapeHtml(e.key.join("/"))}</td><td>${desc}</td>` +
          `<td class="hint">${escapeHtml(e.added_at || "")}</td>` +
          `<td><button class="mini danger known-del" data-i="${i}">削除</button></td></tr>`;
      }).join("") + `</tbody></table>`;
    $$(".known-del").forEach(b => b.onclick = async () => {
      await api(`/api/known-diffs/${b.dataset.i}`, { method: "DELETE" });
      refreshAfterKnownChange();
    });
  } catch (e) { toast(e.message, true); }
}
$("#known-refresh").onclick = loadKnownList;
$("#known-clear-all").onclick = async () => {
  await api("/api/known-diffs", { method: "DELETE" });
  refreshAfterKnownChange();
  toast("既知差分を全て削除しました");
};

function refreshAfterKnownChange() {
  loadKnownList();
  if (state.diff) {
    loadVerification();
    loadColumnsSummary();
    loadRows();
  }
}

async function registerKnown(entry) {
  try {
    await postJson("/api/known-diffs", { entry });
    toast("既知差分として登録しました。以後の照合では問題に数えません。");
    $("#dialog").close();
    refreshAfterKnownChange();
  } catch (e) { toast(e.message, true); }
}

// ---------------------------------------------------------------- 差分ジャンプ
let jumpIndex = -1;

function jumpTo(delta) {
  const lists = viewMode === "split"
    ? SPLIT_TABLES.map(sel => $$(sel + " tbody tr"))
    : [$$("#diff-table tbody tr")];
  const problems = [];
  lists[0].forEach((tr, i) => {
    const r = currentRows[+tr.dataset.ri];
    if (r && r.status !== "same" && !r.known) problems.push(i);
  });
  if (!problems.length) return toast("このページに要確認行はありません");
  const pos = problems.indexOf(jumpIndex);
  let next;
  if (pos === -1) next = delta > 0 ? problems[0] : problems[problems.length - 1];
  else next = problems[(pos + delta + problems.length) % problems.length];
  jumpIndex = next;
  lists.forEach(trs => {
    trs.forEach(tr => tr.classList.remove("jump-current"));
    if (trs[next]) trs[next].classList.add("jump-current");
  });
  lists[0][next].scrollIntoView({ block: "center", behavior: "smooth" });
}

$("#jump-next").onclick = () => jumpTo(1);
$("#jump-prev").onclick = () => jumpTo(-1);
document.addEventListener("keydown", e => {
  if (!$("#tab-diff").classList.contains("active")) return;
  if ($("#dialog").open) return;
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT" || e.target.tagName === "TEXTAREA") return;
  if (e.key === "n") jumpTo(1);
  if (e.key === "p") jumpTo(-1);
});

// ---------------------------------------------------------------- 投入検証
async function loadVerification() {
  const d = state.diff;
  if (!d) return;
  const allowB = $("#verify-allow-b").checked;
  try {
    const v = await (await api(
      `/api/diff/${d.diff_id}/verify?only_b_is_error=${!allowB}`)).json();
    const banner = $("#verify-banner");
    banner.className = v.passed ? "ok" : "ng";
    banner.textContent = v.passed
      ? "✔ 照合OK — 件数・内容ともに一致しています"
      : "✖ 要確認 — 差異があります";
    // 進捗バー: 基準(A)のうち正しく登録されている割合
    const okCount = v.same;
    const pct = v.rows_a ? (okCount / v.rows_a) * 100 : 0;
    $("#verify-progress").innerHTML =
      `<div class="progress-label"><b>${v.rows_a}レコード中 ${okCount}件</b> が正しく登録済み` +
      `(${pct.toFixed(1)}%)${v.only_a ? ` — 未登録 ${v.only_a}件` : ""}` +
      `${v.changed ? ` — 値の相違 ${v.changed}件` : ""}</div>` +
      `<div class="progress"><div class="p-ok" style="width:${pct}%"></div>` +
      `<div class="p-ng" style="width:${v.rows_a ? (v.changed / v.rows_a) * 100 : 0}%"></div>` +
      `<div class="p-miss" style="width:${v.rows_a ? (v.only_a / v.rows_a) * 100 : 0}%"></div></div>`;
    $("#verify-counts").innerHTML =
      `<span>投入元(A): <b>${v.rows_a}</b>件</span>` +
      `<span>Salesforce(B): <b>${v.rows_b}</b>件</span>` +
      `<span>キー一致: <b>${v.matched}</b>件</span>` +
      `<span>完全一致: <b>${v.same}</b>件 (${(v.match_rate * 100).toFixed(1)}%)</span>` +
      `<span>値差異: <b>${v.changed}</b></span>` +
      `<span>未投入(Aのみ): <b>${v.only_a}</b></span>` +
      `<span>想定外(Bのみ): <b>${v.only_b}</b></span>` +
      (v.unmatchable_a + v.unmatchable_b
        ? `<span>照合不能: <b>${v.unmatchable_a + v.unmatchable_b}</b></span>` : "");
    $("#verify-problems").innerHTML = v.problems.map(p =>
      `<div class="${p.startsWith("(許容)") ? "allowed" : "issue"}">・${escapeHtml(p)}</div>`
    ).join("");
  } catch (e) { toast(e.message, true); }
}

$("#verify-allow-b").onchange = loadVerification;
$("#btn-export-verify-xlsx").onclick = () => {
  if (state.diff) postDownload(`/api/export/verify/${state.diff.diff_id}`,
    { format: "xlsx", only_b_is_error: !$("#verify-allow-b").checked }, "verify.xlsx");
};
$("#btn-export-verify-csv").onclick = () => {
  if (state.diff) postDownload(`/api/export/verify/${state.diff.diff_id}`,
    { format: "csv", only_b_is_error: !$("#verify-allow-b").checked }, "verify.csv");
};

function renderStatusbar() {
  const d = state.diff;
  const keys = d.columns_a.filter((c, i) => d.key_flags[i]);
  const norms = [];
  if ($("#opt-trim").checked) norms.push("空白除去");
  if ($("#opt-width").checked) norms.push("全半角同一視");
  if ($("#opt-case").checked) norms.push("大小文字同一視");
  if ($("#opt-tolerance").value) norms.push(`許容誤差${$("#opt-tolerance").value}`);
  const total = d.summary.only_a + d.summary.only_b + d.summary.changed + d.summary.same;
  $("#diff-statusbar").innerHTML =
    `<span>${total}件</span>` +
    `<span>キー: ${escapeHtml(keys.join(" + "))}</span>` +
    `<span>正規化: ${norms.length ? norms.join("・") : "なし"}</span>` +
    `<span class="right">準備完了</span>`;
}

async function loadRows() {
  const d = state.diff;
  if (!d) return;
  try {
    const params = new URLSearchParams({
      status: currentStatus, offset: currentOffset, limit: PAGE_SIZE,
    });
    const res = await (await api(`/api/diff/${d.diff_id}/rows?${params}`)).json();
    currentTotal = res.total;
    renderRowsTable(res.rows);
    const from = res.total === 0 ? 0 : currentOffset + 1;
    const to = Math.min(currentOffset + PAGE_SIZE, res.total);
    $("#diff-page-info").textContent = `${from}–${to} / ${res.total}件`;
  } catch (e) { toast(e.message, true); }
}

function choiceKey(row, colA) { return JSON.stringify([row.key, colA]); }

let currentRows = [];  // 表示中ページの行(詳細パネル用)
let viewMode = localStorage.getItem("diffdesk-viewmode") || "merged";

function matchLabelFor(r, nValues) {
  const man = r.manual ? ` <span class="hint">(手動紐づけ)</span>` : "";
  if (r.known && (r.status === "only_a" || r.status === "only_b")) return "既知(容認)";
  if (r.status === "same") {
    return (r.known_diffs?.length
      ? `<b>${nValues}/${nValues}</b> <span class="hint">(既知${r.known_diffs.length})</span>`
      : `<b>${nValues}/${nValues}</b> 一致`) + man;
  }
  if (r.status === "changed") {
    const nAll = r.manual ? state.diff.columns_a.length : nValues;
    return `<b>${nAll - r.cell_diffs.length}/${nAll}</b> 一致${man}`;
  }
  if (r.status === "only_a") return "未登録";
  return "基準に無し";
}

function renderRowsTable(rows) {
  currentRows = rows;
  const split = viewMode === "split";
  $("#merged-wrap").hidden = split;
  $("#merged-hint").hidden = split;
  $("#split-view").hidden = !split;
  $("#split-legend").hidden = !split;
  if (split) {
    renderSplitTable(rows);
    return;
  }
  const d = state.diff;
  const nCols = d.columns_a.length;
  const nValues = d.key_flags.filter(f => !f).length;
  const head = `<tr><th>状態</th><th>照合</th>` + d.columns_a.map((c, i) => {
    const label = c === d.columns_b[i] ? c : `${c} / ${d.columns_b[i]}`;
    return `<th>${d.key_flags[i] ? "🔑 " : ""}${escapeHtml(label)}</th>`;
  }).join("") + `</tr>`;

  const matchLabel = r => matchLabelFor(r, nValues);

  const body = rows.map((r, ri) => {
    const cells = [];
    const changedCols = new Map(r.cell_diffs.map(cd => [cd.col_a, cd]));
    for (let i = 0; i < nCols; i++) {
      const colA = d.columns_a[i];
      const cd = changedCols.get(colA);
      if (cd) {
        const chosen = state.mergeChoices[choiceKey(r, colA)] === "b" ? "b" : "a";
        cells.push(`<td class="cell-changed"><span class="diffval" data-key='${escapeHtml(JSON.stringify(r.key))}' data-col="${escapeHtml(colA)}">` +
          `<span class="side a ${chosen === "a" ? "chosen" : ""}" title="Aの値を採用">${escapeHtml(cd.value_a) || "<i>(空)</i>"}</span>` +
          `<span class="arrow">→</span>` +
          `<span class="side b ${chosen === "b" ? "chosen" : ""}" title="Bの値を採用">${escapeHtml(cd.value_b) || "<i>(空)</i>"}</span>` +
          `</span></td>`);
      } else {
        const v = r.row_a ? r.row_a[i] : (r.row_b ? r.row_b[i] : "");
        cells.push(`<td>${escapeHtml(v)}</td>`);
      }
    }
    return `<tr class="row-${r.status}" data-ri="${ri}"><td>${STATUS_JA[r.status]}</td>` +
      `<td class="matchcell">${matchLabel(r)}</td>${cells.join("")}</tr>`;
  }).join("");

  $("#diff-table").innerHTML = `<thead>${head}</thead><tbody>${body}</tbody>`;
  $$("#diff-table .diffval .side").forEach(el => {
    el.onclick = e => {
      e.stopPropagation();  // 行クリック(詳細表示)と区別
      const wrap = el.closest(".diffval");
      const key = choiceKey({ key: JSON.parse(wrap.dataset.key) }, wrap.dataset.col);
      state.mergeChoices[key] = el.classList.contains("b") ? "b" : "a";
      wrap.querySelectorAll(".side").forEach(s => s.classList.remove("chosen"));
      el.classList.add("chosen");
    };
  });
  $$("#diff-table tbody tr").forEach(tr => {
    tr.onclick = () => showRecordDetail(currentRows[+tr.dataset.ri]);
  });
}

// 左右分割表示: コードエディタの差分表示風。左=基準(A)、右=比較(B)を
// レコード対で同じ高さに揃え、赤(未登録)/緑(基準に無し)/黄(相違)で色付け。
const SPLIT_TABLES = ["#split-a", "#split-g", "#split-b"];

function renderSplitTable(rows) {
  const d = state.diff;
  const nCols = d.columns_a.length;
  const nValues = d.key_flags.filter(f => !f).length;

  $("#split-label-a").textContent =
    `基準 (A)${state.fileA ? " — " + state.fileA.filename : ""}`;
  $("#split-label-b").textContent =
    `比較 (B)${state.fileB ? " — " + state.fileB.filename : ""}`;

  const colgroup = `<colgroup><col style="width:44px">` +
    d.columns_a.map(() => `<col style="width:160px">`).join("") + `</colgroup>`;
  const headRow = cols => `<tr><th class="rownum">#</th>` +
    cols.map((c, i) =>
      `<th title="${escapeHtml(c)}">${d.key_flags[i] ? "🔑 " : ""}${escapeHtml(c)}</th>`
    ).join("") + `</tr>`;

  let numA = 0, numB = 0;
  const bodyA = [], bodyB = [], bodyG = [];
  rows.forEach((r, ri) => {
    const changedIdx = new Set(r.cell_diffs.map(cd => d.columns_a.indexOf(cd.col_a)));
    const knownIdx = new Set((r.known_diffs || []).map(cd => d.columns_a.indexOf(cd.col_a)));
    const rowCls = r.known ? "sp-known"
      : r.status === "changed" ? "sp-mod"
      : r.status === "only_a" ? "sp-del"
      : r.status === "only_b" ? "sp-add" : "";

    const sideRow = (vals, num, absentLabel, cellCls) => {
      if (!vals) {
        return `<td class="sp-absent" colspan="${nCols + 1}">${absentLabel}</td>`;
      }
      return `<td class="rownum">${num}</td>` + vals.map((v, i) => {
        const cls = changedIdx.has(i) ? cellCls : (knownIdx.has(i) ? "sp-cell-known" : "");
        return `<td class="${cls}" title="${escapeHtml(v)}">${escapeHtml(v)}</td>`;
      }).join("");
    };
    bodyA.push(`<tr class="${rowCls}" data-ri="${ri}">` +
      sideRow(r.row_a, r.row_a ? ++numA : 0, "(基準に無し)", "sp-cell-del") + `</tr>`);
    bodyB.push(`<tr class="${rowCls}" data-ri="${ri}">` +
      sideRow(r.row_b, r.row_b ? ++numB : 0, "(比較先に未登録)", "sp-cell-add") + `</tr>`);

    const [mark, label] = r.known ? ["既", "既知(容認)"]
      : r.manual ? ["⇔", "手動で紐づけ済み(詳細から解除できます)"]
      : r.status === "changed" ? ["≠", `値の相違: ${matchLabelFor(r, nValues).replace(/<[^>]*>/g, "")}`]
      : r.status === "only_a" ? ["−", "比較先に未登録"]
      : r.status === "only_b" ? ["＋", "基準に無し"]
      : ["＝", "一致"];
    const linkable = !r.known && (r.status === "only_a" || r.status === "only_b");
    const cellContent = linkable
      ? `<span class="linkdot" title="ドラッグして相手側の行に落とすと手動で紐づけ">●</span>`
      : mark;
    bodyG.push(`<tr class="${rowCls}" data-ri="${ri}">` +
      `<td class="g-${r.known ? "known" : r.manual ? "manual" : r.status}` +
      `${linkable ? " linkable" : ""}" title="${escapeHtml(label)}">${cellContent}</td></tr>`);
  });

  $("#split-a").innerHTML =
    colgroup + `<thead>${headRow(d.columns_a)}</thead><tbody>${bodyA.join("")}</tbody>`;
  $("#split-b").innerHTML =
    colgroup + `<thead>${headRow(d.columns_b)}</thead><tbody>${bodyB.join("")}</tbody>`;
  $("#split-g").innerHTML =
    `<thead><tr><th>&nbsp;</th></tr></thead><tbody>${bodyG.join("")}</tbody>`;

  // 行クリック=詳細、ホバー=対応レコードを左右両方で強調
  SPLIT_TABLES.forEach(sel => $$(sel + " tbody tr").forEach(tr => {
    tr.onclick = () => showRecordDetail(currentRows[+tr.dataset.ri]);
    tr.onmouseenter = () => setSplitHover(+tr.dataset.ri, true);
    tr.onmouseleave = () => setSplitHover(+tr.dataset.ri, false);
  }));
}

function setSplitHover(ri, on) {
  SPLIT_TABLES.forEach(sel => {
    const tr = document.querySelector(`${sel} tbody tr[data-ri="${ri}"]`);
    if (tr) tr.classList.toggle("hoverrow", on);
  });
}

// 縦スクロールを3ペインで同期、横スクロールは左右ペインで同期(列が1:1対応のため)
{
  const pa = $("#split-pane-a"), pb = $("#split-pane-b"), pg = $("#split-pane-g");
  let lock = false;
  const sync = src => () => {
    if (lock) return;
    lock = true;
    const other = src === pa ? pb : pa;
    other.scrollTop = src.scrollTop;
    other.scrollLeft = src.scrollLeft;
    pg.scrollTop = src.scrollTop;
    requestAnimationFrame(() => { lock = false; });
  };
  pa.addEventListener("scroll", sync(pa));
  pb.addEventListener("scroll", sync(pb));
}

// ---------------------------------------------------------------- 手動紐づけ(ドラッグ)
// 中央ガターの ● を掴んで反対側の未対応行に落とすと、その2行をペアとして登録する。
let linkDrag = null;  // {ri, status, x0, y0, moved, targetTr}

function overlayPos(e) {
  const rect = $("#split-view").getBoundingClientRect();
  return [e.clientX - rect.left, e.clientY - rect.top];
}

function dropTargetAt(e, drag) {
  const el = document.elementFromPoint(e.clientX, e.clientY);
  const tr = el && el.closest("#split-view tbody tr[data-ri]");
  if (!tr) return null;
  const r = currentRows[+tr.dataset.ri];
  const want = drag.status === "only_a" ? "only_b" : "only_a";
  return (r && r.status === want && !r.known) ? tr : null;
}

function clearLinkTargets() {
  $$("#split-view tr.link-target").forEach(t => t.classList.remove("link-target"));
}

document.addEventListener("pointerdown", e => {
  const dot = e.target.closest("#split-g td.linkable");
  if (!dot) return;
  const tr = dot.closest("tr[data-ri]");
  const r = currentRows[+tr.dataset.ri];
  if (!r) return;
  e.preventDefault();
  const [x, y] = overlayPos(e);
  linkDrag = { ri: +tr.dataset.ri, status: r.status, x0: x, y0: y, moved: false, targetTr: null };
  const ov = $("#link-overlay");
  const line = ov.querySelector("line");
  line.setAttribute("x1", x); line.setAttribute("y1", y);
  line.setAttribute("x2", x); line.setAttribute("y2", y);
});

document.addEventListener("pointermove", e => {
  if (!linkDrag) return;
  const [x, y] = overlayPos(e);
  if (!linkDrag.moved && Math.hypot(x - linkDrag.x0, y - linkDrag.y0) < 5) return;
  linkDrag.moved = true;
  $("#link-overlay").removeAttribute("hidden");  // SVGはhiddenプロパティ非対応
  const line = $("#link-overlay").querySelector("line");
  line.setAttribute("x2", x); line.setAttribute("y2", y);
  const target = dropTargetAt(e, linkDrag);
  if (target !== linkDrag.targetTr) {
    clearLinkTargets();
    linkDrag.targetTr = target;
    if (target) SPLIT_TABLES.forEach(sel => {
      const t = document.querySelector(`${sel} tbody tr[data-ri="${target.dataset.ri}"]`);
      if (t) t.classList.add("link-target");
    });
  }
});

document.addEventListener("pointerup", e => {
  if (!linkDrag) return;
  const drag = linkDrag;
  linkDrag = null;
  $("#link-overlay").setAttribute("hidden", "");
  clearLinkTargets();
  if (!drag.moved) return;  // ●はドラッグ専用(行の他の部分クリックで詳細表示)
  const target = dropTargetAt(e, drag);
  if (!target) return;
  const rSrc = currentRows[drag.ri];
  const rDst = currentRows[+target.dataset.ri];
  if (!rSrc || !rDst) return;
  const [keyA, keyB] = drag.status === "only_a"
    ? [rSrc.key, rDst.key] : [rDst.key, rSrc.key];
  registerManualPair(keyA, keyB);
});

async function registerManualPair(keyA, keyB) {
  const d = state.diff;
  if (!d) return;
  try {
    await postJson(`/api/diff/${d.diff_id}/manual-pairs`,
      { key_a: [...keyA], key_b: [...keyB] });
    toast(`「${keyA.join("/")}」と「${keyB.join("/")}」を手動で紐づけました(⇔印)。詳細画面から解除できます。`);
    refreshAfterKnownChange();
  } catch (e) { toast(e.message, true); }
}

async function unlinkManualPair(r) {
  const d = state.diff;
  if (!d) return;
  try {
    const { pairs } = await (await api(`/api/diff/${d.diff_id}/manual-pairs`)).json();
    const idx = pairs.findIndex(p => JSON.stringify(p.key_a) === JSON.stringify([...r.key]));
    if (idx < 0) return toast("この紐づけが見つかりません。", true);
    await api(`/api/diff/${d.diff_id}/manual-pairs/${idx}`, { method: "DELETE" });
    toast("手動の紐づけを解除しました。");
    $("#dialog").close();
    refreshAfterKnownChange();
  } catch (e) { toast(e.message, true); }
}

// ---------------------------------------------------------------- 全画面表示
$("#btn-fullscreen").onclick = () => setFullscreen(!document.body.classList.contains("diff-fs"));

function setFullscreen(on) {
  document.body.classList.toggle("diff-fs", on);
  $("#btn-fullscreen").textContent = on ? "✕ 全画面解除" : "⛶ 全画面";
}

document.addEventListener("keydown", e => {
  if (e.key === "Escape" && document.body.classList.contains("diff-fs")) setFullscreen(false);
});

$("#view-merged").onclick = () => setViewMode("merged");
$("#view-split").onclick = () => setViewMode("split");

function setViewMode(mode) {
  viewMode = mode;
  try { localStorage.setItem("diffdesk-viewmode", mode); } catch { /* 無視 */ }
  $("#view-merged").classList.toggle("active", mode === "merged");
  $("#view-split").classList.toggle("active", mode === "split");
  renderRowsTable(currentRows);
}

// 起動時に前回の表示形式を反映
$("#view-merged").classList.toggle("active", viewMode === "merged");
$("#view-split").classList.toggle("active", viewMode === "split");

// レコード詳細: 1件の全項目を基準↔比較で縦に並べて照合表示
function showRecordDetail(r) {
  if (!r) return;
  const d = state.diff;
  const changed = new Map(r.cell_diffs.map(cd => [cd.col_a, cd]));
  const rowsHtml = d.columns_a.map((colA, i) => {
    const colB = d.columns_b[i];
    const va = r.row_a ? r.row_a[i] : "";
    const vb = r.row_b ? r.row_b[i] : "";
    let mark, cls;
    if (changed.has(colA)) { mark = "✖"; cls = "detail-ng"; }
    else if (d.key_flags[i]) { mark = "🔑"; cls = ""; }
    else if (r.status === "only_a") { mark = "－"; cls = "detail-miss"; }
    else if (r.status === "only_b") { mark = "－"; cls = "detail-miss"; }
    else if (r.known_diffs?.some(kd => kd.col_a === colA)) { mark = "済"; cls = "detail-ok"; }
    else { mark = "✔"; cls = "detail-ok"; }
    const label = colA === colB ? colA : `${colA} / ${colB}`;
    const knownBtn = changed.has(colA)
      ? `<button class="mini known-cell-btn" data-col="${escapeHtml(colA)}" ` +
        `title="この差異を確認済み・問題なしとして登録">既知にする</button>`
      : "";
    return `<tr class="${cls}"><td>${mark}</td><td>${escapeHtml(label)}</td>` +
      `<td>${escapeHtml(va)}</td><td>${escapeHtml(vb)}</td><td>${knownBtn}</td></tr>`;
  }).join("");
  const nValues = d.key_flags.filter(f => !f).length;
  const summary = r.status === "same" ? `全${nValues}項目一致`
    : r.status === "changed" ? `${nValues - r.cell_diffs.length}/${nValues}項目一致(✖が相違)`
    : r.status === "only_a" ? "比較ファイル(B)に存在しません(未登録)"
    : "基準ファイル(A)に存在しません";
  const missingKnownBtn = (r.status === "only_a" || r.status === "only_b") && !r.known
    ? `<button id="known-row-btn" title="このレコードの欠落を確認済みとして容認する">この欠落を既知にする</button>`
    : "";
  const linkUi = (r.status === "only_a" || r.status === "only_b") && !r.known
    ? `<span id="link-ui"><select id="link-select"><option value="">(紐づける相手を選択)</option></select>
       <button id="link-do" title="キーが違うレコード同士を手動でペアにする">この相手と紐づけ</button></span>`
    : "";
  const unlinkBtn = r.manual
    ? `<button id="link-undo" title="手動の紐づけを取り消して元の未対応状態に戻す">紐づけを解除</button>`
    : "";
  const keyLine = r.manual && r.key_b
    ? `キー: ${escapeHtml(r.key.join(" / "))} ⇔ ${escapeHtml(r.key_b.join(" / "))}(手動紐づけ)`
    : `キー: ${escapeHtml(r.key.join(" / "))}`;
  const dlg = $("#dialog");
  dlg.innerHTML = `<h2>レコード照合詳細 — ${keyLine}</h2>
    <p style="margin:8px 12px"><b>${STATUS_JA[r.status]}${r.known ? "(既知)" : ""}${r.manual ? "(手動紐づけ)" : ""}</b>: ${summary}</p>
    <div style="margin:0 12px; max-height:60vh; overflow:auto">
    <table><thead><tr><th></th><th>項目</th><th>基準 (A)</th><th>比較 (B)</th><th></th></tr></thead>
    <tbody>${rowsHtml}</tbody></table></div>
    <div class="toolbar">${missingKnownBtn}${linkUi}${unlinkBtn}<button data-cancel class="primary">閉じる</button></div>`;
  dlg.querySelector("[data-cancel]").onclick = () => dlg.close();
  const linkDo = dlg.querySelector("#link-do");
  if (linkDo) {
    const side = r.status === "only_a" ? "b" : "a";  // 相手側の候補を出す
    (async () => {
      try {
        const { rows: cands } = await (await api(
          `/api/diff/${d.diff_id}/unmatched?side=${side}`)).json();
        const sel = dlg.querySelector("#link-select");
        sel.innerHTML = `<option value="">(紐づける相手を選択 — ${cands.length}件)</option>` +
          cands.map(c =>
            `<option value='${escapeHtml(JSON.stringify(c.key))}'>${escapeHtml(c.label)}</option>`
          ).join("");
      } catch { /* 候補が取れなくてもダイアログ自体は使える */ }
    })();
    linkDo.onclick = () => {
      const v = dlg.querySelector("#link-select").value;
      if (!v) return toast("紐づける相手を選択してください。", true);
      const other = JSON.parse(v);
      const [keyA, keyB] = r.status === "only_a" ? [[...r.key], other] : [other, [...r.key]];
      dlg.close();
      registerManualPair(keyA, keyB);
    };
  }
  const unlink = dlg.querySelector("#link-undo");
  if (unlink) unlink.onclick = () => unlinkManualPair(r);
  dlg.querySelectorAll(".known-cell-btn").forEach(b => b.onclick = () => {
    const cd = r.cell_diffs.find(x => x.col_a === b.dataset.col);
    if (cd) registerKnown({ type: "cell", key: [...r.key], col_a: cd.col_a,
                            value_a: cd.value_a, value_b: cd.value_b });
  });
  const rowBtn = dlg.querySelector("#known-row-btn");
  if (rowBtn) rowBtn.onclick = () =>
    registerKnown({ type: "row", key: [...r.key], status: r.status });
  dlg.showModal();
}

$$(".statusfilter").forEach(b => b.onclick = () => {
  currentStatus = b.dataset.status;
  currentOffset = 0;
  $$(".statusfilter").forEach(x => x.classList.toggle("active", x === b));
  loadRows();
});
$("#diff-prev").onclick = () => {
  if (currentOffset > 0) { currentOffset = Math.max(0, currentOffset - PAGE_SIZE); loadRows(); }
};
$("#diff-next").onclick = () => {
  if (currentOffset + PAGE_SIZE < currentTotal) { currentOffset += PAGE_SIZE; loadRows(); }
};

// ---------------------------------------------------------------- エクスポート
function encodingOptions(selected = "utf-8-sig") {
  return [["utf-8-sig", "UTF-8 (BOM付き) — Data Loader推奨"], ["utf-8", "UTF-8"], ["cp932", "CP932 (Shift_JIS)"]]
    .map(([v, l]) => `<option value="${v}" ${v === selected ? "selected" : ""}>${l}</option>`).join("");
}

async function postDownload(path, body, fallback) {
  try {
    const res = await api(path, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    await downloadResponse(res, fallback);
  } catch (e) { toast(e.message, true); }
}

$("#btn-export-upsert").onclick = async () => {
  const d = state.diff;
  if (!d) return;
  const keyCols = d.columns_a.filter((c, i) => d.key_flags[i]);
  const ok = await showDialog(`<h2>Data Loader用アップサートCSV</h2>
    <label>外部ID列(キーから選択):
      <select id="up-extid">${keyCols.map(c => `<option>${escapeHtml(c)}</option>`).join("")}</select></label>
    <label><input type="checkbox" id="up-insert" checked> Aのみの行を含める(insert)</label>
    <label><input type="checkbox" id="up-update" checked> 変更行を含める(update)</label>
    <label>エンコーディング: <select id="up-enc">${encodingOptions()}</select></label>
    <p class="hint">値はすべてファイルA(正マスタ)のもの。ヘッダーはSF項目名(未指定はB列名)。</p>`);
  if (!ok) return;
  await postDownload(`/api/export/upsert/${d.diff_id}`, {
    external_id: $("#up-extid").value,
    include_insert: $("#up-insert").checked,
    include_update: $("#up-update").checked,
    encoding: $("#up-enc").value,
  }, "upsert.csv");
};

$("#btn-export-delete").onclick = async () => {
  const d = state.diff;
  if (!d) return;
  const nOnlyB = d.summary.only_b;
  const ok = await showDialog(`<h2>削除用CSV</h2>
    <p><strong>Bのみに存在する ${nOnlyB} 行</strong>のId列を削除用CSVとして出力します。</p>
    <label>B側のId列名: <select id="del-col">${d.columns_b.map(c =>
      `<option ${c === "Id" ? "selected" : ""}>${escapeHtml(c)}</option>`).join("")}</select></label>
    <label>エンコーディング: <select id="del-enc">${encodingOptions()}</select></label>
    <p class="hint" style="color:#dc2626">⚠ Data Loaderでの削除は元に戻せません。内容を必ず確認してください。</p>`);
  if (!ok) return;
  await postDownload(`/api/export/delete/${d.diff_id}`, {
    id_col_b: $("#del-col").value, encoding: $("#del-enc").value,
  }, "delete.csv");
};

$("#btn-export-sdl").onclick = async () => {
  const d = state.diff;
  if (!d) return;
  try {
    const res = await api(`/api/export/sdl/${d.diff_id}`);
    await downloadResponse(res, "mapping.sdl");
  } catch (e) { toast(e.message, true); }
};

$("#btn-export-report-csv").onclick = () => {
  if (state.diff) postDownload(`/api/export/report/${state.diff.diff_id}`,
    { format: "csv" }, "report.csv");
};
$("#btn-export-report-xlsx").onclick = () => {
  if (state.diff) postDownload(`/api/export/report/${state.diff.diff_id}`,
    { format: "xlsx" }, "report.xlsx");
};
$("#btn-export-html").onclick = () => {
  if (state.diff) postDownload(`/api/export/html/${state.diff.diff_id}`,
    { only_b_is_error: !$("#verify-allow-b").checked }, "report.html");
};
$("#btn-export-restore").onclick = async () => {
  if (!state.diff) return;
  const ok = await showDialog(`<h2>復元用CSV(投入前のSF値)</h2>
    <p>変更(update対象)行について、<strong>投入前のSalesforce側の値</strong>を
    update用CSVとして保存します。</p>
    <p>アップサート投入後に誤りに気づいた場合、このCSVをData Loaderで
    updateすれば値を投入前に戻せます。<strong>投入前に必ず出力しておいてください。</strong></p>`);
  if (!ok) return;
  postDownload(`/api/export/restore/${state.diff.diff_id}`, {}, "restore.csv");
};

$("#btn-merge").onclick = async () => {
  const d = state.diff;
  if (!d) return;
  const choices = Object.entries(state.mergeChoices)
    .filter(([, v]) => v === "b")
    .map(([k]) => {
      const [key, colA] = JSON.parse(k);
      return { key, col_a: colA, use: "b" };
    });
  try {
    const info = await postJson(`/api/diff/${d.diff_id}/merge`, {
      choices, include_only_b: $("#merge-include-b").checked,
    });
    toast(`マージ結果を作成しました(${info.preview.total_rows}行)。グリッド編集タブで開けます。`);
    const { refreshFileList } = await import("/static/app.js");
    refreshFileList();
  } catch (e) { toast(e.message, true); }
};
