// 見比べビューア: 2ファイルを並べて目視確認するだけの画面(編集・照合なし)。
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

let toastTimer = null;
function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 4000);
}

const MAX_ROWS = 5000;
const panes = {
  l: { data: null, filter: "" },
  r: { data: null, filter: "" },
};

async function loadFileList() {
  try {
    const r = await fetch("/api/files");
    const { files } = await r.json();
    for (const side of ["l", "r"]) {
      const sel = $(`select[data-side="${side}"]`);
      const cur = sel.value;
      sel.innerHTML = `<option value="">(${side === "l" ? "左" : "右"}: ファイルを選択)</option>` +
        files.filter(f => f.total_rows > 0 || f.columns.length)
          .map(f => `<option value="${f.file_id}">${escapeHtml(f.filename)} (${f.total_rows}行)</option>`)
          .join("");
      if (cur && files.some(f => f.file_id === cur)) sel.value = cur;
    }
    if (!files.length) {
      toast("読み込み済みのファイルがありません。本体アプリの「1. ファイル読み込み」でファイルを読み込んでください。");
    }
  } catch {
    toast("ファイル一覧を取得できませんでした。本体アプリ(サーバー)が起動しているか確認してください。");
  }
}

async function loadPane(side) {
  const p = panes[side];
  const fileId = $(`select[data-side="${side}"]`).value;
  if (!fileId) {
    p.data = null;
    renderPane(side);
    return;
  }
  try {
    const r = await fetch(`/api/files/${fileId}?limit=${MAX_ROWS}`);
    if (!r.ok) throw new Error();
    p.data = await r.json();
    renderPane(side);
  } catch {
    toast("ファイルを読み込めませんでした。一覧を更新して選び直してください。");
  }
}

function renderPane(side) {
  const p = panes[side];
  const table = $(`.cmp-pane[data-side="${side}"] table`);
  const info = $(`.cmp-info[data-side="${side}"]`);
  if (!p.data) {
    table.innerHTML = "";
    info.textContent = "";
    return;
  }
  const q = p.filter.toLowerCase();
  const rows = [];
  p.data.rows.forEach((row, i) => {
    if (!q || row.some(v => v.toLowerCase().includes(q))) rows.push([i + 1, row]);
  });
  const mark = v => {
    const e = escapeHtml(v);
    if (!q) return e;
    const i = v.toLowerCase().indexOf(q);
    if (i < 0) return e;
    return escapeHtml(v.slice(0, i)) + "<mark>" + escapeHtml(v.slice(i, i + q.length)) +
      "</mark>" + escapeHtml(v.slice(i + q.length));
  };
  table.innerHTML =
    `<thead><tr><th class="rownum">#</th>` +
    p.data.columns.map(c => `<th title="${escapeHtml(c)}">${escapeHtml(c)}</th>`).join("") +
    `</tr></thead><tbody>` +
    rows.map(([n, row]) =>
      `<tr data-n="${n}"><td class="rownum">${n}</td>` +
      row.map(v => `<td title="${escapeHtml(v)}">${mark(v)}</td>`).join("") + `</tr>`
    ).join("") + `</tbody>`;
  const total = p.data.total_rows;
  const cut = total > p.data.rows.length ? `(先頭${p.data.rows.length}行のみ表示)` : "";
  info.textContent = q
    ? `${rows.length} / ${p.data.rows.length}行 ${cut}`
    : `${total}行 ${cut}`;

  // 行ハイライト連動(同じ行番号を反対側でも強調)
  table.querySelectorAll("tbody tr").forEach(tr => {
    tr.onmouseenter = () => setHover(+tr.dataset.n, true);
    tr.onmouseleave = () => setHover(+tr.dataset.n, false);
  });
}

function setHover(n, on) {
  if (!$("#sync-hover").checked) return;
  $$(`.cmp-pane tr[data-n="${n}"]`).forEach(tr => tr.classList.toggle("hl", on));
}

// 縦スクロール同期
{
  const pl = $(`.cmp-pane[data-side="l"]`);
  const pr = $(`.cmp-pane[data-side="r"]`);
  let lock = false;
  const sync = (src, dst) => () => {
    if (lock || !$("#sync-scroll").checked) return;
    lock = true;
    dst.scrollTop = src.scrollTop;
    requestAnimationFrame(() => { lock = false; });
  };
  pl.addEventListener("scroll", sync(pl, pr));
  pr.addEventListener("scroll", sync(pr, pl));
}

let filterTimer = null;
for (const side of ["l", "r"]) {
  $(`select[data-side="${side}"]`).onchange = () => loadPane(side);
  $(`input[data-side="${side}"]`).oninput = e => {
    clearTimeout(filterTimer);
    filterTimer = setTimeout(() => {
      panes[side].filter = e.target.value.trim();
      renderPane(side);
    }, 200);
  };
}
$("#reload-files").onclick = loadFileList;
$("#font-size").onchange = e => {
  document.body.className = e.target.value;
};

loadFileList();
