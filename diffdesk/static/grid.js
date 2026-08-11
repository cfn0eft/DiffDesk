// グリッド編集タブ: クライアント側で編集し「保存」で一括PUT
import {
  $, $$, api, apiJson, downloadResponse, escapeHtml, postJson, showDialog, toast,
} from "/static/common.js";

const PAGE_SIZE = 200;
const UNDO_LIMIT = 50;

const grid = {
  fileId: null,
  filename: "",
  columns: [],
  rows: [],
  page: 0,
  dirty: false,
  undoStack: [],
  viewFilter: "",
  sortCol: null,
  sortDir: 1,
};

// undoは表全体のコピーではなく操作の逆変換だけを記録する(大規模データ対応)
function pushUndo(entry) {
  grid.undoStack.push(entry);
  if (grid.undoStack.length > UNDO_LIMIT) grid.undoStack.shift();
}

function applyUndo(e) {
  switch (e.type) {
    case "cell":
      grid.rows[e.row][e.col] = e.old;
      break;
    case "delrows":  // 追加した行を取り消す
      [...e.indices].sort((a, b) => b - a).forEach(i => grid.rows.splice(i, 1));
      break;
    case "insrows":  // 削除した行を元の位置に戻す
      e.items.forEach(([i, row]) => grid.rows.splice(i, 0, row));
      break;
    case "delcol":   // 追加した列を取り消す
      grid.columns.splice(e.index, 1);
      grid.rows.forEach(r => r.splice(e.index, 1));
      break;
    case "inscol":   // 削除した列を元に戻す
      grid.columns.splice(e.index, 0, e.name);
      grid.rows.forEach((r, ri) => r.splice(e.index, 0, e.values[ri] ?? ""));
      break;
    case "rename":
      grid.columns[e.index] = e.old;
      break;
    case "roworder":  // ソート前の並びに戻す(行参照の共有でメモリ効率良)
      grid.rows = e.rows;
      break;
  }
}

function markDirty() {
  grid.dirty = true;
  updateStatus();
}

function updateStatus() {
  $("#grid-status").innerHTML = grid.fileId
    ? `<span>${escapeHtml(grid.filename)}</span>` +
      `<span>${grid.rows.length}行 × ${grid.columns.length}列</span>` +
      `<span class="right">${grid.dirty ? "未保存の変更あり" : "保存済み"}</span>`
    : "";
}

// ---------------------------------------------------------------- 読み込み
export function refreshGridFileList(files) {
  const fill = list => {
    const sel = $("#grid-file-select");
    const cur = sel.value;
    sel.innerHTML = `<option value="">(選択)</option>` + list.map(f =>
      `<option value="${f.file_id}">${escapeHtml(f.filename)} (${f.total_rows}行)</option>`).join("");
    if (list.some(f => f.file_id === cur)) sel.value = cur;
  };
  if (files) { fill(files); return; }
  apiJson("/api/files").then(r => fill(r.files)).catch(() => {});
}

async function loadGridFile(fileId) {
  const all = [];
  let offset = 0, total = Infinity, columns = [], filename = "";
  while (offset < total) {
    const r = await apiJson(`/api/files/${fileId}?offset=${offset}&limit=10000`);
    columns = r.columns; total = r.total_rows; filename = r.filename;
    all.push(...r.rows);
    offset += 10000;
    if (r.rows.length === 0) break;
  }
  grid.fileId = fileId;
  grid.filename = filename;
  grid.columns = columns;
  grid.rows = all;
  grid.page = 0;
  grid.dirty = false;
  grid.undoStack = [];
  renderGrid();
  fillColumnSelectors();
  updateStatus();
}

// ---------------------------------------------------------------- 描画
function visibleIndices() {
  const q = grid.viewFilter.trim().toLowerCase();
  if (!q) return null;  // フィルタなし=全行
  const idx = [];
  grid.rows.forEach((r, i) => {
    if (r.some(v => v.toLowerCase().includes(q))) idx.push(i);
  });
  return idx;
}

function sortByColumn(ci) {
  pushUndo({ type: "roworder", rows: [...grid.rows] });
  const dir = (grid.sortCol === ci && grid.sortDir === 1) ? -1 : 1;
  grid.sortCol = ci;
  grid.sortDir = dir;
  grid.rows.sort((a, b) => {
    const x = a[ci], y = b[ci];
    const nx = parseFloat(x), ny = parseFloat(y);
    let cmp;
    if (x.trim() !== "" && y.trim() !== "" && !isNaN(nx) && !isNaN(ny)) cmp = nx - ny;
    else cmp = x.localeCompare(y, "ja");
    return dir * cmp;
  });
  markDirty();
  renderGrid();
}

function renderGrid() {
  const container = $("#grid-container");
  if (!grid.fileId) { container.innerHTML = `<p class="hint">ファイルを選択して「読み込み」を押してください。</p>`; return; }
  const vis = visibleIndices();
  const totalVisible = vis ? vis.length : grid.rows.length;
  const start = grid.page * PAGE_SIZE;
  const pageIdx = vis
    ? vis.slice(start, start + PAGE_SIZE)
    : Array.from({ length: Math.max(0, Math.min(PAGE_SIZE, grid.rows.length - start)) },
                 (_, k) => start + k);
  const head = `<tr><th></th>` + grid.columns.map((c, i) =>
    `<th data-col="${i}"><span class="colname" title="ダブルクリックで列名変更">${escapeHtml(c)}</span>` +
    `<span class="sortbtn" data-col="${i}" title="この列でソート">⇅</span>` +
    `<span class="delcol" data-col="${i}" title="列を削除">×</span></th>`).join("") + `</tr>`;
  const body = pageIdx.map(rowIdx => {
    const r = grid.rows[rowIdx];
    return `<tr data-row="${rowIdx}"><td class="rowsel"><input type="checkbox" class="rowcheck" data-row="${rowIdx}"></td>` +
      r.map((v, ci) =>
        `<td><input value="${escapeHtml(v)}" data-row="${rowIdx}" data-col="${ci}"></td>`).join("") + `</tr>`;
  }).join("");
  container.innerHTML = `<table><thead>${head}</thead><tbody>${body}</tbody></table>`;
  container.querySelectorAll(".sortbtn").forEach(el => {
    el.onclick = () => sortByColumn(+el.dataset.col);
  });

  container.querySelectorAll("tbody input:not(.rowcheck)").forEach(inp => {
    inp.onfocus = () => { inp.dataset.orig = inp.value; };
    inp.onkeydown = e => {
      if (e.key === "Enter") {  // Enterで同じ列の下のセルへ
        e.preventDefault();
        inp.blur();
        const next = container.querySelector(
          `input[data-row="${+inp.dataset.row + 1}"][data-col="${inp.dataset.col}"]`);
        if (next) { next.focus(); next.select(); }
      }
    };
    inp.onchange = () => {
      if (inp.value !== inp.dataset.orig) {
        pushUndo({ type: "cell", row: +inp.dataset.row, col: +inp.dataset.col,
                   old: inp.dataset.orig });
        grid.rows[+inp.dataset.row][+inp.dataset.col] = inp.value;
        markDirty();
      }
    };
  });
  container.querySelectorAll("th .colname").forEach(el => {
    el.ondblclick = async () => {
      const i = +el.parentElement.dataset.col;
      const ok = await showDialog(`<h2>列名の変更</h2>
        <label>新しい列名: <input id="rename-col" value="${escapeHtml(grid.columns[i])}"></label>`);
      if (!ok) return;
      const name = $("#rename-col").value.trim();
      if (!name) return toast("列名が空です", true);
      if (name !== grid.columns[i] && grid.columns.includes(name)) return toast("列名が重複しています", true);
      pushUndo({ type: "rename", index: i, old: grid.columns[i] });
      grid.columns[i] = name;
      markDirty();
      renderGrid();
      fillColumnSelectors();
    };
  });
  container.querySelectorAll(".delcol").forEach(el => {
    el.onclick = async () => {
      const i = +el.dataset.col;
      if (!await showDialog(`<h2>列の削除</h2><p>列「${escapeHtml(grid.columns[i])}」を削除しますか?</p>`)) return;
      pushUndo({ type: "inscol", index: i, name: grid.columns[i],
                 values: grid.rows.map(r => r[i]) });
      grid.columns.splice(i, 1);
      grid.rows.forEach(r => r.splice(i, 1));
      markDirty();
      renderGrid();
      fillColumnSelectors();
    };
  });
  const totalPages = Math.max(1, Math.ceil(totalVisible / PAGE_SIZE));
  if (grid.page >= totalPages) {  // 行削除・フィルタでページが範囲外になったら戻す
    grid.page = totalPages - 1;
    renderGrid();
    return;
  }
  $("#grid-page-info").textContent = `ページ ${grid.page + 1} / ${totalPages}` +
    (vis ? `(フィルタ一致 ${totalVisible}行)` : "");
}

function fillColumnSelectors() {
  const opts = grid.columns.map(c => `<option>${escapeHtml(c)}</option>`).join("");
  $("#sr-column").innerHTML = `<option value="">全列</option>` + opts;
  $("#clean-column").innerHTML = opts;
  $("#val-keys").innerHTML = opts;
  $("#val-required").innerHTML = opts;
  $("#val-format-col").innerHTML = `<option value="">(列)</option>` + opts;
  $("#val-allow-col").innerHTML = `<option value="">(列)</option>` + opts;
  $("#val-range-col").innerHTML = `<option value="">(列)</option>` + opts;
  $("#cluster-col").innerHTML = opts;
  $("#split-col").innerHTML = opts;
  $("#anon-col").innerHTML = opts;
  $("#ct-row").innerHTML = opts;
  $("#ct-col").innerHTML = `<option value="">(なし=度数集計)</option>` + opts;
  $("#calc-cols").innerHTML = opts;
  $("#calc-col-s").innerHTML = opts;
  $("#calc-col-c").innerHTML = opts;
}

// ---------------------------------------------------------------- 操作
export function initGrid() {
  $("#grid-reload").onclick = async () => {
    const id = $("#grid-file-select").value;
    if (!id) return toast("ファイルを選択してください", true);
    if (grid.dirty && !await showDialog(`<h2>確認</h2><p>未保存の変更があります。破棄して読み込みますか?</p>`)) return;
    try { await loadGridFile(id); } catch (e) { toast(e.message, true); }
  };

  $("#grid-undo").onclick = () => {
    const entry = grid.undoStack.pop();
    if (!entry) return toast("これ以上戻せません", true);
    applyUndo(entry);
    markDirty();
    renderGrid();
    fillColumnSelectors();
  };

  $("#grid-save").onclick = async () => {
    if (!grid.fileId) return;
    try {
      await api(`/api/files/${grid.fileId}/table`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ columns: grid.columns, rows: grid.rows }),
      });
      grid.dirty = false;
      updateStatus();
      toast("保存しました");
      const { refreshFileList } = await import("/static/app.js");
      refreshFileList();
    } catch (e) { toast(e.message, true); }
  };

  $("#grid-export").onclick = async () => {
    if (!grid.fileId) return;
    if (!await ensureSaved()) return;  // 未保存の編集を確実に反映してから出力
    updateStatus();
    const enc = $("#grid-export-encoding").value;
    const body = enc === "xlsx" ? { format: "xlsx" } : { encoding: enc };
    try {
      const res = await api(`/api/export/table/${grid.fileId}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      await downloadResponse(res, "export.csv");
    } catch (e) { toast(e.message, true); }
  };

  $("#grid-add-row").onclick = () => {
    if (!grid.fileId) return;
    pushUndo({ type: "delrows", indices: [grid.rows.length] });
    grid.rows.push(new Array(grid.columns.length).fill(""));
    grid.page = Math.floor((grid.rows.length - 1) / PAGE_SIZE);
    markDirty();
    renderGrid();
  };

  $("#grid-del-rows").onclick = () => {
    const checked = $$(".rowcheck:checked").map(c => +c.dataset.row);
    if (!checked.length) return toast("削除する行にチェックを入れてください", true);
    const drop = new Set(checked);
    pushUndo({ type: "insrows",
               items: checked.sort((a, b) => a - b).map(i => [i, grid.rows[i]]) });
    grid.rows = grid.rows.filter((_, i) => !drop.has(i));
    markDirty();
    renderGrid();
  };

  $("#grid-add-col").onclick = async () => {
    if (!grid.fileId) return;
    const ok = await showDialog(`<h2>列の追加</h2><label>列名: <input id="new-col-name" value=""></label>`);
    if (!ok) return;
    const name = $("#new-col-name").value.trim() || `列${grid.columns.length + 1}`;
    if (grid.columns.includes(name)) return toast("列名が重複しています", true);
    pushUndo({ type: "delcol", index: grid.columns.length });
    grid.columns.push(name);
    grid.rows.forEach(r => r.push(""));
    markDirty();
    renderGrid();
    fillColumnSelectors();
  };

  $("#grid-prev").onclick = () => { if (grid.page > 0) { grid.page--; renderGrid(); } };
  $("#grid-next").onclick = () => {
    if ((grid.page + 1) * PAGE_SIZE < grid.rows.length) { grid.page++; renderGrid(); }
  };

  // ---- サーバー側操作(検索置換・クレンジング・検証): 保存してから実行
  async function ensureSaved() {
    if (!grid.fileId) { toast("先にファイルを読み込んでください", true); return false; }
    if (grid.dirty) {
      await api(`/api/files/${grid.fileId}/table`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ columns: grid.columns, rows: grid.rows }),
      });
      grid.dirty = false;
    }
    return true;
  }

  $("#sr-find").onclick = async () => {
    if (!await ensureSaved()) return;
    try {
      const col = $("#sr-column").value;
      const r = await postJson(`/api/files/${grid.fileId}/search`, {
        query: $("#sr-query").value,
        columns: col ? [col] : null,
        regex: $("#sr-regex").checked,
        case_sensitive: $("#sr-case").checked,
      });
      $("#sr-result").textContent = `${r.count}件ヒット` +
        (r.hits.length ? `(最初: ${r.hits[0].row + 1}行目 [${r.hits[0].column}])` : "");
    } catch (e) { toast(e.message, true); }
  };

  $("#sr-do").onclick = async () => {
    if (!await ensureSaved()) return;
    try {
      const col = $("#sr-column").value;
      const r = await postJson(`/api/files/${grid.fileId}/replace`, {
        query: $("#sr-query").value,
        replacement: $("#sr-replace").value,
        columns: col ? [col] : null,
        regex: $("#sr-regex").checked,
        case_sensitive: $("#sr-case").checked,
      });
      $("#sr-result").textContent = `${r.replaced}件置換しました`;
      await loadGridFile(grid.fileId);
    } catch (e) { toast(e.message, true); }
  };

  apiJson("/api/clean-ops").then(({ ops }) => {
    $("#clean-ops").innerHTML = ops.map(o =>
      `<label><input type="checkbox" class="clean-op" value="${o.id}"> ${o.label}</label>`).join("<br>");
  }).catch(() => {});

  $("#clean-do").onclick = async () => {
    if (!await ensureSaved()) return;
    const cols = [...$("#clean-column").selectedOptions].map(o => o.value);
    const ops = $$(".clean-op:checked").map(c => c.value);
    if (!cols.length || !ops.length) return toast("列と操作を選択してください", true);
    try {
      const r = await postJson(`/api/files/${grid.fileId}/clean`, { columns: cols, ops });
      $("#clean-result").textContent = `${r.changed_cells}セルを変更しました`;
      await loadGridFile(grid.fileId);
    } catch (e) { toast(e.message, true); }
  };

  $("#val-allow-fetch").onclick = async () => {
    const fid = $("#val-allow-src-file").value;
    const col = $("#val-allow-src-col").value;
    if (!fid || !col) return toast("生成元のファイルと列を選択してください", true);
    try {
      const r = await postJson(`/api/files/${fid}/column-values`, { column: col });
      $("#val-allow-values").value = r.values.join(",");
      toast(`${r.values.length}個の許可値を取得しました` + (r.truncated ? "(上限で打ち切り)" : ""));
    } catch (e) { toast(e.message, true); }
  };

  $("#val-allow-src-file").onchange = async () => {
    const fid = $("#val-allow-src-file").value;
    if (!fid) return;
    try {
      const r = await apiJson(`/api/files/${fid}?limit=1`);
      $("#val-allow-src-col").innerHTML = `<option value="">(列)</option>` +
        r.columns.map(c => `<option>${escapeHtml(c)}</option>`).join("");
    } catch (e) { toast(e.message, true); }
  };

  $("#val-do").onclick = async () => {
    if (!await ensureSaved()) return;
    const formats = {};
    if ($("#val-format-col").value) formats[$("#val-format-col").value] = $("#val-format-kind").value;
    const allowed_values = {};
    if ($("#val-allow-col").value && $("#val-allow-values").value.trim()) {
      allowed_values[$("#val-allow-col").value] =
        $("#val-allow-values").value.split(",").map(v => v.trim()).filter(Boolean);
    }
    const ranges = {};
    if ($("#val-range-col").value &&
        ($("#val-range-min").value !== "" || $("#val-range-max").value !== "")) {
      ranges[$("#val-range-col").value] = [
        $("#val-range-min").value === "" ? null : parseFloat($("#val-range-min").value),
        $("#val-range-max").value === "" ? null : parseFloat($("#val-range-max").value),
      ];
    }
    try {
      const r = await postJson(`/api/files/${grid.fileId}/validate`, {
        key_columns: [...$("#val-keys").selectedOptions].map(o => o.value),
        required_columns: [...$("#val-required").selectedOptions].map(o => o.value),
        formats,
        allowed_values,
        ranges,
      });
      $("#val-result").innerHTML = r.count === 0
        ? `<p>✅ 問題は見つかりませんでした。</p>`
        : `<p class="issue">⚠ ${r.count}件の問題:</p>` + r.issues.slice(0, 200).map(i =>
            `<div class="issue">${i.row}行目 [${escapeHtml(i.column)}] ${escapeHtml(i.message)}</div>`).join("");
    } catch (e) { toast(e.message, true); }
  };

  // ---- 表示フィルタ
  let filterTimer = null;
  $("#grid-filter").oninput = () => {
    clearTimeout(filterTimer);
    filterTimer = setTimeout(() => {
      grid.viewFilter = $("#grid-filter").value;
      grid.page = 0;
      renderGrid();
    }, 250);
  };

  // ---- 表記ゆれ統一
  let clusterState = [];
  $("#cluster-detect").onclick = async () => {
    if (!await ensureSaved()) return;
    const col = $("#cluster-col").value;
    if (!col) return toast("対象列を選択してください", true);
    try {
      const r = await postJson(`/api/files/${grid.fileId}/clusters`, { column: col });
      clusterState = r.clusters;
      if (!r.count) {
        $("#cluster-list").innerHTML = "";
        $("#cluster-apply").hidden = true;
        $("#cluster-status").textContent = "表記ゆれは見つかりませんでした。";
        return;
      }
      $("#cluster-status").textContent =
        `${r.count}グループの表記ゆれ候補。統一先を選んで「統一」を押してください。`;
      $("#cluster-list").innerHTML = r.clusters.map((c, k) => `
        <div class="toolbar wrap">
          <label><input type="checkbox" class="cl-use" data-k="${k}" checked> 適用</label>
          <span>${c.values.map(v =>
            `<span class="badge warn">${escapeHtml(v.value)} (${v.count})</span>`).join(" ")}</span>
          <span>→ 統一先:</span>
          <select class="cl-canon" data-k="${k}">${c.values.map(v =>
            `<option ${v.value === c.suggested ? "selected" : ""}>${escapeHtml(v.value)}</option>`).join("")}</select>
        </div>`).join("");
      $("#cluster-apply").hidden = false;
    } catch (e) { toast(e.message, true); }
  };

  $("#cluster-apply").onclick = async () => {
    const col = $("#cluster-col").value;
    const mapping = {};
    $$(".cl-use:checked").forEach(cb => {
      const k = +cb.dataset.k;
      const canon = document.querySelector(`.cl-canon[data-k="${k}"]`).value;
      for (const v of clusterState[k].values) {
        if (v.value !== canon) mapping[v.value] = canon;
      }
    });
    if (!Object.keys(mapping).length) return toast("適用対象がありません", true);
    try {
      const r = await postJson(`/api/files/${grid.fileId}/apply-map`, { column: col, mapping });
      toast(`${r.changed}セルを統一しました`);
      $("#cluster-list").innerHTML = "";
      $("#cluster-apply").hidden = true;
      $("#cluster-status").textContent = "";
      await loadGridFile(grid.fileId);
    } catch (e) { toast(e.message, true); }
  };

  // ---- 列分割
  $("#split-do").onclick = async () => {
    if (!await ensureSaved()) return;
    const col = $("#split-col").value;
    const delim = $("#split-delim").value;
    if (!col || !delim) return toast("列と区切り文字を指定してください", true);
    try {
      const r = await postJson(`/api/files/${grid.fileId}/split-column`,
                               { column: col, delimiter: delim });
      toast(`「${col}」を${r.parts}列に分割しました`);
      await loadGridFile(grid.fileId);
    } catch (e) { toast(e.message, true); }
  };

  // ---- 住所分割
  $("#addr-do").onclick = async () => {
    if (!await ensureSaved()) return;
    const col = $("#split-col").value;
    if (!col) return toast("列を選択してください", true);
    try {
      const r = await postJson(`/api/files/${grid.fileId}/split-address`, { column: col });
      toast(`「${col}」を住所4列に分割しました(${r.parsed}行で都道府県等を検出)`);
      await loadGridFile(grid.fileId);
    } catch (e) { toast(e.message, true); }
  };

  // ---- クロス集計
  $("#ct-do").onclick = async () => {
    if (!await ensureSaved()) return;
    const rowCol = $("#ct-row").value;
    if (!rowCol) return toast("行に使う列を選択してください", true);
    try {
      const r = await postJson(`/api/files/${grid.fileId}/crosstab`, {
        row_col: rowCol, col_col: $("#ct-col").value || null,
      });
      const t = r.table;
      $("#ct-result").innerHTML =
        `<table><thead><tr>${t.columns.map(c => `<th>${escapeHtml(c)}</th>`).join("")}</tr></thead>` +
        `<tbody>${t.rows.map(row =>
          `<tr>${row.map(v => `<td>${escapeHtml(v)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
      $("#ct-save").hidden = false;
    } catch (e) { toast(e.message, true); }
  };

  $("#ct-save").onclick = async () => {
    try {
      const r = await postJson(`/api/files/${grid.fileId}/crosstab`, {
        row_col: $("#ct-row").value, col_col: $("#ct-col").value || null,
        save_as_file: true,
      });
      toast("集計結果を新規ファイルとして保存しました");
      const { refreshFileList } = await import("/static/app.js");
      refreshFileList();
    } catch (e) { toast(e.message, true); }
  };

  // ---- 計算列
  $("#calc-mode").onchange = () => {
    const m = $("#calc-mode").value;
    $("#calc-concat-row").hidden = m !== "concat";
    $("#calc-substr-row").hidden = m !== "substring";
    $("#calc-cond-row").hidden = m !== "conditional";
  };

  $("#calc-do").onclick = async () => {
    if (!await ensureSaved()) return;
    const mode = $("#calc-mode").value;
    const name = $("#calc-name").value.trim();
    if (!name) return toast("新しい列名を入力してください", true);
    const body = { mode, new_name: name };
    if (mode === "concat") {
      body.columns = [...$("#calc-cols").selectedOptions].map(o => o.value);
      body.separator = $("#calc-sep").value;
    } else if (mode === "substring") {
      body.column = $("#calc-col-s").value;
      body.start = parseInt($("#calc-start").value || "1", 10);
      body.length = $("#calc-len").value === "" ? null : parseInt($("#calc-len").value, 10);
    } else {
      body.column = $("#calc-col-c").value;
      body.op = $("#calc-op").value;
      body.value = $("#calc-value").value;
      body.then_value = $("#calc-then").value;
      body.else_value = $("#calc-else").value;
    }
    try {
      await postJson(`/api/files/${grid.fileId}/calc-column`, body);
      toast(`列「${name}」を作成しました`);
      await loadGridFile(grid.fileId);
    } catch (e) { toast(e.message, true); }
  };

  // ---- レシピ
  async function refreshRecipes() {
    try {
      const { recipes } = await apiJson("/api/recipes");
      $("#recipe-select").innerHTML = `<option value="">(選択)</option>` +
        recipes.map(r => `<option>${escapeHtml(r)}</option>`).join("");
    } catch { /* 無視 */ }
  }
  refreshRecipes();

  $("#recipe-show").onclick = async () => {
    if (!grid.fileId) return toast("先にファイルを読み込んでください", true);
    try {
      const r = await apiJson(`/api/files/${grid.fileId}/recipe`);
      $("#recipe-log").innerHTML = r.labels.length
        ? "<b>操作履歴:</b><br>" + r.labels.map((l, i) => `${i + 1}. ${escapeHtml(l)}`).join("<br>")
        : "このファイルにはまだ記録された整形操作がありません(クレンジング・置換・分割・計算列などを行うと記録されます)。";
    } catch (e) { toast(e.message, true); }
  };

  $("#recipe-save").onclick = async () => {
    if (!grid.fileId) return toast("先にファイルを読み込んでください", true);
    const name = $("#recipe-name").value.trim();
    if (!name) return toast("レシピ名を入力してください", true);
    try {
      const r = await postJson("/api/recipes", { name, file_id: grid.fileId });
      toast(`レシピ「${name}」を保存しました(${r.count}操作)。別のファイルに再適用できます。`);
      refreshRecipes();
    } catch (e) { toast(e.message, true); }
  };

  $("#recipe-apply").onclick = async () => {
    if (!grid.fileId) return toast("先にファイルを読み込んでください", true);
    const name = $("#recipe-select").value;
    if (!name) return toast("適用するレシピを選択してください", true);
    if (!await ensureSaved()) return;
    try {
      const r = await postJson(`/api/files/${grid.fileId}/apply-recipe`, { name });
      $("#recipe-log").innerHTML = "<b>適用結果:</b><br>" +
        r.logs.map((l, i) => `${i + 1}. ${escapeHtml(l)}`).join("<br>");
      toast(`レシピ「${name}」を適用しました(${r.logs.length}操作)`);
      await loadGridFile(grid.fileId);
    } catch (e) { toast(e.message, true); }
  };

  // ---- 匿名化
  const anonSpec = {};
  apiJson("/api/anonymize-modes").then(({ modes }) => {
    $("#anon-mode").innerHTML = modes.map(m =>
      `<option value="${m.id}">${escapeHtml(m.label)}</option>`).join("");
  }).catch(() => {});

  function renderAnonSpec() {
    const entries = Object.entries(anonSpec);
    $("#anon-spec").textContent = entries.length
      ? "対象: " + entries.map(([c, m]) => `${c}=${m}`).join("、")
      : "(対象未指定)";
  }
  renderAnonSpec();

  $("#anon-add").onclick = () => {
    const col = $("#anon-col").value;
    if (!col) return toast("列を選択してください", true);
    anonSpec[col] = $("#anon-mode").value;
    renderAnonSpec();
  };

  $("#anon-do").onclick = async () => {
    if (!Object.keys(anonSpec).length) return toast("「＋対象に追加」で匿名化する列を指定してください", true);
    if (!await ensureSaved()) return;
    try {
      const info = await postJson(`/api/files/${grid.fileId}/anonymize`, { spec: anonSpec });
      toast(`匿名化ファイルを作成しました(${info.changed}セル変更)。ファイル一覧から開けます。`);
      Object.keys(anonSpec).forEach(k => delete anonSpec[k]);
      renderAnonSpec();
      const { refreshFileList } = await import("/static/app.js");
      refreshFileList();
    } catch (e) { toast(e.message, true); }
  };

  renderGrid();
}
