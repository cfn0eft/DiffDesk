// 多対多(親A - 中間 - 親B)の移行検証タブ。
import { $, $$, api, apiJson, downloadResponse, escapeHtml, postJson, toast } from "/static/common.js";

let jxFiles = [];  // /api/files の結果

async function refreshJxFiles() {
  try {
    const { files } = await apiJson("/api/files");
    jxFiles = files;
    $$(".jx-file").forEach(sel => {
      const cur = sel.value;
      sel.innerHTML = `<option value="">(選択)</option>` +
        files.map(f =>
          `<option value="${f.file_id}">${escapeHtml(f.filename)} (${f.total_rows}行)</option>`
        ).join("");
      if (cur && files.some(f => f.file_id === cur)) sel.value = cur;
      fillColumns(sel);
    });
  } catch (e) { toast(e.message, true); }
}

function columnsOf(fileId) {
  return jxFiles.find(f => f.file_id === fileId)?.columns ?? [];
}

const jxDesired = {};  // 移行定義JSONから読み込んだ希望値(列が現れたら自動選択)

function fillSelect(sel, columns, { optional = false } = {}) {
  const cur = sel.value;
  sel.innerHTML = (optional ? `<option value="">(${sel.id === "jx-required" ? "なし" : "確認しない"})</option>` : "") +
    columns.map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("");
  const want = jxDesired[sel.id];
  if (want && columns.includes(want)) sel.value = want;
  else if (cur && columns.includes(cur)) sel.value = cur;
}

function fillColumns(fileSel) {
  const cols = columnsOf(fileSel.value);
  switch (fileSel.id) {
    case "jx-file-source":
      fillSelect($("#jx-a-source"), cols);
      fillSelect($("#jx-b-source"), cols);
      fillSelect($("#jx-required"), cols, { optional: true });
      break;
    case "jx-file-a":
      fillSelect($("#jx-a-ext"), cols);
      break;
    case "jx-file-b":
      fillSelect($("#jx-b-ext"), cols);
      break;
    case "jx-file-j":
      fillSelect($("#jx-j-key"), cols);
      fillSelect($("#jx-ref-a"), cols, { optional: true });
      fillSelect($("#jx-ref-b"), cols, { optional: true });
      break;
  }
}

function jxRequest() {
  const ids = ["jx-file-source", "jx-file-a", "jx-file-b", "jx-file-j"];
  if (ids.some(id => !$("#" + id).value)) {
    toast("4つのファイル(移行元・親A・親B・中間)をすべて選択してください。", true);
    return null;
  }
  return {
    file_source: $("#jx-file-source").value,
    file_a: $("#jx-file-a").value,
    file_b: $("#jx-file-b").value,
    file_j: $("#jx-file-j").value,
    config: {
      a_source_col: $("#jx-a-source").value,
      b_source_col: $("#jx-b-source").value,
      a_ext_col: $("#jx-a-ext").value,
      b_ext_col: $("#jx-b-ext").value,
      j_key_col: $("#jx-j-key").value,
      key_template: $("#jx-template").value.trim() || "{A}-{B}",
      b_regex_pattern: $("#jx-b-pattern").value,
      b_regex_replacement: $("#jx-b-repl").value,
      required_col: $("#jx-required").value,
      j_ref_a_col: $("#jx-ref-a").value,
      j_ref_b_col: $("#jx-ref-b").value,
    },
  };
}

const CAUSE_JA = {
  missing_a: "親Aの外部IDが存在しない",
  missing_b: "親Bの外部IDが存在しない",
  missing_both: "親A・親Bの両方が存在しない",
  parents_ok: "両親は存在(中間だけ未取込)",
};
const CAUSE_CLS = { missing_a: "jx-c-a", missing_b: "jx-c-b",
                    missing_both: "jx-c-both", parents_ok: "jx-c-j" };

function macroRow(step, extraNote = "") {
  const mark = step.passed
    ? `<span class="ok-mark">✔</span>`
    : `<span class="ng-mark">✖</span>`;
  const notes = [];
  if (step.missing_count) {
    notes.push(`欠落${step.missing_count}件(例: ${step.missing.slice(0, 5).map(escapeHtml).join(", ")})`);
  }
  if (step.extra_count) {
    notes.push(`想定外${step.extra_count}件(例: ${step.extra.slice(0, 5).map(escapeHtml).join(", ")})`);
  }
  if (step.dup_actual) notes.push(`抽出側キー重複${step.dup_actual}件`);
  if (extraNote) notes.push(extraNote);
  return `<tr><td>${mark}</td><td><b>${escapeHtml(step.name)}</b></td>` +
    `<td>${step.expected}</td><td>${step.actual}</td>` +
    `<td>${step.diff > 0 ? "+" : ""}${step.diff}</td>` +
    `<td class="hint">${notes.join(" / ") || "—"}</td></tr>`;
}

function renderJxResult(r) {
  $("#jx-result").hidden = false;
  const banner = $("#jx-banner");
  banner.className = r.passed ? "ok" : "ng";
  banner.textContent = r.passed
    ? "✔ 移行OK — 親A・親B・中間オブジェクトすべて期待どおりです"
    : "✖ 要確認 — 期待値と実績に差があります(下の内訳と孤立分析を確認)";

  const j = r.junction;
  const skipNote =
    `スキップ: 必須列空白${j.skipped_required}件・キー成分空白${j.skipped_empty_pair}件`;
  $("#jx-macro").innerHTML =
    `<table><thead><tr><th>判定</th><th>ステップ</th><th>期待値(ユニーク)</th>` +
    `<th>実績件数</th><th>差</th><th>内訳</th></tr></thead><tbody>` +
    macroRow(r.parent_a) + macroRow(r.parent_b) + macroRow(j, skipNote) +
    `</tbody></table>` +
    (r.ref_errors
      ? `<p class="hint">参照整合: 親A参照エラー <b>${r.ref_errors.bad_ref_a}</b>件 / ` +
        `親B参照エラー <b>${r.ref_errors.bad_ref_b}</b>件</p>`
      : "");

  const o = r.orphans;
  $("#jx-orphan-card").hidden = !o.total;
  $("#jx-export").hidden = !o.total;
  if (o.total) {
    const order = ["missing_a", "missing_b", "missing_both", "parents_ok"];
    const bar = order.map(c => o.causes[c]
      ? `<div class="${CAUSE_CLS[c]}" style="width:${(o.causes[c] / o.total) * 100}%" ` +
        `title="${CAUSE_JA[c]}: ${o.causes[c]}件"></div>` : "").join("");
    const legend = order.filter(c => o.causes[c]).map(c =>
      `<span><i class="${CAUSE_CLS[c]}"></i>${CAUSE_JA[c]}: <b>${o.causes[c]}</b>件</span>`
    ).join("");
    const bn = o.bottleneck
      ? `<p><b>ボトルネック: ${CAUSE_JA[o.bottleneck]}</b>(未取込${o.total}件のうち最多)</p>`
      : "";
    const sample =
      `<table><thead><tr><th>複合キー</th><th>親Aキー</th><th>親Bキー</th><th>原因</th></tr></thead><tbody>` +
      o.samples.slice(0, 30).map(s =>
        `<tr><td>${escapeHtml(s.key)}</td><td>${escapeHtml(s.a)}</td>` +
        `<td>${escapeHtml(s.b)}</td><td>${CAUSE_JA[s.cause]}</td></tr>`).join("") +
      `</tbody></table>` +
      (o.total > 30 ? `<p class="hint">全${o.total}件は「未取込一覧CSV」で出力できます。</p>` : "");
    $("#jx-orphans").innerHTML =
      bn + `<div class="jx-causebar">${bar}</div>` +
      `<div class="jx-legend">${legend}</div>` + sample;
  }
}

$("#jx-run").onclick = async () => {
  const req = jxRequest();
  if (!req) return;
  try {
    const r = await postJson("/api/junction-verify", req);
    renderJxResult(r);
    toast("多対多検証を実行しました。");
  } catch (e) { toast(e.message, true); }
};

$("#jx-export").onclick = async () => {
  const req = jxRequest();
  if (!req) return;
  try {
    const res = await api("/api/junction-verify/orphans", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...req, encoding: "utf-8-sig" }),
    });
    await downloadResponse(res, "未取込一覧.csv");
  } catch (e) { toast(e.message, true); }
};

// 移行定義JSON(仕様書)から設定を自動入力
$("#jx-spec-btn").onclick = () => $("#jx-spec-input").click();
$("#jx-spec-input").onchange = async () => {
  const files = [...$("#jx-spec-input").files];
  $("#jx-spec-input").value = "";
  if (!files.length) return;
  try {
    const specs = [];
    for (const f of files) specs.push(JSON.parse(await f.text()));
    const r = await postJson("/api/migration-spec/junction", { specs });
    const s = r.settings;
    $("#jx-template").value = s.key_template;
    $("#jx-b-pattern").value = s.b_regex_pattern;
    $("#jx-b-repl").value = s.b_regex_replacement;
    // セレクトは希望値として保持し、該当列があるファイルを選んだ時点で自動選択
    const map = {
      "jx-a-source": s.a_source_col, "jx-b-source": s.b_source_col,
      "jx-required": s.required_col,
      "jx-a-ext": s.a_ext_col, "jx-b-ext": s.b_ext_col,
      "jx-j-key": s.j_key_col,
      "jx-ref-a": s.j_ref_a_col, "jx-ref-b": s.j_ref_b_col,
    };
    for (const [id, val] of Object.entries(map)) {
      if (!val) continue;
      jxDesired[id] = val;
      const sel = $("#" + id);
      if ([...sel.options].some(o => o.value === val)) sel.value = val;
    }
    $("#jx-spec-info").textContent =
      `定義「${r.object || "中間オブジェクト"}」を読み込みました。` +
      `ファイルを選ぶと該当する列が自動選択されます。`;
    toast("移行定義JSONから設定を読み込みました。" +
      (r.warnings.length ? " 注意: " + r.warnings.join(" / ") : ""),
      r.warnings.length > 0);
  } catch (e) { toast(`定義JSONの読み込みに失敗: ${e.message}`, true); }
};

$("#jx-refresh").onclick = refreshJxFiles;
$$(".jx-file").forEach(sel => sel.onchange = () => fillColumns(sel));
// タブを開いたときにファイル一覧を最新化
document.querySelector('#tabs button[data-tab="tab-junction"]')
  .addEventListener("click", refreshJxFiles);
