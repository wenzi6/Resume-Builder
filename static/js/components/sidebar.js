// @ts-check
/**
 * 左栏：区块管理（排序 / 显隐 / 重命名 / 新增 / 删除）+ 文档列表。
 */

import { store } from "../store.js";
import { api } from "../api.js";
import { toast, toastSuccess, toastError } from "./toast.js";
import { renderForm, rerenderSectionForm, scrollToSection } from "./form.js";

/* ---------------- 区块树 ---------------- */

const TYPE_LABEL = { object: "单组", array: "列表", skills: "技能", simple: "文本" };

function el(tag, className, text) {
  const e = document.createElement(tag);
  if (className) e.className = className;
  if (text != null) e.textContent = text;
  return e;
}

export function renderSectionTree(container) {
  const doc = store.doc;
  container.textContent = "";
  if (!doc) return;

  const sections = doc.sections || [];
  sections.forEach((section, idx) => {
    container.appendChild(sectionRow(section, idx, sections.length));
  });
}

function sectionRow(section, idx, total) {
  const row = el("li", "section-row");
  row.draggable = true;
  row.dataset.key = section.key;
  if (section.visible === false) row.classList.add("hidden-sec");

  const grip = el("span", "sec-grip", "⋮⋮");
  grip.title = "拖动排序";
  row.appendChild(grip);

  const name = el("span", "sec-name", section.title || section.key);
  row.appendChild(name);

  const badge = el("span", "sec-type", TYPE_LABEL[section.type] || section.type);
  row.appendChild(badge);

  const acts = el("span", "sec-actions");

  // 上移 / 下移
  const up = el("button", "sec-act", "↑");
  up.type = "button";
  up.title = "上移";
  up.style.opacity = idx === 0 ? "0.3" : "";
  up.addEventListener("click", () => moveSection(idx, -1));
  acts.appendChild(up);

  const down = el("button", "sec-act", "↓");
  down.type = "button";
  down.title = "下移";
  down.style.opacity = idx === total - 1 ? "0.3" : "";
  down.addEventListener("click", () => moveSection(idx, 1));
  acts.appendChild(down);

  // 显隐
  const vis = el("button", "sec-act" + (section.visible === false ? " off" : ""), section.visible === false ? "🚫" : "👁");
  vis.type = "button";
  vis.title = section.visible === false ? "显示" : "隐藏";
  vis.addEventListener("click", () => {
    section.visible = section.visible === false;
    store.touch();
    renderSectionTree(document.getElementById("sectionTree"));
    rerenderSectionForm(section.key);
  });
  acts.appendChild(vis);

  // 重命名
  const rename = el("button", "sec-act", "✎");
  rename.type = "button";
  rename.title = "重命名";
  rename.addEventListener("click", () => startRename(row, name, section));
  acts.appendChild(rename);

  // 删除
  const del = el("button", "sec-act danger", "✕");
  del.type = "button";
  del.title = "删除区块";
  del.addEventListener("click", () => deleteSection(section));
  acts.appendChild(del);

  row.appendChild(acts);

  // 点击行 -> 滚动到对应表单
  row.addEventListener("click", (e) => {
    if (e.target.closest("button")) return;
    scrollToSection(section.key);
  });

  /* 拖拽排序 */
  row.addEventListener("dragstart", (e) => {
    e.dataTransfer.setData("text/plain", section.key);
    e.dataTransfer.effectAllowed = "move";
    row.classList.add("dragging");
  });
  row.addEventListener("dragend", () => {
    row.classList.remove("dragging");
    container.querySelectorAll(".drop-target").forEach((n) => n.classList.remove("drop-target"));
  });
  row.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    row.classList.add("drop-target");
  });
  row.addEventListener("dragleave", () => row.classList.remove("drop-target"));
  row.addEventListener("drop", (e) => {
    e.preventDefault();
    row.classList.remove("drop-target");
    const fromKey = e.dataTransfer.getData("text/plain");
    if (!fromKey || fromKey === section.key) return;
    const sections = store.doc.sections;
    const from = sections.findIndex((s) => s.key === fromKey);
    const to = sections.findIndex((s) => s.key === section.key);
    if (from < 0 || to < 0) return;
    const [moved] = sections.splice(from, 1);
    sections.splice(to, 0, moved);
    store.touch();
    renderSectionTree(container);
    renderForm(document.getElementById("formArea"));
  });

  return row;
}

function startRename(row, nameEl, section) {
  const input = el("input", "sec-name-input");
  input.type = "text";
  input.value = section.title || section.key;
  nameEl.replaceWith(input);
  input.focus();
  input.select();
  const commit = () => {
    const v = input.value.trim();
    if (v) {
      section.title = v;
      store.touch();
    }
    renderSectionTree(document.getElementById("sectionTree"));
    rerenderSectionForm(section.key);
  };
  input.addEventListener("blur", commit);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") commit();
    if (e.key === "Escape") {
      input.removeEventListener("blur", commit);
      renderSectionTree(document.getElementById("sectionTree"));
    }
    e.stopPropagation();
  });
}

function moveSection(idx, dir) {
  const sections = store.doc.sections;
  const target = idx + dir;
  if (target < 0 || target >= sections.length) return;
  [sections[idx], sections[target]] = [sections[target], sections[idx]];
  store.touch();
  renderSectionTree(document.getElementById("sectionTree"));
  renderForm(document.getElementById("formArea"));
}

async function deleteSection(section) {
  const ok = await confirmDialog(`确定删除区块「${section.title || section.key}」？内容将一并移除。`);
  if (!ok) return;
  const doc = store.doc;
  doc.sections = doc.sections.filter((s) => s.key !== section.key);
  if (doc.content && section.key in doc.content) delete doc.content[section.key];
  if (Array.isArray(doc.pageBreaks)) {
    doc.pageBreaks = doc.pageBreaks.filter((k) => k !== section.key);
  }
  store.touch();
  renderSectionTree(document.getElementById("sectionTree"));
  renderForm(document.getElementById("formArea"));
  toastSuccess(`已删除区块「${section.title || section.key}」`);
}

/* ---------------- 添加区块弹窗 ---------------- */

let sectionDialogMode = "add"; // add | edit

export function openSectionDialog() {
  sectionDialogMode = "add";
  const overlay = document.getElementById("sectionOverlay");
  overlay.hidden = false;
  renderBuiltinChips();
  document.getElementById("sectionTitleInput").value = "";
  document.getElementById("sectionTypeSelect").value = "array";
  document.getElementById("sectionFieldsText").value = "";
  document.getElementById("sectionTitleInput").focus();
}

export function closeSectionDialog() {
  document.getElementById("sectionOverlay").hidden = true;
}

function renderBuiltinChips() {
  const chips = document.getElementById("builtinChips");
  chips.textContent = "";
  const doc = store.doc;
  const existing = new Set((doc?.sections || []).map((s) => s.key));
  const builtin = store.schema?.builtin || [];
  const missing = builtin.filter((s) => !existing.has(s.key));
  if (!missing.length) {
    chips.appendChild(el("span", "field-hint", "所有内置区块都已在简历中。"));
    return;
  }
  for (const s of missing) {
    const chip = el("button", "chip", `+ ${s.title}`);
    chip.type = "button";
    chip.addEventListener("click", () => {
      addSection({ ...structuredClone(s), visible: true });
      closeSectionDialog();
    });
    chips.appendChild(chip);
  }
}

/** 保存按钮：新建自定义区块。 */
export function saveSectionFromDialog() {
  const title = document.getElementById("sectionTitleInput").value.trim();
  if (!title) {
    toastError("请填写区块标题");
    return;
  }
  const type = document.getElementById("sectionTypeSelect").value;
  const fieldsText = document.getElementById("sectionFieldsText").value;

  const fields = [];
  for (const line of fieldsText.split("\n")) {
    const t = line.trim();
    if (!t) continue;
    const [key, label, ftype] = t.split("|").map((x) => (x || "").trim());
    if (!key) continue;
    fields.push({ key, label: label || key, type: ["text", "date", "textarea", "list"].includes(ftype) ? ftype : "text" });
  }
  if (!fields.length) {
    const defaults = type === "array" ? store.schema?.customArrayFields : store.schema?.customSimpleFields;
    fields.push(...structuredClone(defaults || [{ key: "descriptions", label: "内容", type: "list" }]));
  }

  // key：中文标题 -> 安全 key
  let key = "custom_" + title.replace(/[^a-zA-Z0-9]/g, "").slice(0, 12);
  if (!key.replace("custom_", "")) key = "custom_" + Math.random().toString(36).slice(2, 8);
  const existing = new Set((store.doc.sections || []).map((s) => s.key));
  let finalKey = key;
  let n = 1;
  while (existing.has(finalKey)) finalKey = `${key}_${n++}`;

  addSection({ key: finalKey, title, type, fields, visible: true });
  closeSectionDialog();
}

function addSection(sectionDef) {
  const doc = store.doc;
  doc.sections = doc.sections || [];
  doc.sections.push(sectionDef);
  // 初始化内容
  doc.content = doc.content || {};
  if (!(sectionDef.key in doc.content)) {
    if (sectionDef.type === "array") doc.content[sectionDef.key] = [];
    else if (sectionDef.type === "skills") doc.content[sectionDef.key] = { featuredSkills: [], descriptions: [] };
    else doc.content[sectionDef.key] = { descriptions: [] };
  }
  store.touch();
  renderSectionTree(document.getElementById("sectionTree"));
  renderForm(document.getElementById("formArea"));
  scrollToSection(sectionDef.key);
  toastSuccess(`已添加区块「${sectionDef.title}」`);
}

/* ---------------- 文档列表 ---------------- */

function timeAgo(ts) {
  if (!ts) return "";
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return "刚刚";
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  const d = new Date(ts * 1000);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

export async function renderDocList(container) {
  container.textContent = "";
  let docs = [];
  try {
    const data = await api.documents();
    docs = data.documents || [];
    store.setDocuments(docs);
  } catch (e) {
    container.appendChild(el("li", "field-hint", "加载失败：" + e.message));
    return;
  }
  if (!docs.length) {
    container.appendChild(el("li", "field-hint", "还没有简历，点击上方按钮新建。"));
    return;
  }
  // 搜索过滤（按标题）+ 按更新时间排序
  const q = (document.getElementById("docSearch")?.value || "").trim().toLowerCase();
  const sorted = docs
    .filter((d) => !q || (d.title || "").toLowerCase().includes(q))
    .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
  if (!sorted.length) {
    container.appendChild(el("li", "field-hint", "没有匹配的简历"));
    return;
  }
  for (const d of sorted) {
    container.appendChild(docItem(d));
  }
}

function docItem(d) {
  const li = el("li", "doc-item" + (store.doc?.id === d.id ? " active" : ""));
  li.dataset.id = d.id;

  const head = el("div", "doc-item-head");
  head.appendChild(el("span", "doc-item-title", d.title || "未命名简历"));
  if (d.hasSourcePdf) {
    const pdf = el("span", "badge badge-pdf", "原PDF");
    pdf.title = "对照导入：保留原始 PDF 格式";
    head.appendChild(pdf);
  }
  const acts = el("span", "doc-item-acts");

  const hist = el("button", "sec-act", "⏱");
  hist.type = "button";
  hist.title = "历史版本";
  hist.addEventListener("click", (e) => {
    e.stopPropagation();
    openVersionsDialog(d.id);
  });
  acts.appendChild(hist);

  const dup = el("button", "sec-act", "⧉");
  dup.type = "button";
  dup.title = "复制";
  dup.addEventListener("click", async (e) => {
    e.stopPropagation();
    try {
      const { document: copy } = await api.duplicateDocument(d.id);
      store.setDocument(copy);
      renderDocList(document.getElementById("docList"));
      toastSuccess("已复制");
    } catch (err) {
      toastError(err.message);
    }
  });
  acts.appendChild(dup);

  const del = el("button", "sec-act danger", "✕");
  del.type = "button";
  del.title = "删除";
  del.addEventListener("click", async (e) => {
    e.stopPropagation();
    const ok = await confirmDialog(`确定删除「${d.title || "未命名简历"}」？此操作不可恢复。`);
    if (!ok) return;
    try {
      await api.deleteDocument(d.id);
      store.clearLocal(d.id);
      if (store.doc?.id === d.id) {
        // 删除的是当前文档：重新加载列表并打开最近的一个（或新建示例）
        const { app } = await import("../app.js");
        await app.reloadAfterDelete();
      } else {
        renderDocList(document.getElementById("docList"));
      }
      toastSuccess("已删除");
    } catch (err) {
      toastError(err.message);
    }
  });
  acts.appendChild(del);
  head.appendChild(acts);
  li.appendChild(head);

  const meta = el("div", "doc-item-meta");
  meta.appendChild(el("span", null, d.templateId || "classic"));
  meta.appendChild(el("span", null, timeAgo(d.updatedAt)));
  li.appendChild(meta);

  li.addEventListener("click", async () => {
    if (store.doc?.id === d.id) return;
    if (store.dirty) await store.saveNow();
    try {
      const { document: doc } = await api.getDocument(d.id);
      // localStorage 有更新的未保存内容时优先用本地（刷新恢复场景）
      const local = store.readLocal(d.id);
      if (local && (local.updatedAt || 0) > (doc.updatedAt || 0)) {
        const useLocal = await confirmDialog("检测到本地有未同步的修改，是否恢复本地版本？", "恢复本地", "用服务器版本");
        store.setDocument(useLocal ? local : doc);
      } else {
        store.setDocument(doc);
      }
      renderDocList(document.getElementById("docList"));
      renderForm(document.getElementById("formArea"));
    } catch (err) {
      toastError(err.message);
    }
  });

  return li;
}

/* ---------------- 历史版本 ---------------- */

let versionsDocId = null;

export async function openVersionsDialog(docId) {
  versionsDocId = docId;
  const overlay = document.getElementById("versionsOverlay");
  overlay.hidden = false;
  const list = document.getElementById("versionList");
  list.textContent = "";
  list.appendChild(el("li", "field-hint", "加载中…"));
  try {
    const data = await api.getJson(`/api/v1/documents/${docId}/versions`);
    list.textContent = "";
    if (!data.versions?.length) {
      list.appendChild(el("li", "field-hint", "还没有历史版本"));
      return;
    }
    for (const v of data.versions) {
      const li = el("li", "doc-item");
      const head = el("div", "doc-item-head");
      head.appendChild(el("span", "doc-item-title", v.title || "未命名"));
      const btn = el("button", "btn btn-sm", "恢复");
      btn.type = "button";
      btn.addEventListener("click", async () => {
        const ok = await confirmDialog(
          `确定恢复到 ${new Date(v.savedAt * 1000).toLocaleString("zh-CN")} 的版本？当前内容会被替换。`);
        if (!ok) return;
        try {
          const { document: doc } = await api.postJson(
            `/api/v1/documents/${docId}/versions/${v.id}/restore`, {});
          store.setDocument(doc);
          const { renderAll } = await import("./jsonEditor.js");
          renderAll();
          overlay.hidden = true;
          toastSuccess("已恢复历史版本");
        } catch (e) {
          toastError("恢复失败：" + e.message);
        }
      });
      head.appendChild(btn);
      li.appendChild(head);
      const meta = el("div", "doc-item-meta");
      meta.appendChild(el("span", null, new Date(v.savedAt * 1000).toLocaleString("zh-CN")));
      li.appendChild(meta);
      list.appendChild(li);
    }
  } catch (e) {
    list.textContent = "";
    list.appendChild(el("li", "field-hint", "加载失败：" + e.message));
  }
}

export function bindVersionsDialog() {
  const overlay = document.getElementById("versionsOverlay");
  document.getElementById("btnCloseVersions").addEventListener("click", () => (overlay.hidden = true));
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) overlay.hidden = true;
  });
}

/* ---------------- 数据安全：导出全部 / 导入全部 / 备份 ---------------- */

async function exportAllDocs() {
  try {
    const resp = await fetch("/api/v1/documents/export-all");
    if (!resp.ok) throw new Error((await resp.json()).error || `HTTP ${resp.status}`);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `resume-studio-${new Date().toISOString().slice(0, 10)}.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    toastSuccess("已导出全部简历（ZIP）");
  } catch (e) {
    toastError("导出失败：" + e.message);
  }
}

async function importAllDocs(file) {
  try {
    const fd = new FormData();
    fd.append("file", file);
    const resp = await fetch("/api/v1/documents/import-all", { method: "POST", body: fd });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
    renderDocList(document.getElementById("docList"));
    const skipped = data.skipped?.length ? `，跳过 ${data.skipped.length} 个` : "";
    toastSuccess(`已导入 ${data.count} 份简历${skipped}`);
  } catch (e) {
    toastError("导入失败：" + e.message);
  }
}

export async function renderBackupList() {
  const list = document.getElementById("backupList");
  list.textContent = "";
  try {
    const data = await api.getJson("/api/v1/backups");
    if (!data.backups?.length) {
      list.appendChild(el("li", "field-hint", "还没有备份"));
      return;
    }
    for (const b of data.backups) {
      const li = el("li", "doc-item");
      const head = el("div", "doc-item-head");
      head.appendChild(el("span", "doc-item-title", b.createdText));
      const size = el("span", "field-hint", `${(b.size / 1024).toFixed(0)} KB`);
      head.appendChild(size);
      const btn = el("button", "btn btn-sm", "恢复");
      btn.type = "button";
      btn.addEventListener("click", async () => {
        const ok = await confirmDialog(`确定恢复到 ${b.createdText} 的备份？当前数据将被覆盖（恢复前会再自动备份一次）。`);
        if (!ok) return;
        try {
          await api.postJson("/api/v1/backups/now", {});  // 恢复前先保一份
          await api.postJson("/api/v1/backups/restore", { name: b.name });
          toastSuccess("已恢复，正在重载…");
          setTimeout(() => location.reload(), 800);
        } catch (e) {
          toastError("恢复失败：" + e.message);
        }
      });
      head.appendChild(btn);
      li.appendChild(head);
      list.appendChild(li);
    }
  } catch (e) {
    list.appendChild(el("li", "field-hint", "加载失败：" + e.message));
  }
}

export function bindDataSafety() {
  document.getElementById("btnExportAll").addEventListener("click", exportAllDocs);
  document.getElementById("btnImportAll").addEventListener("click", () =>
    document.getElementById("importAllInput").click());
  document.getElementById("importAllInput").addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (file) importAllDocs(file);
    e.target.value = "";
  });
  document.getElementById("btnBackupNow").addEventListener("click", async () => {
    try {
      const r = await api.postJson("/api/v1/backups/now", {});
      renderBackupList();
      toastSuccess(r.backup ? "备份完成" : "内容无变化，未生成新备份");
    } catch (e) {
      toastError("备份失败：" + e.message);
    }
  });
  // 文档搜索（输入即过滤）
  const search = document.getElementById("docSearch");
  if (search && !search.dataset.bound) {
    search.dataset.bound = "1";
    search.addEventListener("input", () => renderDocList(document.getElementById("docList")));
  }
}

/* ---------------- 通用确认弹窗 ---------------- */

let confirmResolver = null;

export function confirmDialog(text, okLabel = "确认", cancelLabel = "取消") {
  return new Promise((resolve) => {
    const overlay = document.getElementById("confirmOverlay");
    document.getElementById("confirmText").textContent = text;
    const okBtn = document.getElementById("btnConfirmOk");
    const cancelBtn = document.getElementById("btnConfirmCancel");
    okBtn.textContent = okLabel;
    cancelBtn.textContent = cancelLabel;
    overlay.hidden = false;
    confirmResolver = resolve;
    okBtn.focus();
  });
}

export function bindConfirmDialog() {
  const overlay = document.getElementById("confirmOverlay");
  const done = (val) => {
    overlay.hidden = true;
    if (confirmResolver) confirmResolver(val);
    confirmResolver = null;
  };
  document.getElementById("btnConfirmOk").addEventListener("click", () => done(true));
  document.getElementById("btnConfirmCancel").addEventListener("click", () => done(false));
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) done(false);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !overlay.hidden) done(false);
  });
}
