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
function renderGrid() {
  const container = $("#grid-container");
  if (!grid.fileId) { container.innerHTML = `<p class="hint">ファイルを選択して「読み込み」を押してください。</p>`; return; }
  const start = grid.page * PAGE_SIZE;
  const rows = grid.rows.slice(start, start + PAGE_SIZE);
  const head = `<tr><th></th>` + grid.columns.map((c, i) =>
    `<th data-col="${i}"><span class="colname" title="ダブルクリックで列名変更">${escapeHtml(c)}</span>` +
    `<span class="delcol" data-col="${i}" title="列を削除">×</span></th>`).join("") + `</tr>`;
  const body = rows.map((r, ri) => {
    const rowIdx = start + ri;
    return `<tr data-row="${rowIdx}"><td class="rowsel"><input type="checkbox" class="rowcheck" data-row="${rowIdx}"></td>` +
      r.map((v, ci) =>
        `<td><input value="${escapeHtml(v)}" data-row="${rowIdx}" data-col="${ci}"></td>`).join("") + `</tr>`;
  }).join("");
  container.innerHTML = `<table><thead>${head}</thead><tbody>${body}</tbody></table>`;

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
  const totalPages = Math.max(1, Math.ceil(grid.rows.length / PAGE_SIZE));
  if (grid.page >= totalPages) {  // 行削除等でページが範囲外になったら戻す
    grid.page = totalPages - 1;
    renderGrid();
    return;
  }
  $("#grid-page-info").textContent = `ページ ${grid.page + 1} / ${totalPages}`;
}

function fillColumnSelectors() {
  const opts = grid.columns.map(c => `<option>${escapeHtml(c)}</option>`).join("");
  $("#sr-column").innerHTML = `<option value="">全列</option>` + opts;
  $("#clean-column").innerHTML = opts;
  $("#val-keys").innerHTML = opts;
  $("#val-required").innerHTML = opts;
  $("#val-format-col").innerHTML = `<option value="">(列)</option>` + opts;
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

  $("#val-do").onclick = async () => {
    if (!await ensureSaved()) return;
    const formats = {};
    if ($("#val-format-col").value) formats[$("#val-format-col").value] = $("#val-format-kind").value;
    try {
      const r = await postJson(`/api/files/${grid.fileId}/validate`, {
        key_columns: [...$("#val-keys").selectedOptions].map(o => o.value),
        required_columns: [...$("#val-required").selectedOptions].map(o => o.value),
        formats,
      });
      $("#val-result").innerHTML = r.count === 0
        ? `<p>✅ 問題は見つかりませんでした。</p>`
        : `<p class="issue">⚠ ${r.count}件の問題:</p>` + r.issues.slice(0, 200).map(i =>
            `<div class="issue">${i.row}行目 [${escapeHtml(i.column)}] ${escapeHtml(i.message)}</div>`).join("");
    } catch (e) { toast(e.message, true); }
  };

  renderGrid();
}
