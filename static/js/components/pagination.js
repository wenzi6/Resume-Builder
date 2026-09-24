/**
 * 分页编辑模式。
 *
 * 进入后：向预览 iframe 注入
 *   1. 每页底部的虚线分页线（位置 = n × pageHeightPx）
 *   2. 每个区块右上角的「在此分页」按钮（切换 doc.pageBreaks）
 * 支持一键应用后端建议分页点 / 清除全部。
 */

import { store } from "../store.js";
import { api } from "../api.js";
import { toast, toastSuccess } from "./toast.js";

const OVERLAY_STYLE = `
.rs-pb-lines { position: absolute; inset: 0; pointer-events: none; z-index: 9990; }
.rs-pb-line {
  position: absolute; left: 0; right: 0; height: 0;
  border-top: 1.5px dashed #0f766e;
}
.rs-pb-line span {
  position: absolute; right: 2px; top: -13px;
  font: 600 9px/1 -apple-system, "Microsoft YaHei", sans-serif;
  color: #0f766e; background: #ecfdf5; border: 1px solid #a7f3d0;
  border-radius: 3px; padding: 2px 5px;
}
.rsec { position: relative; }
.rs-pb-btn {
  position: absolute; top: 0; right: -2px; z-index: 9995;
  font: 600 10px/1 -apple-system, "Microsoft YaHei", sans-serif;
  color: #0f766e; background: #fff; border: 1px solid #0f766e;
  border-radius: 4px; padding: 3px 7px; cursor: pointer;
  opacity: 0; transition: opacity 0.15s;
  box-shadow: 0 1px 4px rgb(15 23 42 / 0.15);
}
.rsec:hover .rs-pb-btn { opacity: 1; }
.rs-pb-btn.on { background: #0f766e; color: #fff; opacity: 1; }
.rs-pb-banner {
  position: sticky; top: 0; z-index: 9999;
  background: #0f766e; color: #fff;
  font: 600 11px/1.4 -apple-system, "Microsoft YaHei", sans-serif;
  padding: 6px 10px; border-radius: 0 0 6px 6px;
  display: flex; gap: 10px; align-items: center; justify-content: space-between;
}
.rs-pb-banner b { color: #d1fae5; }
`;

/** 向 iframe 注入分页覆盖层（iframe load 时或进入模式时调用）。 */
export function injectPaginationOverlay(frameEl) {
  const doc = frameEl?.contentDocument;
  if (!doc) return;
  cleanupPaginationOverlay(frameEl);

  const style = doc.createElement("style");
  style.id = "rs-pb-style";
  style.textContent = OVERLAY_STYLE;
  doc.head.appendChild(style);

  const sheet = doc.querySelector(".r-sheet") || doc.body;
  if (getComputedStyle(sheet).position === "static") sheet.style.position = "relative";

  // ---- 分页线 ----
  const info = store.state.pageInfo;
  if (info?.pageHeightPx && info.pageCount > 1) {
    const lines = doc.createElement("div");
    lines.className = "rs-pb-lines";
    for (let p = 1; p < info.pageCount; p++) {
      const line = doc.createElement("div");
      line.className = "rs-pb-line";
      line.style.top = `${p * info.pageHeightPx}px`;
      const label = doc.createElement("span");
      label.textContent = `第 ${p} 页 / 第 ${p + 1} 页`;
      line.appendChild(label);
      lines.appendChild(line);
    }
    sheet.appendChild(lines);
  }

  // ---- 每个区块的「在此分页」按钮 ----
  const breaks = new Set(store.doc?.pageBreaks || []);
  sheet.querySelectorAll(".rsec[data-section]").forEach((sec) => {
    const key = sec.getAttribute("data-section");
    if (!key) return;
    const btn = doc.createElement("button");
    btn.type = "button";
    btn.className = "rs-pb-btn" + (breaks.has(key) ? " on" : "");
    btn.textContent = breaks.has(key) ? "✓ 已分页" : "在此分页";
    btn.title = "在该区块前分页";
    btn.addEventListener("click", () => toggleBreak(key, frameEl));
    sec.appendChild(btn);
  });
}

function cleanupPaginationOverlay(frameEl) {
  const doc = frameEl?.contentDocument;
  if (!doc) return;
  doc.getElementById("rs-pb-style")?.remove();
  doc.querySelectorAll(".rs-pb-lines, .rs-pb-btn, .rs-pb-banner").forEach((n) => n.remove());
}

/** 切换某区块的手动分页。 */
async function toggleBreak(key, frameEl) {
  const doc = store.doc;
  doc.pageBreaks = Array.isArray(doc.pageBreaks) ? doc.pageBreaks : [];
  const idx = doc.pageBreaks.indexOf(key);
  if (idx >= 0) doc.pageBreaks.splice(idx, 1);
  else doc.pageBreaks.push(key);
  store.touch({ pageInfo: true });
  // 局部更新按钮状态，避免整页重渲染打断操作
  try {
    const secDoc = frameEl?.contentDocument;
    const sec = secDoc?.querySelector(`.rsec[data-section="${CSS.escape(key)}"]`);
    const btn = sec?.querySelector(".rs-pb-btn");
    if (btn) {
      const on = doc.pageBreaks.includes(key);
      btn.classList.toggle("on", on);
      btn.textContent = on ? "✓ 已分页" : "在此分页";
    }
  } catch {
    /* ignore */
  }
}

/* ---------------- 模式进入 / 退出 ---------------- */

export function bindPaginationControls() {
  const btn = document.getElementById("btnPagination");
  btn.addEventListener("click", () => {
    if (store.state.paginationMode) exitPaginationMode();
    else enterPaginationMode();
  });
  document.getElementById("btnExitPagination").addEventListener("click", exitPaginationMode);
  document.getElementById("btnApplyBreaks").addEventListener("click", applySuggestedBreaks);
  document.getElementById("btnClearBreaks").addEventListener("click", clearBreaks);
}

export async function enterPaginationMode() {
  store.setPaginationMode(true);
  document.getElementById("paginationBar").hidden = false;
  document.getElementById("btnPagination").classList.add("btn-primary");
  // 确保有最新测量数据
  if (!store.state.pageInfo) {
    const { refreshPageInfo } = await import("./preview.js");
    await refreshPageInfo();
  }
  injectPaginationOverlay(document.getElementById("previewFrame"));
  toast("已进入分页编辑模式");
}

export function exitPaginationMode() {
  store.setPaginationMode(false);
  document.getElementById("paginationBar").hidden = true;
  document.getElementById("btnPagination").classList.remove("btn-primary");
  cleanupPaginationOverlay(document.getElementById("previewFrame"));
  store.saveNow();
  toastSuccess("已退出分页编辑模式");
}

async function applySuggestedBreaks() {
  try {
    const { pageBreaks } = await api.autoPagebreaks(store.doc);
    if (!pageBreaks?.length) {
      toast("没有需要的分页建议（当前排版已合理或内容不足）");
      return;
    }
    store.doc.pageBreaks = pageBreaks;
    store.touch({ pageInfo: true });
    // 重新渲染以注入 .r-pagebreak，再重建覆盖层
    const { doRenderPreview } = await import("./preview.js");
    await doRenderPreview();
    toastSuccess(`已应用 ${pageBreaks.length} 个建议分页点`);
  } catch (e) {
    toast("应用失败：" + e.message, "error");
  }
}

async function clearBreaks() {
  store.doc.pageBreaks = [];
  store.touch({ pageInfo: true });
  const { doRenderPreview } = await import("./preview.js");
  await doRenderPreview();
  toastSuccess("已清除全部分页");
}
