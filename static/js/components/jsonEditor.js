// @ts-check
/**
 * JSON 编辑弹窗 + 导入弹窗。
 */

import { store } from "../store.js";
import { api } from "../api.js";
import { toast, toastSuccess, toastError } from "./toast.js";
import { renderForm } from "./form.js";
import { renderSectionTree } from "./sidebar.js";
import { renderDesignPanel, syncDesignValues } from "./designPanel.js";
import { doRenderPreview, refreshPageInfo } from "./preview.js";

/* ---------------- JSON 编辑器 ---------------- */

export function openJsonEditor() {
  const overlay = document.getElementById("jsonOverlay");
  const ta = document.getElementById("jsonText");
  ta.value = JSON.stringify(store.doc, null, 2);
  overlay.hidden = false;
  ta.focus();
}

export function closeJsonEditor() {
  document.getElementById("jsonOverlay").hidden = true;
}

export async function applyJson() {
  const ta = document.getElementById("jsonText");
  let parsed;
  try {
    parsed = JSON.parse(ta.value);
  } catch (e) {
    toastError("JSON 解析失败：" + e.message);
    return;
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    toastError("顶层必须是 JSON 对象");
    return;
  }
  const doc = store.doc;
  // 保留 id，其余整体替换
  const merged = { ...parsed, id: doc.id };
  store.setDocument(merged);
  closeJsonEditor();
  renderAll();
  toastSuccess("已应用 JSON 修改");
}

/* ---------------- 导入 ---------------- */

export function openImportDialog() {
  document.getElementById("importOverlay").hidden = false;
}

export function closeImportDialog() {
  document.getElementById("importOverlay").hidden = true;
}

export function bindImportDialog() {
  const overlay = document.getElementById("importOverlay");
  document.getElementById("btnImport").addEventListener("click", openImportDialog);
  document.getElementById("btnCloseImport").addEventListener("click", () => (overlay.hidden = true));
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) overlay.hidden = true;
  });

  // 子页签
  overlay.querySelectorAll(".import-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      overlay.querySelectorAll(".import-tab").forEach((t) => t.classList.toggle("active", t === tab));
      overlay.querySelectorAll(".import-pane").forEach((p) => (p.hidden = p.id !== "import" + cap(tab.dataset.import)));
    });
  });

  document.getElementById("importJsonFile").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    await handleImport(async () => {
      const { document: doc } = await api.importJson(file);
      return doc;
    }, `已导入 JSON「${file.name}」`);
    e.target.value = "";
  });

  document.getElementById("importPdfFile").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    await handleImport(async () => {
      const { document: doc, pdf } = await api.importPdf(file);
      return { doc, extra: pdf };
    }, `已按原格式对照导入「${file.name}」`, (pdf) =>
      pdf ? `右侧「原始格式」保留原 PDF，左侧模块可编辑（共 ${pdf.pages || "?"} 页）` : "");
    e.target.value = "";
  });

  document.getElementById("importTplFile").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const { template } = await api.importTemplate(file);
      const { templates } = await api.templates();
      store.setTemplates(templates);
      overlay.hidden = true;
      toastSuccess(`模板「${template?.name || file.name}」导入成功`);
    } catch (err) {
      toastError("模板导入失败：" + err.message);
    }
    e.target.value = "";
  });
}

function cap(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** 导入JSON/PDF：保存为新文档并打开。 */
async function handleImport(fn, successMsg, hintFn) {
  try {
    const result = await fn();
    const imported = result?.doc || result;
    const extra = result?.extra;
    if (!imported) throw new Error("返回数据为空");
    // 保存为服务端文档（导入的文档带新 id，直接作为新文档保存）
    if (store.dirty) await store.saveNow();
    const saved = await saveNewDocument(imported);
    store.setDocument(saved);
    renderAll();
    const { renderDocList } = await import("./sidebar.js");
    renderDocList(document.getElementById("docList"));
    document.getElementById("importOverlay").hidden = true;
    toastSuccess(successMsg);
    if (hintFn) {
      const hint = hintFn(extra);
      if (hint) toast(hint, "info", 6000);
    }
  } catch (e) {
    toastError("导入失败：" + e.message);
  }
}

async function saveNewDocument(doc) {
  // import 返回的文档已含 id，直接 PUT 到该 id 即完成落库
  const { document: saved } = await api.saveDocument(doc.id, doc);
  return saved;
}

/* ---------------- 统一重渲染 ---------------- */

export function renderAll() {
  renderForm(document.getElementById("formArea"));
  renderSectionTree(document.getElementById("sectionTree"));
  renderDesignPanel(document.getElementById("pane-design"));
  syncDesignValues();
  doRenderPreview();
  refreshPageInfo();
}
