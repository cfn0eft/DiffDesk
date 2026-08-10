// メイン: タブ制御、ファイル読み込み、マッピング、プロファイル、差分実行
import {
  $, $$, api, apiJson, downloadResponse, escapeHtml, postJson,
  renderPreviewTable, showDialog, state, toast,
} from "/static/common.js";
import { renderDiff } from "/static/diffview.js";
import { initGrid, refreshGridFileList } from "/static/grid.js";

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

async function uploadFile(side, file) {
  const form = new FormData();
  form.append("file", file);
  try {
    const info = await apiJson("/api/files", { method: "POST", body: form });
    setSideInfo(side, info);
    renderParsePanel(side);
    renderPreview(side);
    refreshFileList();
    rebuildMappingSelects();
    toast(`${info.filename} を読み込みました (${info.preview.total_rows}行)`);
  } catch (e) { toast(e.message, true); }
}

function renderParsePanel(side) {
  const info = sideInfo(side);
  const panel = $(`.parse-panel[data-side="${side}"]`);
  if (!info) { panel.hidden = true; return; }
  panel.hidden = false;
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
  panel.innerHTML = `
    <div class="toolbar">
      <strong>${escapeHtml(info.filename)}</strong> ${detected}
    </div>
    <div class="toolbar">
      ${info.is_excel ? sheets : `
        <label>エンコーディング: <select data-role="encoding">${encSel}</select></label>
        <label>区切り: <select data-role="delimiter">${delimSel}</select></label>`}
      <label>ヘッダー行: <input data-role="header_row" type="number" min="1" value="${p.header_row || 1}" style="width:60px"></label>
      <button data-role="reparse">再読込</button>
    </div>`;
  panel.querySelector('[data-role="reparse"]').onclick = () => reparse(side);
}

async function reparse(side) {
  const info = sideInfo(side);
  const panel = $(`.parse-panel[data-side="${side}"]`);
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
    setSideInfo(side, updated);
    renderParsePanel(side);
    renderPreview(side);
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

$$(".dropzone").forEach(zone => {
  const side = zone.dataset.side;
  zone.ondragover = e => { e.preventDefault(); zone.classList.add("dragover"); };
  zone.ondragleave = () => zone.classList.remove("dragover");
  zone.ondrop = e => {
    e.preventDefault();
    zone.classList.remove("dragover");
    if (e.dataTransfer.files[0]) uploadFile(side, e.dataTransfer.files[0]);
  };
});
$$('input[type="file"][data-side]').forEach(input => {
  input.onchange = () => {
    if (input.files[0]) uploadFile(input.dataset.side, input.files[0]);
    input.value = "";
  };
});

// ---------------------------------------------------------------- ファイル一覧・ユーティリティ
export async function refreshFileList() {
  const { files } = await apiJson("/api/files");
  const el = $("#file-list");
  if (!files.length) { el.innerHTML = `<p class="hint">まだファイルがありません。</p>`; return; }
  el.innerHTML = `<table><thead><tr><th></th><th>ファイル</th><th>行数</th><th>列数</th><th></th></tr></thead><tbody>` +
    files.map(f => `<tr>
      <td><input type="checkbox" class="file-check" value="${f.file_id}"></td>
      <td>${escapeHtml(f.filename)} <span class="hint">${f.file_id}</span></td>
      <td>${f.total_rows}</td><td>${f.columns.length}</td>
      <td><button class="mini file-del" data-id="${f.file_id}">削除</button></td>
    </tr>`).join("") + `</tbody></table>`;
  el.querySelectorAll(".file-del").forEach(b => b.onclick = async () => {
    await api(`/api/files/${b.dataset.id}`, { method: "DELETE" });
    if (state.fileA?.file_id === b.dataset.id) { state.fileA = null; renderParsePanel("a"); renderPreview("a"); }
    if (state.fileB?.file_id === b.dataset.id) { state.fileB = null; renderParsePanel("b"); renderPreview("b"); }
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
    <td><select data-i="${i}" data-f="col_b">${colOptions(colsB, p.col_b)}</select></td>
    <td style="text-align:center"><input type="checkbox" data-i="${i}" data-f="is_key" ${p.is_key ? "checked" : ""}></td>
    <td><input data-i="${i}" data-f="sf_field" value="${escapeHtml(p.sf_field || "")}" placeholder="${escapeHtml(p.col_b)}" size="18"></td>
    <td><button class="mini danger" data-del="${i}">×</button></td>
  </tr>`).join("");
  tbody.querySelectorAll("select,input").forEach(el => {
    el.onchange = () => {
      const p = state.mapping[+el.dataset.i];
      if (el.dataset.f === "is_key") p.is_key = el.checked;
      else p[el.dataset.f] = el.value || null;
      if (el.dataset.f === "sf_field") p.sf_field = el.value || null;
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

$("#btn-automap").onclick = async () => {
  if (!state.fileA || !state.fileB) return toast("先にファイルA・Bを読み込んでください", true);
  try {
    const r = await postJson("/api/automap", {
      file_a: state.fileA.file_id, file_b: state.fileB.file_id,
    });
    if (!r.pairs.length) return toast("対応付けできるペアが見つかりませんでした。手動で追加してください。", true);
    state.mapping = r.pairs.map(p => ({
      col_a: p.col_a, col_b: p.col_b, is_key: p.is_key, sf_field: p.sf_field,
      _method: p.method, _confidence: p.confidence,
    }));
    renderMappingTable();
    const detail = r.by_value
      ? `(名前一致${r.by_name}組・データの中身から推定${r.by_value}組)`
      : "";
    toast(`${r.pairs.length}組を自動対応付けしました${detail}。キー列にチェックを入れてください。`);
  } catch (e) { toast(e.message, true); }
};

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
    numeric_tolerance: tol === "" ? null : parseFloat(tol),
  };
}
function applyOptions(o) {
  $("#opt-trim").checked = o.trim ?? true;
  $("#opt-width").checked = o.normalize_width ?? true;
  $("#opt-case").checked = o.ignore_case ?? false;
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
    const parsed = parseMappingJson(JSON.parse(await file.text()));
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
    toast(`${file.name} から${pairs.length}組を読み込みました` +
          (dropped ? `(列名不一致の${dropped}組は除外)` : "") +
          (pairs.some(p => p.is_key) ? "" : "。キー列にチェックを入れてください"));
  } catch (e) { toast(`JSONの読み込みに失敗: ${e.message}`, true); }
};

$("#btn-mapping-export").onclick = () => {
  if (!state.mapping.length) return toast("書き出すマッピングがありません", true);
  const profile = {
    version: 1,
    name: $("#profile-name").value.trim() || "mapping",
    mapping: { pairs: state.mapping.map(p => ({
      col_a: p.col_a, col_b: p.col_b, is_key: p.is_key, sf_field: p.sf_field,
    })) },
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
        mapping: { pairs: state.mapping },
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

// ---------------------------------------------------------------- 差分実行
$("#btn-run-diff").onclick = async () => {
  if (!state.fileA || !state.fileB) return toast("ファイルAとBを読み込んでください", true);
  if (!state.mapping.length) return toast("列マッピングを設定してください", true);
  if (!state.mapping.some(p => p.is_key)) return toast("キー列を1つ以上指定してください", true);
  try {
    const body = {
      file_a: state.fileA.file_id,
      file_b: state.fileB.file_id,
      mapping: { pairs: state.mapping },
      options: currentOptions(),
      row_filter: { conditions_a: state.filtersA, conditions_b: state.filtersB },
    };
    state.diff = await postJson("/api/diff", body);
    state.mergeChoices = {};
    switchTab("tab-diff");
    renderDiff();
    toast("差分を実行しました");
  } catch (e) { toast(e.message, true); }
};

// ---------------------------------------------------------------- 初期化
initGrid();
refreshProfiles();
refreshFileList();
