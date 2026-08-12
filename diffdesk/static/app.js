// メイン: タブ制御、ファイル読み込み、マッピング、プロファイル、差分実行
import {
  $, $$, api, apiJson, downloadResponse, escapeHtml, postJson,
  renderPreviewTable, showDialog, state, toast,
} from "/static/common.js";
import { renderDiff } from "/static/diffview.js";
import { initGrid, refreshGridFileList } from "/static/grid.js";
import "/static/junction.js";

// ---------------------------------------------------------------- タブ
export function switchTab(id) {
  $$("#tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === id));
  $$(".tab").forEach(t => t.classList.toggle("active", t.id === id));
}
$$("#tabs button").forEach(b => b.onclick = () => switchTab(b.dataset.tab));

// ---------------------------------------------------------------- アップロード
const ENCODINGS = [
  ["", "自動判定"], ["utf-8-sig", "UTF-8 (BOM付き)"], ["utf-8", "UTF-8"],
  ["cp932", "CP932 (Shift_JIS)"], ["utf-16", "UTF-16"], ["euc_jp", "EUC-JP"],
];
const DELIMITERS = [["", "自動"], [",", "カンマ ,"], ["\t", "タブ"], [";", "セミコロン ;"], ["|", "パイプ |"]];

function sideInfo(side) { return side === "a" ? state.fileA : state.fileB; }
function setSideInfo(side, info) {
  if (side === "a") state.fileA = info; else state.fileB = info;
}

let poolSettingsId = null;  // 読込設定パネルを開いているfile_id

// ファイルをプールへ追加(複数可)。空いていれば最初の2件を自動でA/Bに割当。
async function uploadToPool(files) {
  for (const file of files) {
    const form = new FormData();
    form.append("file", file);
    try {
      const info = await apiJson("/api/files", { method: "POST", body: form });
      if (!state.fileA) {
        setSideInfo("a", info);
      } else if (!state.fileB && state.fileA.file_id !== info.file_id) {
        setSideInfo("b", info);
      }
      toast(`${info.filename} を読み込みました (${info.preview.total_rows}行)`);
    } catch (e) { toast(`${file.name}: ${e.message}`, true); }
  }
  renderAssignments();
  refreshFileList();
  rebuildMappingSelects();
  updateNextSteps();
}

// 役割(基準A / 比較B)の割当
async function assignRole(fileId, side) {
  try {
    const info = await apiJson(`/api/files/${fileId}/info`);
    const other = side === "a" ? "b" : "a";
    if (sideInfo(other)?.file_id === fileId) setSideInfo(other, null);
    setSideInfo(side, info);
    renderAssignments();
    refreshFileList();
    rebuildMappingSelects();
    updateNextSteps();
    toast(`${info.filename} を${side === "a" ? "基準(A)" : "比較(B)"}にしました`);
  } catch (e) { toast(e.message, true); }
}

function updateNextSteps() {
  $("#next-steps").hidden = !(state.fileA && state.fileB);
}

function renderAssignments() {
  const a = state.fileA, b = state.fileB;
  $("#assign-previews").hidden = !a && !b;
  $("#assign-a-name").textContent = a
    ? `${a.filename} (${a.preview.total_rows}行)` : "未選択(一覧の「基準A」を選択)";
  $("#assign-b-name").textContent = b
    ? `${b.filename} (${b.preview.total_rows}行)` : "未選択(一覧の「比較B」を選択)";
  renderPreview("a");
  renderPreview("b");
}

function renderParsePanel() {
  // プールで「読込設定」を押したファイルの設定パネル
  const card = $("#pool-settings-card");
  if (!poolSettingsId) { card.hidden = true; return; }
  apiJson(`/api/files/${poolSettingsId}/info`).then(info => {
    card.hidden = false;
    $("#pool-settings-name").textContent = info.filename;
    const p = info.parse_params || {};
    const encSel = ENCODINGS.map(([v, l]) =>
      `<option value="${v}" ${v === (p.encoding || "") ? "selected" : ""}>${l}</option>`).join("");
    const delimSel = DELIMITERS.map(([v, l]) =>
      `<option value="${escapeHtml(v)}" ${v === (p.delimiter || "") ? "selected" : ""}>${l}</option>`).join("");
    const sheets = info.sheets
      ? `<label>シート: <select data-role="sheet">${info.sheets.map(s =>
          `<option ${s === (p.sheet || info.preview.sheet) ? "selected" : ""}>${escapeHtml(s)}</option>`).join("")}</select></label>`
      : "";
    const detected = info.detected_encoding
      ? `<span class="badge">判定: ${info.detected_encoding}${info.confidence < 0.9 ? " (要確認)" : ""}</span>`
      : "";
    const panel = $("#pool-parse-panel");
    panel.innerHTML = `
      <div class="toolbar">
        ${detected}
        ${info.is_excel ? sheets : `
          <label>エンコーディング: <select data-role="encoding">${encSel}</select></label>
          <label>区切り: <select data-role="delimiter">${delimSel}</select></label>`}
        <label>ヘッダー行: <input data-role="header_row" type="number" min="1" value="${p.header_row || 1}" style="width:60px"></label>
        <button data-role="reparse" class="primary">再読込</button>
        <button data-role="close-settings">閉じる</button>
      </div>`;
    renderPreviewTable($("#pool-preview"), info.preview.columns,
                       info.preview.rows, info.preview.total_rows);
    panel.querySelector('[data-role="reparse"]').onclick = () => reparsePool(info);
    panel.querySelector('[data-role="close-settings"]').onclick = () => {
      poolSettingsId = null;
      renderParsePanel();
    };
  }).catch(e => toast(e.message, true));
}

async function reparsePool(info) {
  const panel = $("#pool-parse-panel");
  const get = role => panel.querySelector(`[data-role="${role}"]`);
  const body = { header_row: parseInt(get("header_row").value || "1", 10) };
  if (info.is_excel) {
    body.sheet = get("sheet").value;
  } else {
    if (get("encoding").value) body.encoding = get("encoding").value;
    if (get("delimiter").value) body.delimiter = get("delimiter").value;
  }
  try {
    const updated = await postJson(`/api/files/${info.file_id}/parse`, body);
    // A/Bに割当済みならその情報も更新
    if (state.fileA?.file_id === updated.file_id) setSideInfo("a", updated);
    if (state.fileB?.file_id === updated.file_id) setSideInfo("b", updated);
    renderParsePanel();
    renderAssignments();
    refreshFileList();
    rebuildMappingSelects();
    toast("再読込しました");
  } catch (e) { toast(e.message, true); }
}

function renderPreview(side) {
  const info = sideInfo(side);
  const el = $(`.preview[data-side="${side}"]`);
  if (!info) { el.innerHTML = ""; return; }
  renderPreviewTable(el, info.preview.columns, info.preview.rows, info.preview.total_rows);
}

{
  const zone = $("#pool-drop");
  zone.ondragover = e => { e.preventDefault(); zone.classList.add("dragover"); };
  zone.ondragleave = () => zone.classList.remove("dragover");
  zone.ondrop = e => {
    e.preventDefault();
    zone.classList.remove("dragover");
    if (e.dataTransfer.files.length) uploadToPool([...e.dataTransfer.files]);
  };
  $("#pool-input").onchange = () => {
    if ($("#pool-input").files.length) uploadToPool([...$("#pool-input").files]);
    $("#pool-input").value = "";
  };
}

// ---------------------------------------------------------------- ファイル一覧・ユーティリティ
export async function refreshFileList() {
  const { files } = await apiJson("/api/files");
  const el = $("#pool-list");
  if (!files.length) {
    el.innerHTML = `<p class="hint">まだファイルがありません。上のエリアから読み込んでください。</p>`;
  } else {
    el.innerHTML = `<table><thead><tr><th title="ユーティリティの対象"></th><th>ファイル</th>` +
      `<th>行数</th><th>列数</th><th>基準A</th><th>比較B</th><th></th><th></th></tr></thead><tbody>` +
      files.map(f => {
        const isA = state.fileA?.file_id === f.file_id;
        const isB = state.fileB?.file_id === f.file_id;
        return `<tr class="${isA ? "row-role-a" : ""} ${isB ? "row-role-b" : ""}">
        <td><input type="checkbox" class="file-check" value="${f.file_id}"></td>
        <td>${escapeHtml(f.filename)}${isA ? ' <span class="rolechip role-a">A</span>' : ""}${isB ? ' <span class="rolechip role-b">B</span>' : ""}</td>
        <td>${f.total_rows}</td><td>${f.columns.length}</td>
        <td style="text-align:center"><input type="radio" name="role-a" class="role-radio" data-side="a" data-id="${f.file_id}" ${isA ? "checked" : ""} title="このファイルを基準(A)にする"></td>
        <td style="text-align:center"><input type="radio" name="role-b" class="role-radio" data-side="b" data-id="${f.file_id}" ${isB ? "checked" : ""} title="このファイルを比較(B)にする"></td>
        <td><button class="mini file-settings" data-id="${f.file_id}">読込設定</button></td>
        <td><button class="mini danger file-del" data-id="${f.file_id}">削除</button></td>
      </tr>`;
      }).join("") + `</tbody></table>`;
  }
  // エラーファイル分析・許可値取得用のファイルセレクトも更新
  for (const selId of ["#err-file-select", "#val-allow-src-file", "#health-file-select"]) {
    const sel = $(selId);
    if (!sel) continue;
    const cur = sel.value;
    sel.innerHTML = `<option value="">(選択)</option>` + files.map(f =>
      `<option value="${f.file_id}">${escapeHtml(f.filename)}</option>`).join("");
    if (files.some(f => f.file_id === cur)) sel.value = cur;
  }
  el.querySelectorAll(".role-radio").forEach(r => r.onchange = () =>
    assignRole(r.dataset.id, r.dataset.side));
  el.querySelectorAll(".file-settings").forEach(b => b.onclick = () => {
    poolSettingsId = b.dataset.id;
    renderParsePanel();
  });
  el.querySelectorAll(".file-del").forEach(b => b.onclick = async () => {
    await api(`/api/files/${b.dataset.id}`, { method: "DELETE" });
    if (state.fileA?.file_id === b.dataset.id) state.fileA = null;
    if (state.fileB?.file_id === b.dataset.id) state.fileB = null;
    if (poolSettingsId === b.dataset.id) { poolSettingsId = null; renderParsePanel(); }
    renderAssignments();
    updateNextSteps();
    refreshFileList();
    refreshGridFileList();
  });
  refreshGridFileList(files);
}

function checkedFileIds() {
  return $$(".file-check:checked").map(c => c.value);
}

$("#btn-concat").onclick = async () => {
  const ids = checkedFileIds();
  if (ids.length < 2) return toast("結合するファイルを2つ以上チェックしてください", true);
  try {
    const info = await postJson("/api/files/concat", { file_ids: ids });
    toast(`結合しました (${info.preview.total_rows}行) → グリッド編集タブで開けます`);
    refreshFileList();
  } catch (e) { toast(e.message, true); }
};

$("#btn-dedupe").onclick = async () => {
  const ids = checkedFileIds();
  if (ids.length !== 1) return toast("重複行削除するファイルを1つチェックしてください", true);
  try {
    const r = await postJson(`/api/files/${ids[0]}/dedupe`, {});
    toast(`完全重複行を${r.removed}件削除しました (${r.total_rows}行)`);
    refreshFileList();
  } catch (e) { toast(e.message, true); }
};

$("#btn-convert").onclick = async () => {
  const ids = checkedFileIds();
  if (ids.length !== 1) return toast("変換するファイルを1つチェックしてください", true);
  const enc = $("#convert-encoding").value;
  try {
    const res = await api(`/api/export/table/${ids[0]}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ encoding: enc }),
    });
    await downloadResponse(res, "converted.csv");
  } catch (e) { toast(e.message, true); }
};

// ---------------------------------------------------------------- Data Loaderエラーファイル分析
$("#btn-analyze-errors").onclick = async () => {
  const fid = $("#err-file-select").value;
  if (!fid) return toast("分析するファイルを選択してください", true);
  try {
    const r = await postJson(`/api/files/${fid}/analyze-errors`, {});
    const rows = r.categories.map(c =>
      `<tr><td>${escapeHtml(c.label)}</td><td>${c.count}</td>` +
      `<td class="hint">${escapeHtml(c.hint)}</td>` +
      `<td class="hint" style="max-width:380px;overflow:hidden;text-overflow:ellipsis">${escapeHtml(c.example)}</td></tr>`).join("");
    $("#err-analysis").innerHTML =
      `<p><b>${r.total_rows}行</b>の失敗レコード(ERROR列: ${escapeHtml(r.error_column)})</p>` +
      `<table><thead><tr><th>エラー分類</th><th>件数</th><th>対処ヒント</th><th>メッセージ例</th></tr></thead>` +
      `<tbody>${rows}</tbody></table>`;
  } catch (e) { toast(e.message, true); }
};

$("#btn-export-retry").onclick = async () => {
  const fid = $("#err-file-select").value;
  if (!fid) return toast("対象ファイルを選択してください", true);
  try {
    const res = await api(`/api/export/retry/${fid}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ encoding: "utf-8-sig" }),
    });
    await downloadResponse(res, "retry.csv");
    toast("再投入用CSVを出力しました(ERROR/STATUS列を除去済み)");
  } catch (e) { toast(e.message, true); }
};

$("#btn-undo-delete").onclick = async () => {
  const fid = $("#err-file-select").value;
  if (!fid) return toast("successファイルを選択してください", true);
  const ok = await showDialog(`<h2>取り消し用delete CSV</h2>
    <p>successファイル内で<strong>新規作成(Item Created)されたレコードのId</strong>を
    Data LoaderのDelete操作用CSVとして出力します。</p>
    <p class="hint" style="color:#dc2626">⚠ 削除は元に戻せません。出力内容を必ず確認してから投入してください。</p>`);
  if (!ok) return;
  try {
    const res = await api(`/api/files/${fid}/undo-delete`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const skipped = res.headers.get("X-Skipped-Updates");
    await downloadResponse(res, "undo_delete.csv");
    toast(`取り消し用delete CSVを出力しました` +
          (skipped && skipped !== "0" ? `(update成功行${skipped}件は除外)` : ""));
  } catch (e) { toast(e.message, true); }
};

// ---------------------------------------------------------------- ファイル健康診断
async function refreshBaselines() {
  try {
    const { baselines } = await apiJson("/api/baselines");
    $("#baseline-select").innerHTML = `<option value="">(基準)</option>` +
      baselines.map(b => `<option>${escapeHtml(b)}</option>`).join("");
  } catch { /* 起動直後は無視 */ }
}

$("#btn-health-check").onclick = async () => {
  const fid = $("#health-file-select").value;
  if (!fid) return toast("対象ファイルを選択してください", true);
  try {
    const p = await postJson(`/api/files/${fid}/profile`, {});
    $("#health-warnings").innerHTML = "";
    $("#health-result").innerHTML =
      `<p>全${p.rows}行</p><table><thead><tr><th>列</th><th>型</th><th>空欄率</th><th>ユニーク数</th><th>最大文字数</th><th>上位の値</th></tr></thead><tbody>` +
      p.columns.map(c => `<tr><td>${escapeHtml(c.name)}</td><td>${c.type}</td>` +
        `<td>${(c.empty_rate * 100).toFixed(1)}%</td><td>${c.unique}</td><td>${c.max_length}</td>` +
        `<td class="hint">${c.top_values.map(t => `${escapeHtml(t.value)}(${t.count})`).join("、")}</td></tr>`).join("") +
      `</tbody></table>`;
  } catch (e) { toast(e.message, true); }
};

$("#btn-baseline-save").onclick = async () => {
  const fid = $("#health-file-select").value;
  const name = $("#baseline-name").value.trim();
  if (!fid || !name) return toast("ファイルと基準名を指定してください", true);
  try {
    await postJson(`/api/files/${fid}/save-baseline`, { name });
    toast(`基準「${name}」を保存しました。来月は同じファイルを「比較」するだけです。`);
    refreshBaselines();
  } catch (e) { toast(e.message, true); }
};

$("#btn-baseline-compare").onclick = async () => {
  const fid = $("#health-file-select").value;
  const name = $("#baseline-select").value;
  if (!fid || !name) return toast("ファイルと基準を選択してください", true);
  try {
    const { warnings } = await postJson(`/api/files/${fid}/compare-baseline`, { name });
    $("#health-warnings").innerHTML = warnings.map(w =>
      `<div class="${w.level === "warn" ? "issue" : "hint"}" style="${w.level === "warn" ? "color:#9c3a2e" : ""}">・${escapeHtml(w.message)}</div>`).join("");
  } catch (e) { toast(e.message, true); }
};

// ---------------------------------------------------------------- キーなしあいまい突合
const fzPairs = [];
let fzCandidates = [];

function renderFzPairs() {
  $("#fz-pairs").textContent = fzPairs.length
    ? fzPairs.map(p => `${p[0]}↔${p[1]}`).join("、") : "(未指定)";
}

function fillFuzzySelects() {
  $("#fz-col-a").innerHTML = (state.fileA?.preview.columns || []).map(c =>
    `<option>${escapeHtml(c)}</option>`).join("");
  $("#fz-col-b").innerHTML = (state.fileB?.preview.columns || []).map(c =>
    `<option>${escapeHtml(c)}</option>`).join("");
}

$("#fz-add-pair").onclick = () => {
  const a = $("#fz-col-a").value, b = $("#fz-col-b").value;
  if (!a || !b) return toast("先にファイルA・Bを読み込んでください", true);
  fzPairs.push([a, b]);
  renderFzPairs();
};

$("#fz-detect").onclick = async () => {
  if (!state.fileA || !state.fileB) return toast("先にファイルA・Bを読み込んでください", true);
  if (!fzPairs.length) return toast("「＋追加」で比較する列ペアを指定してください", true);
  try {
    const r = await postJson("/api/fuzzy-match", {
      file_a: state.fileA.file_id, file_b: state.fileB.file_id,
      pairs: fzPairs, threshold: parseFloat($("#fz-threshold").value) || 0.75,
    });
    fzCandidates = r.candidates;
    if (!r.count) {
      $("#fz-list").innerHTML = `<p class="hint">しきい値以上の候補が見つかりませんでした。しきい値を下げてみてください。</p>`;
      $("#fz-link").hidden = true;
      return;
    }
    $("#fz-list").innerHTML =
      `<table><thead><tr><th></th><th>スコア</th>` +
      r.columns_a.map((c, i) => `<th>A: ${escapeHtml(c)} / B: ${escapeHtml(r.columns_b[i])}</th>`).join("") +
      `</tr></thead><tbody>` +
      r.candidates.map((c, k) => `<tr>
        <td><input type="checkbox" class="fz-use" data-k="${k}" ${c.score >= 0.9 ? "checked" : ""}></td>
        <td><b>${(c.score * 100).toFixed(0)}%</b></td>` +
        c.values_a.map((va, i) =>
          `<td>${escapeHtml(va)}<br><span class="hint">${escapeHtml(c.values_b[i])}</span></td>`).join("") +
        `</tr>`).join("") + `</tbody></table>`;
    $("#fz-link").hidden = false;
    toast(`${r.count}組の候補が見つかりました(90%以上は自動チェック済み)`);
  } catch (e) { toast(e.message, true); }
};

$("#fz-link").onclick = async () => {
  const matches = $$(".fz-use:checked").map(cb => fzCandidates[+cb.dataset.k]);
  if (!matches.length) return toast("紐づける組にチェックを入れてください", true);
  try {
    const info = await postJson("/api/fuzzy-link", {
      file_a: state.fileA.file_id, file_b: state.fileB.file_id, matches,
    });
    toast(`紐づけ結果ファイルを作成しました(${info.preview.total_rows}行)。グリッド編集タブで開けます。`);
    refreshFileList();
  } catch (e) { toast(e.message, true); }
};

// ---------------------------------------------------------------- マッピング
const FILTER_OPS = [
  ["eq", "＝"], ["ne", "≠"], ["contains", "を含む"], ["not_contains", "を含まない"],
  ["starts_with", "で始まる"], ["ends_with", "で終わる"],
  ["empty", "が空"], ["not_empty", "が空でない"], ["regex", "正規表現"],
];

function colOptions(cols, selected) {
  return cols.map(c =>
    `<option value="${escapeHtml(c)}" ${c === selected ? "selected" : ""}>${escapeHtml(c)}</option>`).join("");
}

export function rebuildMappingSelects() {
  renderMappingTable();
  renderFilters();
  fillFuzzySelects();
}

function transformSummary(t) {
  const parts = [];
  if (t.regex_rules?.length) parts.push(`正規表現${t.regex_rules.length}件`);
  if (t.value_map) parts.push(`値変換${Object.keys(t.value_map).length}組`);
  if (t.truthy_values) parts.push("真偽値化");
  if (t.type === "date") parts.push("日付");
  if (t.type === "number") parts.push("数値");
  return parts.join("・") || "変換";
}

function renderMappingTable() {
  const tbody = $("#mapping-table tbody");
  const colsA = state.fileA?.preview.columns || [];
  const colsB = state.fileB?.preview.columns || [];
  if (!colsA.length || !colsB.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="hint">ファイルAとBを読み込むとここで対応付けできます。</td></tr>`;
    return;
  }
  if (!state.mapping.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="hint">「自動対応付け」または「＋ペアを追加」で対応付けを作成してください。</td></tr>`;
    return;
  }
  const METHOD_JA = { name: "名前", value: "値", "name+value": "名前+値" };
  tbody.innerHTML = state.mapping.map((p, i) => `<tr>
    <td><select data-i="${i}" data-f="col_a">${colOptions(colsA, p.col_a)}</select>
      ${p._method ? `<div class="hint">自動: ${METHOD_JA[p._method] || p._method}一致 ${Math.round((p._confidence || 0) * 100)}%</div>` : ""}</td>
    <td>↔</td>
    <td><select data-i="${i}" data-f="col_b">${colOptions(colsB, p.col_b)}</select>
      ${p.transform ? `<div class="hint transform-badge" title="移行定義JSONの変換ルールをA側に再現適用して照合します">🔁 ${escapeHtml(transformSummary(p.transform))}</div>` : ""}</td>
    <td style="text-align:center"><input type="checkbox" data-i="${i}" data-f="is_key" ${p.is_key ? "checked" : ""} ${$("#key-mode").value !== "columns" ? "disabled" : ""}></td>
    <td><input data-i="${i}" data-f="sf_field" value="${escapeHtml(p.sf_field || "")}" placeholder="${escapeHtml(p.col_b)}" size="18" title="Data Loader出力時のSalesforce項目名。親レコードを外部IDで参照する場合は Account:ExtId__c の形式で指定できます"></td>
    <td><button class="mini danger" data-del="${i}">×</button></td>
  </tr>`).join("");
  tbody.querySelectorAll("select,input").forEach(el => {
    el.onchange = () => {
      const p = state.mapping[+el.dataset.i];
      if (el.dataset.f === "is_key") p.is_key = el.checked;
      else p[el.dataset.f] = el.value || null;
      if (el.dataset.f === "sf_field") p.sf_field = el.value || null;
      if ((el.dataset.f === "col_a" || el.dataset.f === "col_b") && p.transform) {
        p.transform = null;  // 列を変えたら定義由来の変換は無効(誤適用防止)
        renderMappingTable();
        toast("列を変更したため、この行の変換ルールを解除しました。");
      }
    };
  });
  tbody.querySelectorAll("[data-del]").forEach(b => b.onclick = () => {
    state.mapping.splice(+b.dataset.del, 1);
    renderMappingTable();
  });
}

$("#btn-add-pair").onclick = () => {
  const colsA = state.fileA?.preview.columns || [];
  const colsB = state.fileB?.preview.columns || [];
  if (!colsA.length || !colsB.length) return toast("先にファイルA・Bを読み込んでください", true);
  state.mapping.push({ col_a: colsA[0], col_b: colsB[0], is_key: !state.mapping.some(p => p.is_key), sf_field: null });
  renderMappingTable();
};

// 自動対応付け(キー自動推定込み)。成功時はペア数、失敗時はnullを返す。
async function doAutomap() {
  if (!state.fileA || !state.fileB) {
    toast("先にファイルA・Bを読み込んでください", true);
    return null;
  }
  const r = await postJson("/api/automap", {
    file_a: state.fileA.file_id, file_b: state.fileB.file_id,
  });
  if (!r.pairs.length) {
    toast("対応付けできるペアが見つかりませんでした。手動で追加してください。", true);
    return null;
  }
  state.mapping = r.pairs.map(p => ({
    col_a: p.col_a, col_b: p.col_b, is_key: p.is_key, sf_field: p.sf_field,
    _method: p.method, _confidence: p.confidence, _keyCandidate: p.key_candidate,
  }));
  // キー自動推定: 両側でユニークな列のうち、番号/ID/コード系の名前を優先
  const candidates = state.mapping.filter(p => p._keyCandidate);
  if (candidates.length) {
    const idLike = /番号|ID|コード|code|number|key|No\b/i;
    const best = candidates.find(p => idLike.test(p.col_a + p.col_b)) || candidates[0];
    best.is_key = true;
  }
  renderMappingTable();
  const parts = [];
  if (r.by_dict) parts.push(`辞書${r.by_dict}組`);
  if (r.by_name) parts.push(`名前一致${r.by_name}組`);
  if (r.by_value) parts.push(`中身から推定${r.by_value}組`);
  const detail = parts.length > 1 || r.by_dict ? `(${parts.join("・")})` : "";
  const keyMsg = candidates.length
    ? `キー候補として「${state.mapping.find(p => p.is_key)?.col_a}」を自動設定しました。`
    : "キー列にチェックを入れてください。";
  toast(`${r.pairs.length}組を自動対応付けしました${detail}。${keyMsg}`);
  return r.pairs.length;
}

$("#btn-automap").onclick = () => doAutomap().catch(e => toast(e.message, true));

// ---- 行フィルタ
function renderFilters() {
  for (const [side, conds, colsInfo] of [
    ["a", state.filtersA, state.fileA], ["b", state.filtersB, state.fileB],
  ]) {
    const el = $(`#filters-${side}`);
    const cols = colsInfo?.preview.columns || [];
    el.innerHTML = conds.map((c, i) => `<div class="toolbar">
      <select data-f="column" data-i="${i}">${colOptions(cols, c.column)}</select>
      <select data-f="op" data-i="${i}">${FILTER_OPS.map(([v, l]) =>
        `<option value="${v}" ${v === c.op ? "selected" : ""}>${l}</option>`).join("")}</select>
      <input data-f="value" data-i="${i}" value="${escapeHtml(c.value)}" size="10">
      <button class="mini danger" data-del="${i}">×</button>
    </div>`).join("") || `<p class="hint">条件なし(全行を比較)</p>`;
    el.querySelectorAll("select,input").forEach(inp => {
      inp.onchange = () => { conds[+inp.dataset.i][inp.dataset.f] = inp.value; };
    });
    el.querySelectorAll("[data-del]").forEach(b => b.onclick = () => {
      conds.splice(+b.dataset.del, 1);
      renderFilters();
    });
  }
}
$("#btn-add-filter-a").onclick = () => {
  const cols = state.fileA?.preview.columns || [];
  if (!cols.length) return toast("先にファイルAを読み込んでください", true);
  state.filtersA.push({ column: cols[0], op: "eq", value: "" });
  renderFilters();
};
$("#btn-add-filter-b").onclick = () => {
  const cols = state.fileB?.preview.columns || [];
  if (!cols.length) return toast("先にファイルBを読み込んでください", true);
  state.filtersB.push({ column: cols[0], op: "eq", value: "" });
  renderFilters();
};

// ---- オプション取得
export function currentOptions() {
  const tol = $("#opt-tolerance").value;
  return {
    trim: $("#opt-trim").checked,
    normalize_width: $("#opt-width").checked,
    ignore_case: $("#opt-case").checked,
    normalize_numeric: $("#opt-numeric").checked,
    numeric_tolerance: tol === "" ? null : parseFloat(tol),
  };
}
function applyOptions(o) {
  $("#opt-trim").checked = o.trim ?? true;
  $("#opt-width").checked = o.normalize_width ?? true;
  $("#opt-case").checked = o.ignore_case ?? false;
  $("#opt-numeric").checked = o.normalize_numeric ?? true;
  $("#opt-tolerance").value = o.numeric_tolerance ?? "";
}

// ---------------------------------------------------------------- マッピングJSONの読込/書出
function parseMappingJson(data) {
  // 受理する形式:
  //  1) プロファイル形式 {mapping: {pairs: [...]}, options, row_filter, external_id}
  //  2) {pairs: [...]} / [...](ペア配列)
  //  3) 単純な対応表 {"A列名": "B列名", ...}
  let pairs = null, options = null, filters = null, externalId = null;
  if (Array.isArray(data)) {
    pairs = data;
  } else if (data && typeof data === "object") {
    if (data.mapping && Array.isArray(data.mapping.pairs)) {
      pairs = data.mapping.pairs;
      options = data.options || null;
      filters = data.row_filter || null;
      externalId = data.external_id || null;
    } else if (Array.isArray(data.pairs)) {
      pairs = data.pairs;
    } else if (Object.values(data).every(v => typeof v === "string")) {
      pairs = Object.entries(data).map(([a, b]) => ({ col_a: a, col_b: b }));
    }
  }
  if (!pairs || !pairs.length) throw new Error("マッピングとして解釈できるJSONではありません");
  const normalized = pairs.map(p => ({
    col_a: String(p.col_a ?? ""), col_b: String(p.col_b ?? ""),
    is_key: !!p.is_key, sf_field: p.sf_field ? String(p.sf_field) : null,
  })).filter(p => p.col_a && p.col_b);
  if (!normalized.length) throw new Error("有効なペアがありません(col_a / col_b が必要です)");
  return { pairs: normalized, options, filters, externalId };
}

$("#btn-mapping-import").onclick = () => $("#mapping-file-input").click();
$("#mapping-file-input").onchange = async () => {
  const file = $("#mapping-file-input").files[0];
  $("#mapping-file-input").value = "";
  if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    let parsed;
    let specInfo = null;
    if (Array.isArray(data?.fields)) {
      // 移行定義JSON(マッピング仕様書)形式 → サーバーで変換ルールごと解釈
      const r = await postJson("/api/migration-spec/mapping", { spec: data });
      parsed = { pairs: r.pairs, options: null, filters: null, externalId: null };
      specInfo = r;
    } else {
      parsed = parseMappingJson(data);
    }
    const colsA = state.fileA?.preview.columns || [];
    const colsB = state.fileB?.preview.columns || [];
    let dropped = 0;
    let pairs = parsed.pairs;
    if (colsA.length && colsB.length) {
      const kept = pairs.filter(p => colsA.includes(p.col_a) && colsB.includes(p.col_b));
      dropped = pairs.length - kept.length;
      pairs = kept;
    }
    if (!pairs.length) return toast("JSON内の列名が読み込み済みファイルの列と一致しません", true);
    state.mapping = pairs;
    if (parsed.options) applyOptions(parsed.options);
    if (parsed.filters) {
      state.filtersA = parsed.filters.conditions_a || [];
      state.filtersB = parsed.filters.conditions_b || [];
    }
    rebuildMappingSelects();
    let msg = `${file.name} から${pairs.length}組を読み込みました` +
      (dropped ? `(列名不一致の${dropped}組は除外)` : "");
    if (specInfo) {
      const nT = pairs.filter(p => p.transform).length;
      if (nT) msg += `。変換ルールつき${nT}列は投入時の変換を再現して照合します`;
      if (specInfo.constants.length) {
        msg += `。定数項目${specInfo.constants.length}件(` +
          specInfo.constants.map(c => c.field).join(", ").slice(0, 60) + `)は照合対象外`;
      }
      if (specInfo.has_composite) {
        msg += "。複合キー項目があります — 多対多の検証は「5. 多対多検証」タブでこのJSONを読み込めます";
      }
    }
    toast(msg + (pairs.some(p => p.is_key) ? "" : "。キー列にチェックを入れてください"));
  } catch (e) { toast(`JSONの読み込みに失敗: ${e.message}`, true); }
};

$("#btn-mapping-export").onclick = () => {
  if (!state.mapping.length) return toast("書き出すマッピングがありません", true);
  const profile = {
    version: 1,
    name: $("#profile-name").value.trim() || "mapping",
    mapping: { pairs: state.mapping.map(p => ({
      col_a: p.col_a, col_b: p.col_b, is_key: p.is_key, sf_field: p.sf_field,
    })), key_mode: $("#key-mode").value },
    options: currentOptions(),
    row_filter: { conditions_a: state.filtersA, conditions_b: state.filtersB },
    external_id: state.mapping.find(p => p.is_key)?.col_a || null,
  };
  const blob = new Blob([JSON.stringify(profile, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${profile.name}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
};

// ---------------------------------------------------------------- ユーザー辞書
$("#btn-dict-learn").onclick = async () => {
  if (!state.mapping.length) return toast("学習させる対応がありません。先にマッピングを設定してください。", true);
  try {
    const pairs = state.mapping.map(p => ({ col_a: p.col_a, col_b: p.col_b }));
    const r = await postJson("/api/user-dict", { pairs });
    toast(`${pairs.length}組の対応をユーザー辞書に学習しました(辞書合計${r.count}組)。次回の自動対応付けで最優先されます。`);
    loadDictList();
  } catch (e) { toast(e.message, true); }
};

async function loadDictList() {
  try {
    const { entries } = await apiJson("/api/user-dict");
    $("#dict-list").innerHTML = entries.length
      ? `<table><thead><tr><th>自分の列名</th><th>相手の列名</th><th></th></tr></thead><tbody>` +
        entries.map((e, i) =>
          `<tr><td>${escapeHtml(e.col_a)}</td><td>${escapeHtml(e.col_b)}</td>` +
          `<td><button class="mini danger dict-del" data-i="${i}">削除</button></td></tr>`).join("") +
        `</tbody></table>`
      : `<p class="hint">まだ学習した対応はありません。「対応を辞書に学習」で登録できます。</p>`;
    $$(".dict-del").forEach(b => b.onclick = async () => {
      await api(`/api/user-dict/${b.dataset.i}`, { method: "DELETE" });
      loadDictList();
    });
  } catch { /* 無視 */ }
}
$("#dict-refresh").onclick = loadDictList;
loadDictList();

// ---------------------------------------------------------------- プロファイル
async function refreshProfiles() {
  try {
    const { profiles } = await apiJson("/api/profiles");
    $("#profile-select").innerHTML = `<option value="">(選択)</option>` +
      profiles.map(p => `<option>${escapeHtml(p)}</option>`).join("");
  } catch { /* 起動直後は無視 */ }
}

$("#btn-profile-save").onclick = async () => {
  const name = $("#profile-name").value.trim();
  if (!name) return toast("プロファイル名を入力してください", true);
  if (!state.mapping.length) return toast("保存するマッピングがありません", true);
  try {
    await postJson("/api/profiles", {
      profile: {
        name,
        mapping: { pairs: state.mapping, key_mode: $("#key-mode").value },
        options: currentOptions(),
        row_filter: { conditions_a: state.filtersA, conditions_b: state.filtersB },
        external_id: state.mapping.find(p => p.is_key)?.col_a || null,
      },
    });
    toast(`プロファイル「${name}」を保存しました`);
    refreshProfiles();
  } catch (e) { toast(e.message, true); }
};

$("#btn-profile-load").onclick = async () => {
  const name = $("#profile-select").value;
  if (!name) return toast("読み込むプロファイルを選択してください", true);
  try {
    const { profile } = await apiJson(`/api/profiles/${encodeURIComponent(name)}`);
    state.mapping = profile.mapping.pairs;
    $("#key-mode").value = profile.mapping.key_mode || "columns";
    onKeyModeChange();
    state.filtersA = profile.row_filter?.conditions_a || [];
    state.filtersB = profile.row_filter?.conditions_b || [];
    applyOptions(profile.options || {});
    $("#profile-name").value = profile.name;
    rebuildMappingSelects();
    toast(`プロファイル「${name}」を読み込みました`);
  } catch (e) { toast(e.message, true); }
};

$("#btn-profile-delete").onclick = async () => {
  const name = $("#profile-select").value;
  if (!name) return toast("削除するプロファイルを選択してください", true);
  if (!await showDialog(`<h2>プロファイル削除</h2><p>「${escapeHtml(name)}」を削除しますか?</p>`)) return;
  await api(`/api/profiles/${encodeURIComponent(name)}`, { method: "DELETE" });
  refreshProfiles();
  toast("削除しました");
};

// ---------------------------------------------------------------- キー方式
const KEY_MODE_HINTS = {
  columns: "",
  row_number: "行番号で比較: 両ファイルを上から順に1行ずつ突き合わせます(並び順が同じデータ向け)。キー列のチェックは使いません。行の追加・削除があると以降がずれて見えます。",
  content: "行の内容で比較: 全列が一致した行同士を対応付け、それ以外は「Aのみ」「Bのみ」になります(変更セルの検出はありません)。同一内容の重複行は照合対象外として警告されます。",
};

export function onKeyModeChange() {
  const mode = $("#key-mode").value;
  const hint = $("#key-mode-hint");
  hint.hidden = !KEY_MODE_HINTS[mode];
  hint.textContent = KEY_MODE_HINTS[mode] || "";
  renderMappingTable();
}
$("#key-mode").onchange = onKeyModeChange;

// ---------------------------------------------------------------- 差分実行
async function runDiff() {
  if (!state.fileA || !state.fileB) return toast("ファイルAとBを読み込んでください", true);
  if (!state.mapping.length) return toast("列マッピングを設定してください", true);
  if ($("#key-mode").value === "columns" && !state.mapping.some(p => p.is_key)) {
    return toast("キー列が指定されていません。キー☑を付けるか、キー方式を「行番号」「行の内容」に変更してください", true);
  }
  try {
    const body = {
      file_a: state.fileA.file_id,
      file_b: state.fileB.file_id,
      mapping: { pairs: state.mapping, key_mode: $("#key-mode").value },
      options: currentOptions(),
      row_filter: { conditions_a: state.filtersA, conditions_b: state.filtersB },
    };
    state.diff = await postJson("/api/diff", body);
    state.mergeChoices = {};
    switchTab("tab-diff");
    renderDiff();
    toast("差分を実行しました");
  } catch (e) { toast(e.message, true); }
}
$("#btn-run-diff").onclick = runDiff;

// おまかせ比較: 自動対応付け → キー自動推定 → 差分実行
$("#btn-omakase").onclick = async () => {
  try {
    const n = await doAutomap();
    if (!n) { switchTab("tab-map"); return; }
    if ($("#key-mode").value === "columns" && !state.mapping.some(p => p.is_key)) {
      switchTab("tab-map");
      return toast("キー列を自動で決められませんでした。キーにチェックを入れるか、紐づけキーを「行番号」「行の内容」に変更して「差分を実行」してください。", true);
    }
    await runDiff();
  } catch (e) { toast(e.message, true); }
};

$("#btn-goto-map").onclick = () => switchTab("tab-map");

$("#btn-swap").onclick = () => {
  if (!state.fileA && !state.fileB) return;
  [state.fileA, state.fileB] = [state.fileB, state.fileA];
  state.mapping = state.mapping.map(p => ({
    col_a: p.col_b, col_b: p.col_a, is_key: p.is_key, sf_field: null,
  }));
  [state.filtersA, state.filtersB] = [state.filtersB, state.filtersA];
  renderAssignments();
  refreshFileList();
  rebuildMappingSelects();
  updateNextSteps();
  toast("ファイルAとBを入れ替えました(マッピングも反転)");
};

// ---------------------------------------------------------------- 設定の記憶
const PREFS_KEY = "diffdesk-prefs";

function savePrefs() {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify({
      options: currentOptions(),
      convertEnc: $("#convert-encoding").value,
      gridEnc: $("#grid-export-encoding").value,
    }));
  } catch { /* プライベートモード等では保存しない */ }
}

function restorePrefs() {
  try {
    const prefs = JSON.parse(localStorage.getItem(PREFS_KEY) || "null");
    if (!prefs) return;
    if (prefs.options) applyOptions(prefs.options);
    if (prefs.convertEnc) $("#convert-encoding").value = prefs.convertEnc;
    if (prefs.gridEnc) $("#grid-export-encoding").value = prefs.gridEnc;
  } catch { /* 壊れた保存値は無視 */ }
}

["#opt-trim", "#opt-width", "#opt-case", "#opt-numeric", "#opt-tolerance",
 "#convert-encoding", "#grid-export-encoding"].forEach(sel => {
  $(sel).addEventListener("change", savePrefs);
});

// ---------------------------------------------------------------- 初期化
initGrid();
restorePrefs();
refreshProfiles();
refreshBaselines();
refreshFileList();

// ---------------------------------------------------------------- 見比べウィンドウ
{
  const openCompare = () =>
    window.open("/compare", "diffdesk-compare", "width=1500,height=900");
  const b1 = $("#btn-compare-1");
  const b2 = $("#btn-compare-2");
  if (b1) b1.onclick = openCompare;
  if (b2) b2.onclick = openCompare;
}

// ---------------------------------------------------------------- 案件切替
async function loadProjects() {
  try {
    const cfg = await apiJson("/api/projects");
    const sel = $("#project-select");
    sel.innerHTML = cfg.names.map(n =>
      `<option value="${escapeHtml(n)}" ${n === cfg.current ? "selected" : ""}>${escapeHtml(n)}</option>`).join("");
  } catch { /* 表示のみの機能なので失敗は無視 */ }
}

$("#project-select").onchange = async () => {
  const name = $("#project-select").value;
  try {
    await postJson("/api/projects/switch", { name });
    toast(`案件「${name}」に切り替えました`);
    document.dispatchEvent(new CustomEvent("diffdesk:workspace-changed"));
    loadDictList();
  } catch (e) { toast(e.message, true); loadProjects(); }
};

$("#project-new").onclick = async () => {
  const name = window.prompt("新しい案件名(例: ○○試験 移行検証)");
  if (!name) return;
  try {
    await postJson("/api/projects", { name });
    await loadProjects();
    toast(`案件「${name.trim()}」を作成して切り替えました`);
    document.dispatchEvent(new CustomEvent("diffdesk:workspace-changed"));
    loadDictList();
  } catch (e) { toast(e.message, true); }
};

// ---------------------------------------------------------------- 統一アンドゥ
$("#undo-btn").onclick = async () => {
  try {
    const r = await postJson("/api/undo", {});
    toast(`元に戻しました: ${r.label}`);
    document.dispatchEvent(new CustomEvent("diffdesk:workspace-changed"));
    loadDictList();
  } catch (e) { toast(e.message, true); }
};
$("#undo-btn").onmouseenter = async () => {
  try {
    const r = await apiJson("/api/undo");
    $("#undo-btn").title = r.count
      ? `直前の操作を取り消す: ${r.label}(残り${r.count}件)`
      : "元に戻せる操作はありません";
  } catch { /* ツールチップ用なので失敗は無視 */ }
};

// ---------------------------------------------------------------- 更新チェック
(async () => {
  try {
    const r = await apiJson("/api/update-check");
    if (r.update_available) {
      const badge = $("#update-badge");
      badge.textContent = `⬆ v${r.latest} が公開されています`;
      badge.title = "クリックでリリースページを開く。更新コマンド:\n" +
        'python -m pip install --upgrade "diffdesk @ git+https://github.com/cfn0eft/DiffDesk.git"';
      badge.hidden = false;
    }
  } catch { /* オフライン等では何も表示しない */ }
})();

// ---------------------------------------------------------------- ヘルプ
$("#help-btn").onclick = () => {
  showDialog(`<h2>DiffDesk クイックガイド</h2>
  <div style="margin:0 12px; max-height:65vh; overflow:auto">
  <ol style="line-height:1.9; padding-left:1.4em">
    <li><b>1. ファイル読み込み</b> — CSV/Excelを何個でもドロップ。基準(A)と比較(B)をラジオで選択。文字化けは「読込設定」から直せます</li>
    <li><b>2. 紐づけ設定</b> — 「自動対応付け」で列を対応付け。キーが無いファイルは<b>キー方式</b>を「行番号」「行の内容」に</li>
    <li><b>3. 照合結果</b> — 統合/左右分割で差異を確認。<b>「未対応」フィルタ+左右分割</b>で紐づけモード(●をドラッグ)。問題ない差異は「既知にする」で容認</li>
    <li><b>4. 編集・整形</b> — セル編集・一括クレンジング・検索置換・Data Loaderエラー分析</li>
    <li><b>5. 多対多検証</b> — 中間(ジャンクション)オブジェクトの投入検証</li>
  </ol>
  <h3 style="margin:10px 0 4px">よく使う機能</h3>
  <ul style="line-height:1.8; padding-left:1.4em">
    <li><b>案件</b>(画面上部) — 既知差分・履歴・手動紐づけ・辞書を案件ごとに分けて保存</li>
    <li><b>↩ 元に戻す</b> — 既知差分・手動紐づけ・辞書の直前の登録/削除を取り消し(直近30操作)</li>
    <li><b>1551 と 1551.0</b> — 数値の表記ゆれは既定で同一視(オプションで変更可)</li>
    <li><b>Web版AI連携</b> — 「AI用プロンプトをコピー」→Gemini等に貼付→回答を貼り戻すと紐づけ候補に(DiffDesk自体は通信しません)</li>
  </ul>
  <p class="hint" style="margin:8px 0">詳細は <a href="https://github.com/cfn0eft/DiffDesk#readme" target="_blank" rel="noopener">README(GitHub)</a> を参照。バージョン: ヘッダー右上に表示</p>
  </div>
  <div class="toolbar"><button data-cancel class="primary">閉じる</button></div>`);
};

loadProjects();

// ---------------------------------------------------------------- 作業セッションの保存/復元
async function loadWorksessions() {
  try {
    const { sessions } = await apiJson("/api/worksessions");
    $("#ws-list").innerHTML = sessions.length
      ? `<table><thead><tr><th>名前</th><th>保存日時</th><th>ファイル</th><th>サイズ</th><th></th><th></th></tr></thead><tbody>` +
        sessions.map(s =>
          `<tr><td><b>${escapeHtml(s.name)}</b></td><td class="hint">${escapeHtml(s.saved_at)}</td>` +
          `<td>${s.files.map(f => escapeHtml(f.filename) + (f.role ? `<span class="rolechip role-${f.role}">${f.role.toUpperCase()}</span>` : "")).join(", ")}</td>` +
          `<td class="hint">${(s.size / 1024).toFixed(0)}KB</td>` +
          `<td><button class="mini primary ws-restore" data-n="${escapeHtml(s.name)}">復元</button></td>` +
          `<td><button class="mini danger ws-del" data-n="${escapeHtml(s.name)}">削除</button></td></tr>`
        ).join("") + `</tbody></table>`
      : `<p class="hint">保存済みのセッションはありません。</p>`;
    $$(".ws-restore").forEach(b => b.onclick = () => restoreWorksession(b.dataset.n));
    $$(".ws-del").forEach(b => b.onclick = async () => {
      if (!window.confirm(`セッション「${b.dataset.n}」を削除しますか?`)) return;
      await api(`/api/worksession/${encodeURIComponent(b.dataset.n)}`, { method: "DELETE" });
      toast("セッションを削除しました");
      loadWorksessions();
    });
  } catch { /* 一覧のみの機能なので失敗は無視 */ }
}

$("#ws-save").onclick = async () => {
  const name = $("#ws-name").value.trim();
  if (!name) return toast("セッション名を入力してください", true);
  try {
    const meta = await postJson("/api/worksession/save", {
      name,
      file_a: state.fileA?.file_id || "",
      file_b: state.fileB?.file_id || "",
      mapping: { pairs: state.mapping, key_mode: $("#key-mode").value },
      options: currentOptions(),
      row_filter: { conditions_a: state.filtersA, conditions_b: state.filtersB },
    });
    toast(`セッション「${meta.name}」を保存しました(${meta.files.length}ファイル)`);
    loadWorksessions();
  } catch (e) { toast(e.message, true); }
};

async function restoreWorksession(name) {
  try {
    const r = await postJson("/api/worksession/restore", { name });
    await refreshFileList();
    refreshGridFileList();
    if (r.role_a) await assignRole(r.role_a, "a");
    if (r.role_b) await assignRole(r.role_b, "b");
    state.mapping = r.mapping?.pairs || [];
    $("#key-mode").value = r.mapping?.key_mode || "columns";
    onKeyModeChange();
    state.filtersA = r.row_filter?.conditions_a || [];
    state.filtersB = r.row_filter?.conditions_b || [];
    applyOptions(r.options || {});
    rebuildMappingSelects();
    renderFilters();
    $("#ws-name").value = r.name || name;
    toast(`セッション「${name}」を復元しました`);
    // マッピングとA/Bが揃っていれば差分まで自動実行
    if (state.fileA && state.fileB && state.mapping.length) {
      const keyless = $("#key-mode").value !== "columns";
      if (keyless || state.mapping.some(p => p.is_key)) await runDiff();
    }
  } catch (e) { toast(e.message, true); }
}

document.addEventListener("diffdesk:workspace-changed", loadWorksessions);
loadWorksessions();
