/**
 * 入口：初始化、顶栏、模板选择、快捷键、全局装配。
 */

import { store } from "./store.js";
import { api } from "./api.js";
import { t, getLang, setLang, applyI18n } from "./i18n.js";
import { toast, toastSuccess, toastError } from "./components/toast.js";
import { renderForm, scrollToSection } from "./components/form.js";
import {
  renderSectionTree,
  renderDocList,
  openSectionDialog,
  closeSectionDialog,
  saveSectionFromDialog,
  bindConfirmDialog,
  bindVersionsDialog,
  confirmDialog,
} from "./components/sidebar.js";
import { renderDesignPanel, syncDesignValues } from "./components/designPanel.js";
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
import { bindAiPanel } from "./components/aiPanel.js";

/* ================= 启动 ================= */

// 对照导入文档：主导出按钮切到原格式，显示「模板排版」次要按钮
function syncExportButtons() {
  const hasSource = !!store.doc?.sourcePdf;
  document.getElementById("btnExportPdfTpl").hidden = !hasSource;
  document.getElementById("btnExportPdf").title =
    hasSource ? "按原始格式导出（修改应用进原 PDF）" : "";
}

async function boot() {
  applyI18n();
  bindConfirmDialog();
  bindVersionsDialog();
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
  bindViewToggle();
  bindAiPanel();
  bindLangToggle();

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
    syncExportButtons();
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

  // 对照导入文档：主导出按钮切到原格式，显示「模板排版」次要按钮
  store.on("doc-swapped", () => {
    renderForm(document.getElementById("formArea"));
    renderSectionTree(document.getElementById("sectionTree"));
    if (!document.getElementById("pane-design").hidden) {
      renderDesignPanel(document.getElementById("pane-design"));
    } else {
      syncDesignValues();
    }
    syncExportButtons();
  });

  store.on("preview", () => doRenderPreview());

  store.on("pageinfo", () => refreshPageInfo());

  store.on("pageinfo-result", () => {
    renderPageInfo();
    // 分页模式下测量结果更新（如内容变化后）→ 重画分页线
    if (store.state.paginationMode) {
      import("./components/pagination.js").then((m) =>
        m.injectPaginationOverlay(document.getElementById("previewFrame")));
    }
  });

  store.on("save-state", (state, msg) => {
    const el = document.getElementById("saveStatus");
    el.className = "save-status " + state;
    if (state === "saving") el.textContent = t("toast.saving");
    else if (state === "saved") {
      el.textContent = t("toast.savedAt", { time: new Date().toLocaleTimeString(getLang() === "zh-CN" ? "zh-CN" : "en-US", { hour12: false }) });
    } else if (state === "error") el.textContent = t("toast.saveFailed", { msg: msg || "?" });
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

  document.getElementById("btnExportPdf").addEventListener("click", () => exportResume("pdf", "original"));
  document.getElementById("btnExportDocx").addEventListener("click", () => exportResume("docx"));
  document.getElementById("btnExportJson").addEventListener("click", () => exportResume("json"));
  document.getElementById("btnExportHtml").addEventListener("click", () => exportResume("html"));
  document.getElementById("btnExportPdfTpl").addEventListener("click", () => exportResume("pdf", "template"));

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

async function exportResume(fmt, mode = "template") {
  const doc = store.doc;
  if (!doc) return;
  if (store.dirty) await store.saveNow();
  const info = store.state.pageInfo;
  const name = (doc.title || "resume").replace(/[\\/:*?"<>|]/g, "_");
  try {
    let warnings = [];
    if (fmt === "pdf") {
      // 对照导入的文档：默认按原格式导出（修改打进原始 PDF），模板导出为次要选项
      const useOriginal = mode === "original" && !!doc.sourcePdf;
      if (!useOriginal && info && info.pageCount > 1) {
        toast(t("toast.exporting", { n: info.pageCount }));
      }
      warnings = await postDownloadName(
        "/api/v1/export/pdf",
        useOriginal ? { id: doc.id, mode: "original" } : { id: doc.id },
        `${name}.pdf`);
      toastSuccess(useOriginal ? "已按原格式导出 PDF" : t("toast.pdfOk"));
    } else if (fmt === "docx") {
      warnings = await postDownloadName("/api/v1/export/docx", { id: doc.id }, `${name}.docx`);
      toastSuccess(t("toast.docxOk"));
    } else if (fmt === "json") {
      warnings = await postDownloadName("/api/v1/export/json", { id: doc.id }, `${name}.json`);
      toastSuccess(t("toast.jsonOk"));
    } else if (fmt === "html") {
      warnings = await postDownloadName("/api/v1/export/html", { id: doc.id }, `${name}.html`);
      toastSuccess(t("toast.htmlOk"));
    }
    for (const w of warnings) {
      toast("⚠️ " + w, "error", 8000);
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
    // 输入框内保留原生文本撤销
    const inField = ["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName);
    if (!inField && e.key.toLowerCase() === "z") {
      e.preventDefault();
      if (store.undo()) toast(t("toast.undo"));
      return;
    }
    if (!inField && (e.key.toLowerCase() === "y" || (e.shiftKey && e.key.toLowerCase() === "z"))) {
      e.preventDefault();
      if (store.redo()) toast(t("toast.redo"));
      return;
    }
    if (e.key.toLowerCase() === "s") {
      e.preventDefault();
      await store.saveNow();
      toastSuccess(t("toast.saved"));
    } else if (e.key.toLowerCase() === "e") {
      e.preventDefault();
      exportResume("pdf");
    }
  });
}

/* ================= 语言切换 ================= */

function bindLangToggle() {
  const btn = document.getElementById("btnLang");
  if (!btn) return;
  btn.addEventListener("click", () => {
    setLang(getLang() === "zh-CN" ? "en" : "zh-CN");
    applyI18n();
    // 动态渲染的面板用当前语言重画
    renderDesignPanel(document.getElementById("pane-design"));
    renderDocList(document.getElementById("docList"));
    renderPageInfo();
  });
}

/* ================= 视图切换（模板预览 / 原始格式） ================= */

function bindViewToggle() {
  document.getElementById("viewToggle").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-view]");
    if (!btn) return;
    store.setViewMode(btn.dataset.view);
  });
  store.on("view-mode", applyViewMode);
  store.on("doc-swapped", applyViewMode);
}

function applyViewMode() {
  const doc = store.doc;
  const hasSource = !!doc?.sourcePdf;
  document.getElementById("viewToggle").hidden = !hasSource;
  const mode = store.state.viewMode;
  document.querySelectorAll("#viewToggle button").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === mode));

  const sourcePane = document.getElementById("sourcePane");
  const previewScroll = document.getElementById("previewScroll");
  const zoomGroup = document.querySelector(".zoom-group");
  if (mode === "source" && hasSource) {
    sourcePane.hidden = false;
    previewScroll.hidden = true;
    document.getElementById("paginationBar").hidden = true; // 分页只属于模板预览
    zoomGroup.style.display = "none";
    loadSourcePdf(doc.sourcePdf);
  } else {
    sourcePane.hidden = true;
    previewScroll.hidden = false;
    zoomGroup.style.display = "";
    if (store.state.paginationMode) document.getElementById("paginationBar").hidden = false;
  }
}

async function loadSourcePdf(rel) {
  const pagesEl = document.getElementById("sourcePages");
  const loading = document.getElementById("sourceLoading");
  const missing = document.getElementById("sourceMissing");
  const openBtn = document.getElementById("sourceOpen");
  const url = "/data/" + rel;
  openBtn.href = url;

  // 已渲染过同一份就不再重复请求
  if (pagesEl.dataset.rel === rel) return;
  pagesEl.dataset.rel = rel;
  pagesEl.textContent = "";
  loading.hidden = false;
  missing.hidden = true;

  try {
    const resp = await fetch(url, { method: "HEAD" });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const data = await api.getJson(`/api/v1/documents/${store.doc.id}/source-pages`);
    loading.hidden = true;
    if (!data.pages?.length) throw new Error("无页面");
    data.pages.forEach((p) => {
      const fig = document.createElement("figure");
      fig.style.margin = "0";
      const img = document.createElement("img");
      img.src = p.url;
      img.alt = `第 ${p.page} 页`;
      img.loading = "lazy";
      fig.appendChild(img);
      const no = document.createElement("figcaption");
      no.className = "source-page-no";
      no.textContent = `第 ${p.page} 页 / 共 ${data.pages.length} 页`;
      fig.appendChild(no);
      pagesEl.appendChild(fig);
    });
  } catch {
    loading.hidden = true;
    pagesEl.textContent = "";
    missing.hidden = false;
  }
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
