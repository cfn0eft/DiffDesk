// 共有状態とユーティリティ
export const state = {
  fileA: null,          // {file_id, filename, columns}
  fileB: null,
  mapping: [],          // [{col_a, col_b, is_key, sf_field}]
  filtersA: [],         // [{column, op, value}]
  filtersB: [],
  diff: null,           // {diff_id, summary, ...}
  mergeChoices: {},     // `${JSON.stringify(key)}|${col_a}` -> "b"
};

export function $(sel) { return document.querySelector(sel); }
export function $$(sel) { return [...document.querySelectorAll(sel)]; }

export function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

let toastTimer = null;
export function toast(msg, isError = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.className = isError ? "error" : "";
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, isError ? 6000 : 3000);
}

export async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body.error) {
        message = body.error.message;
        if (body.error.locations) {
          message += " " + body.error.locations.slice(0, 3)
            .map(l => `(${l.row}行目[${l.column}]「${l.char}」)`).join(" ");
        }
      } else if (body.detail) {
        message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch { /* JSONでない */ }
    throw new Error(message);
  }
  return res;
}

export async function apiJson(path, options = {}) {
  return (await api(path, options)).json();
}

export function postJson(path, body) {
  return apiJson(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function downloadResponse(res, fallbackName) {
  const cd = res.headers.get("content-disposition") || "";
  let filename = fallbackName;
  const m = cd.match(/filename\*=UTF-8''([^;]+)/);
  if (m) filename = decodeURIComponent(m[1]);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// 汎用ダイアログ: bodyHtmlを表示し、[data-ok]クリックでresolve(true)
export function showDialog(bodyHtml) {
  return new Promise(resolve => {
    const dlg = $("#dialog");
    dlg.innerHTML = bodyHtml +
      `<div class="toolbar"><button data-cancel>キャンセル</button>` +
      `<button data-ok class="primary">OK</button></div>`;
    dlg.querySelector("[data-ok]").onclick = () => { dlg.close(); resolve(true); };
    dlg.querySelector("[data-cancel]").onclick = () => { dlg.close(); resolve(false); };
    dlg.oncancel = () => resolve(false);
    dlg.showModal();
  });
}

export function renderPreviewTable(container, columns, rows, totalRows) {
  const head = columns.map(c => `<th>${escapeHtml(c)}</th>`).join("");
  const body = rows.map(r =>
    `<tr>${r.map(c => `<td>${escapeHtml(c)}</td>`).join("")}</tr>`).join("");
  container.innerHTML =
    `<div class="hint">全${totalRows}行 (先頭${rows.length}行を表示)</div>` +
    `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}
