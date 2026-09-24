/**
 * 入口：初始化、顶栏、模板选择、快捷键、全局装配。
 */

import { store } from "./store.js";
import { api } from "./api.js";
import { toast, toastSuccess, toastError } from "./components/toast.js";
import { renderForm, scrollToSection } from "./components/form.js";
import {
  renderSectionTree,
  renderDocList,
  openSectionDialog,
  closeSectionDialog,
  saveSectionFromDialog,
  bindConfirmDialog,
  confirmDialog,
} from "./components/sidebar.js";
import { renderDesignPanel } from "./components/designPanel.js";
import {
  doRenderPreview,
  bindPreviewFrame,
  bindZoomButtons,
  bindPreviewActions,
  refreshPageInfo,
  renderPageInfo,
  schedulePageInfo,
} from "./components/preview.js";
import { bindPaginationControls, exitPaginationMode } from "./components/pagination.js";
import { openJsonEditor, closeJsonEditor, applyJson, bindImportDialog, renderAll } from "./components/jsonEditor.js";

/* ================= 启动 ================= */

async function boot() {
  bindConfirmDialog();
  bindImportDialog();
  bindPaginationControls();
  bindPreviewFrame();
  bindZoomButtons();
  bindPreviewActions();
  bindTopbar();
  bindTabs();
  bindDialogs();
  bindShortcuts();
  bindStoreEvents();

  try {
    const [schema, templates, docsData] = await Promise.all([
      api.schema(),
      api.templates(),
      api.documents(),
    ]);
    let doc = null;
    const docs = docsData.documents || [];
    if (docs.length) {
      // 打开最近更新的文档；若本地有更新未同步内容则询问
      const sorted = [...docs].sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
      const { document: serverDoc } = await api.getDocument(sorted[0].id);
      const local = store.readLocal(sorted[0].id);
      if (local && (local.updatedAt || 0) > (serverDoc.updatedAt || 0)) {
        const useLocal = await confirmDialog(
          "检测到本地有未同步的修改（上次异常退出？），是否恢复本地版本？",
          "恢复本地",
          "用服务器版本",
        );
        doc = useLocal ? local : serverDoc;
      } else {
        doc = serverDoc;
      }
    } else {
      const { document: fresh } = await api.createFromSample("general");
      doc = fresh;
      toastSuccess("已为你创建示例简历，可直接修改");
    }
    store.init({ doc, templates, schema, documents: docs });
    renderAll();
    renderDocList(document.getElementById("docList"));
    renderTemplatePicker();
  } catch (e) {
    document.getElementById("formArea").textContent = "";
    const div = document.createElement("div");
    div.className = "editor-loading";
    div.textContent = "初始化失败：" + e.message + "（请确认 python app.py 正在运行）";
    document.getElementById("formArea").appendChild(div);
    toastError("初始化失败：" + e.message);
  }
}

/* ================= store 事件 ================= */

function bindStoreEvents() {
  store.on("doc", () => {
    const t = document.getElementById("docTitle");
    if (document.activeElement !== t) t.value = store.doc?.title || "";
    renderTemplateName();
  });

  store.on("preview", () => doRenderPreview());

  store.on("pageinfo", () => refreshPageInfo());

  store.on("pageinfo-result", () => renderPageInfo());

  store.on("save-state", (state, msg) => {
    const el = document.getElementById("saveStatus");
    el.className = "save-status " + state;
    if (state === "saving") el.textContent = "保存中…";
    else if (state === "saved") el.textContent = `已保存 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`;
    else if (state === "error") el.textContent = "保存失败：" + (msg || "未知错误");
    else el.textContent = "";
  });

  store.on("zoom", () => {
    // applyZoom 在 preview.js 内通过 load 事件联动；这里直接派发一次
    document.getElementById("previewFrame").dispatchEvent(new Event("load"));
  });
}

/* ================= 顶栏 ================= */

function bindTopbar() {
  const title = document.getElementById("docTitle");
  title.addEventListener("input", () => {
    if (!store.doc) return;
    store.doc.title = title.value;
    store.touch();
  });
  title.addEventListener("change", () => store.saveNow());

  document.getElementById("btnExportPdf").addEventListener("click", () => exportResume("pdf"));
  document.getElementById("btnExportDocx").addEventListener("click", () => exportResume("docx"));
  document.getElementById("btnExportJson").addEventListener("click", () => exportResume("json"));

  document.getElementById("btnJson").addEventListener("click", openJsonEditor);
  document.getElementById("btnApplyJson").addEventListener("click", applyJson);
  document.getElementById("btnCloseJson").addEventListener("click", closeJsonEditor);

  document.getElementById("btnAddSection").addEventListener("click", openSectionDialog);
  document.getElementById("btnSaveSection").addEventListener("click", saveSectionFromDialog);
  document.getElementById("btnCancelSection").addEventListener("click", closeSectionDialog);
  document.getElementById("btnCloseSection").addEventListener("click", closeSectionDialog);

  document.getElementById("btnNewFromSample").addEventListener("click", async () => {
    const ok = await confirmDialog("从示例数据新建一份简历？当前未保存修改会先保存。", "新建", "取消");
    if (!ok) return;
    if (store.dirty) await store.saveNow();
    try {
      const { document: doc } = await api.createFromSample("general");
      store.setDocument(doc);
      renderAll();
      renderDocList(document.getElementById("docList"));
      toastSuccess("已新建示例简历");
    } catch (e) {
      toastError(e.message);
    }
  });

  document.getElementById("btnNewBlank").addEventListener("click", async () => {
    if (store.dirty) await store.saveNow();
    try {
      const { document: doc } = await api.createDocument("classic", "未命名简历");
      store.setDocument(doc);
      renderAll();
      renderDocList(document.getElementById("docList"));
      toastSuccess("已新建空白简历");
    } catch (e) {
      toastError(e.message);
    }
  });
}

async function exportResume(fmt) {
  const doc = store.doc;
  if (!doc) return;
  if (store.dirty) await store.saveNow();
  const info = store.state.pageInfo;
  const name = (doc.title || "resume").replace(/[\\/:*?"<>|]/g, "_");
  try {
    if (fmt === "pdf") {
      if (info && info.pageCount > 1) {
        toast(`当前简历共 ${info.pageCount} 页，正在导出…`);
      }
      await postDownloadName("/api/v1/export/pdf", { id: doc.id }, `${name}.pdf`);
      toastSuccess("PDF 导出成功");
    } else if (fmt === "docx") {
      await postDownloadName("/api/v1/export/docx", { id: doc.id }, `${name}.docx`);
      toastSuccess("Word 导出成功");
    } else {
      await postDownloadName("/api/v1/export/json", { id: doc.id }, `${name}.json`);
      toastSuccess("JSON 导出成功");
    }
  } catch (e) {
    toastError(e.message);
  }
}

async function postDownloadName(url, body, filename) {
  const { postDownload } = await import("./api.js");
  return postDownload(url, body, filename);
}

/* ================= 模板选择 ================= */

function renderTemplatePicker() {
  const menu = document.getElementById("templateMenu");
  menu.textContent = "";
  for (const t of store.templates) {
    const opt = document.createElement("button");
    opt.type = "button";
    opt.className = "tpl-option" + (store.doc?.templateId === t.id ? " active" : "");
    opt.setAttribute("role", "option");
    opt.dataset.id = t.id;

    const sw = document.createElement("span");
    sw.className = "tpl-swatch";
    sw.style.background = t.defaultDesign?.accent || "#0f766e";
    sw.textContent = (t.name || "?").slice(0, 1);
    opt.appendChild(sw);

    const meta = document.createElement("span");
    meta.className = "tpl-meta";
    const nameRow = document.createElement("div");
    nameRow.className = "tpl-opt-name";
    nameRow.textContent = t.name || t.id;
    if (t.atsSafe) {
      const badge = document.createElement("span");
      badge.className = "badge badge-ats";
      badge.textContent = "ATS";
      nameRow.appendChild(badge);
    }
    if (store.doc?.templateId === t.id) {
      const check = document.createElement("span");
      check.className = "badge-check";
      check.textContent = "✓";
      nameRow.appendChild(check);
    }
    meta.appendChild(nameRow);
    const desc = document.createElement("div");
    desc.className = "tpl-opt-desc";
    desc.textContent = t.description || "";
    meta.appendChild(desc);
    opt.appendChild(meta);

    opt.addEventListener("click", () => selectTemplate(t.id));
    menu.appendChild(opt);
  }
  renderTemplateName();
}

function renderTemplateName() {
  const t = store.templates.find((x) => x.id === store.doc?.templateId);
  document.getElementById("tplName").textContent = t ? t.name : "选择模板";
  const dot = document.getElementById("tplDot");
  if (dot) dot.style.background = t?.defaultDesign?.accent || "#0f766e";
}

async function selectTemplate(id) {
  const doc = store.doc;
  if (!doc || doc.templateId === id) {
    document.getElementById("templateMenu").hidden = true;
    return;
  }
  doc.templateId = id;
  // 套用模板默认设计（主题色 / 字体），保留用户其他参数
  const tpl = store.templates.find((t) => t.id === id);
  if (tpl?.defaultDesign) {
    for (const [k, v] of Object.entries(tpl.defaultDesign)) {
      if (k in doc.design) doc.design[k] = v;
    }
  }
  store.touch({ pageInfo: true });
  document.getElementById("templateMenu").hidden = true;
  document.getElementById("templatePickerBtn").setAttribute("aria-expanded", "false");
  renderTemplatePicker();
  toastSuccess(`已切换模板「${tpl?.name || id}」`);
}

function bindTemplateMenuToggle() {
  const btn = document.getElementById("templatePickerBtn");
  const menu = document.getElementById("templateMenu");
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const willOpen = menu.hidden;
    menu.hidden = !willOpen;
    btn.setAttribute("aria-expanded", String(willOpen));
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".template-picker")) {
      menu.hidden = true;
      btn.setAttribute("aria-expanded", "false");
    }
  });
}

/* ================= 左栏页签 ================= */

function bindTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => {
        const active = t === tab;
        t.classList.toggle("active", active);
        t.setAttribute("aria-selected", String(active));
      });
      document.querySelectorAll(".tab-pane").forEach((p) => {
        p.classList.toggle("active", p.id === `pane-${tab.dataset.tab}`);
        p.hidden = p.id !== `pane-${tab.dataset.tab}`;
      });
      if (tab.dataset.tab === "docs") renderDocList(document.getElementById("docList"));
      if (tab.dataset.tab === "design") renderDesignPanel(document.getElementById("pane-design"));
    });
  });
}

/* ================= 弹窗 / 快捷键 ================= */

function bindDialogs() {
  bindTemplateMenuToggle();

  const sectionOverlay = document.getElementById("sectionOverlay");
  sectionOverlay.addEventListener("click", (e) => {
    if (e.target === sectionOverlay) closeSectionDialog();
  });

  const jsonOverlay = document.getElementById("jsonOverlay");
  jsonOverlay.addEventListener("click", (e) => {
    if (e.target === jsonOverlay) closeJsonEditor();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (!jsonOverlay.hidden) closeJsonEditor();
      else if (!sectionOverlay.hidden) closeSectionDialog();
      else if (store.state.paginationMode) exitPaginationMode();
    }
  });
}

function bindShortcuts() {
  document.addEventListener("keydown", async (e) => {
    const mod = e.ctrlKey || e.metaKey;
    if (!mod) return;
    if (e.key.toLowerCase() === "s") {
      e.preventDefault();
      await store.saveNow();
      toastSuccess("已保存");
    } else if (e.key.toLowerCase() === "e") {
      e.preventDefault();
      exportResume("pdf");
    }
  });
}

/* ================= 删除当前文档后 ================= */

export const app = {
  async reloadAfterDelete() {
    try {
      const { documents } = await api.documents();
      store.setDocuments(documents);
      if (documents.length) {
        const sorted = [...documents].sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
        const { document: doc } = await api.getDocument(sorted[0].id);
        store.setDocument(doc);
      } else {
        const { document: doc } = await api.createFromSample("general");
        store.setDocument(doc);
      }
      renderAll();
      renderDocList(document.getElementById("docList"));
    } catch (e) {
      toastError(e.message);
    }
  },
};

/* ================= GO ================= */
boot();
