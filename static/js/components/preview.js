/**
 * 预览：iframe 实时渲染 + 页码指示 + 缩放。
 */

import { store } from "../store.js";
import { api, postRender } from "../api.js";
import { toastError } from "./toast.js";
import { injectPaginationOverlay } from "./pagination.js";

const frame = () => document.getElementById("previewFrame");
const stage = () => document.getElementById("previewStage");
const scroll = () => document.getElementById("previewScroll");

let renderSeq = 0;

/** 请求一次渲染（防抖由 store 调度）。 */
export async function doRenderPreview() {
  const doc = store.doc;
  if (!doc) return;
  const seq = ++renderSeq;
  try {
    const html = await postRender(doc);
    if (seq !== renderSeq) return; // 已有更新的渲染请求
    const f = frame();
    f.srcdoc = html;
  } catch (e) {
    if (seq === renderSeq) {
      document.getElementById("previewEmpty").hidden = false;
      document.getElementById("previewEmpty").textContent = "预览渲染失败：" + e.message;
    }
  }
}

/** iframe 加载完成后：调整高度、按缩放变换、分页模式下注入覆盖层。 */
export function bindPreviewFrame() {
  const f = frame();
  f.addEventListener("load", () => {
    try {
      const doc = f.contentDocument;
      if (!doc?.body) return;
      const h = Math.max(doc.body.scrollHeight, doc.documentElement.scrollHeight, 1123);
      f.style.height = h + 4 + "px";
      applyZoom();
      if (store.state.paginationMode) injectPaginationOverlay(f);
      // 首屏渲染后测一次页码
      schedulePageInfo(600);
    } catch {
      /* 跨域或尚未就绪 */
    }
  });
}

/* ---------------- 缩放 ---------------- */

function applyZoom() {
  const z = store.state.zoom;
  const f = frame();
  stage().style.transform = z === 1 ? "" : `scale(${z})`;
  stage().style.width = `${794 * z}px`;
  // 缩放后保持可视：用负边距抵消 transform 占位
  const h = parseFloat(f.style.height) || 1123;
  stage().style.height = `${h * z}px`;
  stage().style.marginBottom = h > 0 ? `${-(h * (1 - z)) + 0}px` : "";
  document.getElementById("zoomVal").textContent = `${Math.round(z * 100)}%`;
}

export function bindZoomButtons() {
  document.getElementById("zoomIn").addEventListener("click", () => {
    store.setZoom(store.state.zoom + 0.1);
  });
  document.getElementById("zoomOut").addEventListener("click", () => {
    store.setZoom(store.state.zoom - 0.1);
  });
}

/* ---------------- 页码信息 ---------------- */

let pageInfoTimer = null;

export function schedulePageInfo(delay = 900) {
  clearTimeout(pageInfoTimer);
  pageInfoTimer = setTimeout(() => {
    pageInfoTimer = null;
    refreshPageInfo();
  }, delay);
}

export async function refreshPageInfo() {
  const doc = store.doc;
  if (!doc) return;
  try {
    const info = await api.pageInfo(doc);
    store.setPageInfo(info);
  } catch (e) {
    // 分页测量失败不打扰用户（预览仍可用）
    console.warn("page-info failed:", e.message);
  }
}

export function renderPageInfo() {
  const badge = document.getElementById("pageBadge");
  const warn = document.getElementById("pageWarn");
  const info = store.state.pageInfo;
  if (!info) {
    badge.textContent = "测量中…";
    badge.classList.remove("over");
    warn.textContent = "";
    return;
  }
  const n = info.pageCount || 1;
  badge.textContent = `共 ${n} 页`;
  badge.classList.toggle("over", n > 1);

  const warns = [];
  if (info.warnings?.length) warns.push(...info.warnings);
  const straddlers = (info.sections || []).filter((s) => s.straddles && !s.tallerThanPage);
  if (straddlers.length) {
    warns.push(`${straddlers.length} 个区块跨页，可在「分页」模式调整`);
  }
  warn.textContent = warns.slice(0, 2).join("；");
  warn.title = warns.join("\n");
}

/* ---------------- 刷新按钮 ---------------- */

export function bindPreviewActions() {
  document.getElementById("btnRefreshPreview").addEventListener("click", () => {
    doRenderPreview();
    refreshPageInfo();
  });
}
