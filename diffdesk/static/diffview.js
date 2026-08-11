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
  loadRows();
}

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
      ? "✔ 投入OK — 件数・内容ともに一致しています"
      : "✖ 要確認 — 差異があります";
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

function renderRowsTable(rows) {
  const d = state.diff;
  const nCols = d.columns_a.length;
  const head = `<tr><th>状態</th>` + d.columns_a.map((c, i) => {
    const label = c === d.columns_b[i] ? c : `${c} / ${d.columns_b[i]}`;
    return `<th>${d.key_flags[i] ? "🔑 " : ""}${escapeHtml(label)}</th>`;
  }).join("") + `</tr>`;

  const body = rows.map(r => {
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
    return `<tr class="row-${r.status}"><td>${STATUS_JA[r.status]}</td>${cells.join("")}</tr>`;
  }).join("");

  $("#diff-table").innerHTML = `<thead>${head}</thead><tbody>${body}</tbody>`;
  $$("#diff-table .diffval .side").forEach(el => {
    el.onclick = () => {
      const wrap = el.closest(".diffval");
      const key = choiceKey({ key: JSON.parse(wrap.dataset.key) }, wrap.dataset.col);
      state.mergeChoices[key] = el.classList.contains("b") ? "b" : "a";
      wrap.querySelectorAll(".side").forEach(s => s.classList.remove("chosen"));
      el.classList.add("chosen");
    };
  });
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
