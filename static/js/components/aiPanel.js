// @ts-check
/**
 * AI 助手：生成简历 / 修改建议 / JD 定制 / 设置 + 字段级润色对话框。
 *
 * 所有请求走 /api/v1/llm/*；key 只存在本机（GET config 不返回 key）。
 */
import { store } from "../store.js";
import { api } from "../api.js";
import { toast, toastSuccess, toastError } from "./toast.js";
import { confirmDialog } from "./sidebar.js";
import { t } from "../i18n.js";
import { renderForm } from "./form.js";

let aiCfg = null;
let polishTarget = null; // {path, original, context}

/* ---------------- 面板框架 ---------------- */

const AI_SIZE_KEY = "resume-studio:ai-dialog-size";
const AI_DEFAULT_SIZE = { w: 1120, h: 780 };

function applyAiSize(size) {
  const dlg = document.getElementById("aiDialog");
  if (!dlg) return;
  const w = Math.max(520, Math.min(size.w, window.innerWidth * 0.96));
  const h = Math.max(380, Math.min(size.h, window.innerHeight * 0.92));
  dlg.style.width = w + "px";
  dlg.style.height = h + "px";
}

function loadAiSize() {
  try {
    const raw = localStorage.getItem(AI_SIZE_KEY);
    if (raw) {
      const s = JSON.parse(raw);
      if (s && s.w && s.h) return s;
    }
  } catch { /* ignore */ }
  return { ...AI_DEFAULT_SIZE };
}

function saveAiSize(size) {
  try {
    localStorage.setItem(AI_SIZE_KEY, JSON.stringify(size));
  } catch { /* ignore */ }
}

/** 绑定对话框缩放把手（右下角拖动）。 */
function bindAiResize() {
  const handle = document.getElementById("aiResizeHandle");
  const dlg = document.getElementById("aiDialog");
  if (!handle || !dlg) return;
  let start = null;

  handle.addEventListener("mousedown", (e) => {
    e.preventDefault();
    e.stopPropagation();
    const rect = dlg.getBoundingClientRect();
    start = { x: e.clientX, y: e.clientY, w: rect.width, h: rect.height };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  });

  function onMove(e) {
    if (!start) return;
    const w = Math.max(520, Math.min(start.w + (e.clientX - start.x), window.innerWidth * 0.96));
    const h = Math.max(380, Math.min(start.h + (e.clientY - start.y), window.innerHeight * 0.92));
    dlg.style.width = w + "px";
    dlg.style.height = h + "px";
  }

  function onUp() {
    if (!start) return;
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
    const rect = dlg.getBoundingClientRect();
    saveAiSize({ w: Math.round(rect.width), h: Math.round(rect.height) });
    start = null;
  }

  // 重置大小按钮
  document.getElementById("btnAiResetSize")?.addEventListener("click", () => {
    applyAiSize(AI_DEFAULT_SIZE);
    saveAiSize(AI_DEFAULT_SIZE);
  });
}

export function openAiPanel(tab = "generate") {
  document.getElementById("aiOverlay").hidden = false;
  applyAiSize(loadAiSize());
  switchAiTab(tab);
  loadAiConfig().then(() => {
    // 未配置 Key 时直接落到设置页，引导先完成配置
    if (!aiCfg?.configured) {
      switchAiTab("settings");
      setStatus("aiConfigStatus", "首次使用：请填写 Base URL / API Key / 模型，保存后点「测试连接」验证", "error");
    }
  });
}

export function closeAiPanel() {
  document.getElementById("aiOverlay").hidden = true;
}

function switchAiTab(tab) {
  document.querySelectorAll(".ai-tab").forEach((b) => b.classList.toggle("active", b.dataset.aiTab === tab));
  document.querySelectorAll(".ai-pane").forEach((p) => {
    p.classList.toggle("active", p.id === "ai" + cap(tab));
    p.hidden = p.id !== "ai" + cap(tab);
  });
  // 切到对话页签时渲染空态提示
  if (tab === "chat") renderChatLog();
}

function cap(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function el(tag, className, text) {
  const e = document.createElement(tag);
  if (className) e.className = className;
  if (text != null) e.textContent = text;
  return e;
}

function setStatus(elId, msg, kind = "") {
  const el = document.getElementById(elId);
  if (!el) return;
  el.textContent = msg || "";
  el.className = "ai-status" + (kind ? " " + kind : "");
}

function busy(btn, text) {
  btn.disabled = true;
  btn.dataset.origText = btn.dataset.origText || btn.textContent;
  btn.textContent = text;
}

function unbusy(btn) {
  btn.disabled = false;
  if (btn.dataset.origText) btn.textContent = btn.dataset.origText;
}

/* ---------------- 设置 ---------------- */

const FORMAT_HINTS = {
  openai: "",
  azure: "Azure：Base URL 填到资源域名（如 https://xxx.openai.azure.com），「模型名称」填部署名（deployment）",
  anthropic: "Anthropic 原生协议：Base URL 一般填 https://api.anthropic.com",
  gemini: "Gemini 原生协议：Base URL 一般填 https://generativelanguage.googleapis.com",
};

async function loadAiConfig() {
  try {
    aiCfg = await api.getJson("/api/v1/llm/config");
    renderConfigSelect();
  } catch (e) {
    setStatus("aiConfigStatus", "配置加载失败：" + e.message, "error");
    return;
  }

  // 预设下拉（按分组）
  const sel = document.getElementById("aiPreset");
  sel.textContent = "";
  const custom = document.createElement("option");
  custom.value = "";
  custom.textContent = "自定义…";
  sel.appendChild(custom);
  const groups = {};
  for (const p of aiCfg.presets || []) {
    (groups[p.group] = groups[p.group] || []).push(p);
  }
  for (const [g, list] of Object.entries(groups)) {
    const og = document.createElement("optgroup");
    og.label = g;
    for (const p of list) {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = `${p.name}（${p.model}）`;
      opt.dataset.baseUrl = p.base_url || p.baseUrl;
      opt.dataset.model = p.model;
      opt.dataset.format = p.format || "openai";
      og.appendChild(opt);
    }
    sel.appendChild(og);
  }

  // 格式下拉
  const fmtSel = document.getElementById("aiFormat");
  fmtSel.textContent = "";
  for (const f of aiCfg.formats || []) {
    const opt = document.createElement("option");
    opt.value = f.id;
    opt.textContent = f.name;
    fmtSel.appendChild(opt);
  }

  document.getElementById("aiBaseUrl").value = aiCfg.base_url || aiCfg.baseUrl || "";
  document.getElementById("aiModel").value = aiCfg.model || "";
  document.getElementById("aiTimeout").value = aiCfg.timeout || 90;
  document.getElementById("aiFormat").value = aiCfg.format || "openai";
  updateFormatHint();
  const keyInput = document.getElementById("aiApiKey");
  keyInput.value = "";
  keyInput.placeholder = aiCfg.has_key ? "已保存（留空则不修改）" : "sk-…";
  document.getElementById("aiConfigName").value = aiCfg.name || "";
}

/** 渲染配置选择下拉（全部命名配置，当前激活项置顶）。 */
async function renderConfigSelect() {
  const sel = document.getElementById("aiConfigSelect");
  let data;
  try {
    data = await api.getJson("/api/v1/llm/configs");
  } catch {
    return;
  }
  sel.textContent = "";
  for (const c of data.configs || []) {
    const opt = document.createElement("option");
    opt.value = c.id;
    const marks = [];
    if (!c.configured) marks.push("未配置");
    opt.textContent = c.name + (marks.length ? `（${marks.join("·")}）` : "");
    if (c.id === data.active) opt.selected = true;
    sel.appendChild(opt);
  }
}

/** 切换配置。 */
async function switchConfig(id) {
  try {
    await api.postJson(`/api/v1/llm/configs/${id}/activate`, {});
    aiCfg = await api.getJson("/api/v1/llm/config");
    renderConfigSelect();
    fillConfigForm();
    setStatus("aiConfigStatus", `已切换到配置「${aiCfg.name}」`, "ok");
  } catch (e) {
    setStatus("aiConfigStatus", e.message, "error");
  }
}

/** 新建配置（空白，立即激活）。 */
async function createConfig() {
  try {
    await api.postJson("/api/v1/llm/configs", {
      name: "新配置", base_url: "", api_key: "", model: "", format: "openai",
    });
    aiCfg = await api.getJson("/api/v1/llm/config");
    renderConfigSelect();
    fillConfigForm();
    setStatus("aiConfigStatus", "已新建配置，请填写 Base URL / API Key / 模型", "");
    document.getElementById("aiBaseUrl").focus();
  } catch (e) {
    setStatus("aiConfigStatus", e.message, "error");
  }
}

/** 删除当前配置（至少保留一套时）。 */
async function deleteCurrentConfig() {
  const data = await api.getJson("/api/v1/llm/configs");
  if ((data.configs || []).length <= 1) {
    setStatus("aiConfigStatus", "至少保留一套配置，不能全部删除", "error");
    return;
  }
  const ok = await confirmDialog(`确定删除配置「${aiCfg.name}」？删除后不可恢复。`);
  if (!ok) return;
  try {
    await api.del(`/api/v1/llm/configs/${aiCfg.id}`);
    aiCfg = await api.getJson("/api/v1/llm/config");
    renderConfigSelect();
    fillConfigForm();
    setStatus("aiConfigStatus", "配置已删除", "ok");
  } catch (e) {
    setStatus("aiConfigStatus", e.message, "error");
  }
}

/** 用当前激活配置回填表单字段。 */
function fillConfigForm() {
  document.getElementById("aiBaseUrl").value = aiCfg.base_url || "";
  document.getElementById("aiModel").value = aiCfg.model || "";
  document.getElementById("aiFormat").value = aiCfg.format || "openai";
  document.getElementById("aiTimeout").value = aiCfg.timeout || 90;
  document.getElementById("aiConfigName").value = aiCfg.name || "";
  const keyInput = document.getElementById("aiApiKey");
  keyInput.value = "";
  keyInput.placeholder = aiCfg.has_key ? "已保存（留空则不修改）" : "sk-…";
  updateFormatHint();
}

function updateFormatHint() {
  const fmt = document.getElementById("aiFormat").value;
  const hint = document.getElementById("aiFormatHint");
  const text = FORMAT_HINTS[fmt] || "";
  hint.textContent = text;
  hint.hidden = !text;
}

let aiConfigSaveTimer = null;

async function saveAiConfig(opts = {}) {
  const silent = !!opts.silent;
  const baseUrl = document.getElementById("aiBaseUrl").value.trim();
  const model = document.getElementById("aiModel").value.trim();
  const apiKey = document.getElementById("aiApiKey").value.trim();
  const format = document.getElementById("aiFormat").value;
  const timeout = parseInt(document.getElementById("aiTimeout").value, 10) || 90;
  if (!silent) setStatus("aiConfigStatus", "保存中…");
  const name = document.getElementById("aiConfigName").value.trim();
  try {
    aiCfg = await api.putJson("/api/v1/llm/config", { base_url: baseUrl, model, api_key: apiKey, format, timeout, name });
    // 同步下拉中当前配置的显示文本（名称 / 未配置标记）
    const opt = document.getElementById("aiConfigSelect").selectedOptions[0];
    if (opt) {
      const ok = !!(aiCfg.base_url && aiCfg.model && aiCfg.has_key);
      opt.textContent = (aiCfg.name || "未命名配置") + (ok ? "" : "（未配置）");
    }
    if (!silent) {
      document.getElementById("aiApiKey").value = "";
      document.getElementById("aiApiKey").placeholder = "已保存（留空则不修改）";
      const missing = [];
      if (!aiCfg.base_url) missing.push("Base URL");
      if (!aiCfg.model) missing.push("模型名称");
      if (!aiCfg.has_key) missing.push("API Key");
      if (missing.length) {
        setStatus("aiConfigStatus", `已保存，但还缺：${missing.join("、")}`, "error");
      } else {
        setStatus("aiConfigStatus", "✅ 已保存", "ok");
        toastSuccess("AI 配置已保存");
      }
    }
  } catch (e) {
    if (!silent) setStatus("aiConfigStatus", e.message, "error");
  }
}

/** 字段变更 → 防抖 800ms 自动保存（与产品其他部分一致，不再需要手动点保存）。 */
function scheduleAiConfigSave() {
  clearTimeout(aiConfigSaveTimer);
  setStatus("aiConfigStatus", "");
  aiConfigSaveTimer = setTimeout(() => saveAiConfig({ silent: true }), 800);
}

/** 绑定 AI 配置字段的自动保存。 */
function bindAiConfigAutosave() {
  for (const id of ["aiBaseUrl", "aiModel", "aiApiKey", "aiConfigName"]) {
    document.getElementById(id).addEventListener("input", scheduleAiConfigSave);
  }
  for (const id of ["aiFormat", "aiTimeout"]) {
    document.getElementById(id).addEventListener("change", scheduleAiConfigSave);
  }
}

async function testAiConnection() {
  const btn = document.getElementById("btnAiTest");
  busy(btn, "测试中…");
  setStatus("aiConfigStatus", "");
  try {
    // 先保存再测（用户可能改了没保存）
    await saveAiConfig();
    const r = await api.postJson("/api/v1/llm/test", {});
    setStatus("aiConfigStatus", r.message, r.ok ? "ok" : "error");
  } catch (e) {
    setStatus("aiConfigStatus", e.message, "error");
  } finally {
    unbusy(btn);
  }
}

function ensureConfigured() {
  if (aiCfg?.configured) return true;
  switchAiTab("settings");
  const missing = [];
  if (!aiCfg?.base_url) missing.push("Base URL");
  if (!aiCfg?.model) missing.push("模型名称");
  if (!aiCfg?.has_key) missing.push("API Key");
  const msg = missing.length ? `AI 尚未配置完成，还缺：${missing.join("、")}` : "AI 尚未配置";
  setStatus("aiConfigStatus", msg + "（填完自动保存）", "error");
  toast(msg, "error");
  return false;
}

/* ---------------- 流式调用 ---------------- */

/**
 * SSE 流式调用 LLM 能力。
 * @param {string} capability polish | generate
 * @param {Object} params
 * @param {{onChunk?: Function, onDone?: Function, onError?: Function}} handlers
 */
async function streamLlm(capability, params, handlers = {}) {
  let resp;
  try {
    resp = await fetch("/api/v1/llm/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ capability, ...params }),
    });
  } catch (e) {
    handlers.onError?.("网络错误：" + e.message);
    return;
  }
  if (!resp.ok || !resp.body) {
    let msg = `HTTP ${resp.status}`;
    try {
      msg = (await resp.json()).error || msg;
    } catch { /* ignore */ }
    handlers.onError?.(msg);
    return;
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const line = buf.slice(0, idx).trim();
        buf = buf.slice(idx + 2);
        if (!line.startsWith("data:")) continue;
        let msg;
        try {
          msg = JSON.parse(line.slice(5));
        } catch {
          continue;
        }
        if (msg.chunk) handlers.onChunk?.(msg.chunk);
        else if (msg.done) { handlers.onDone?.(msg.result); return; }
        else if (msg.error) { handlers.onError?.(msg.error); return; }
      }
    }
    handlers.onError?.("连接中断");
  } catch (e) {
    handlers.onError?.(e.message);
  }
}

/** 对话专用流式（/llm/chat，messages 直接透传）。 */
async function streamChat(messages, handlers = {}) {
  let resp;
  try {
    resp = await fetch("/api/v1/llm/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages }),
    });
  } catch (e) {
    handlers.onError?.("网络错误：" + e.message);
    return;
  }
  if (!resp.ok || !resp.body) {
    let msg = "HTTP " + resp.status;
    try {
      msg = (await resp.json()).error || msg;
    } catch { /* ignore */ }
    handlers.onError?.(msg);
    return;
  }
  await readSseStream(resp, handlers);
}

/** 通用 SSE 读取：解析 data: 行，分发 chunk / done / error。 */
async function readSseStream(resp, handlers) {
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const line = buf.slice(0, idx).trim();
        buf = buf.slice(idx + 2);
        if (!line.startsWith("data:")) continue;
        let msg;
        try {
          msg = JSON.parse(line.slice(5));
        } catch {
          continue;
        }
        if (msg.chunk) handlers.onChunk?.(msg.chunk);
        else if (msg.done) { handlers.onDone?.(msg.result ?? msg.text); return; }
        else if (msg.error) { handlers.onError?.(msg.error); return; }
      }
    }
    handlers.onError?.("连接中断");
  } catch (e) {
    handlers.onError?.(e.message);
  }
}

/* ---------------- 生成简历 ---------------- */

async function runGenerate() {
  if (!ensureConfigured()) return;
  const btn = document.getElementById("btnAiGenerate");
  const brief = {
    title: document.getElementById("aiGenTitle").value.trim(),
    name: document.getElementById("aiGenName").value.trim(),
    years: document.getElementById("aiGenYears").value.trim(),
    location: document.getElementById("aiGenLocation").value.trim(),
    skills: document.getElementById("aiGenSkills").value.trim(),
    highlights: document.getElementById("aiGenHighlights").value.trim(),
    education: document.getElementById("aiGenEducation").value.trim(),
  };
  if (!brief.title) {
    setStatus("aiGenStatus", "请填写目标岗位", "error");
    return;
  }
  busy(btn, "生成中…");
  let received = 0;
  setStatus("aiGenStatus", "AI 正在生成…");
  document.getElementById("aiGenResult").hidden = true;
  await streamLlm("generate", { brief }, {
    onChunk: (chunk) => {
      received += chunk.length;
      setStatus("aiGenStatus", `生成中… 已接收 ${received} 字`);
    },
    onDone: (r) => {
      renderGenerateResult(r.content);
      setStatus("aiGenStatus", "✅ 生成完成", "ok");
      unbusy(btn);
    },
    onError: (msg) => {
      setStatus("aiGenStatus", msg, "error");
      unbusy(btn);
    },
  });
}

function renderGenerateResult(content) {
  const box = document.getElementById("aiGenResult");
  box.textContent = "";
  const lines = [];
  const p = content.profile || {};
  if (p.name || p.title) lines.push(`👤 ${p.name || ""} ${p.title || ""}`.trim());
  if (p.summary) lines.push(`📝 ${p.summary}`);
  for (const [key, label] of [["workExperiences", "工作经历"], ["projects", "项目经历"], ["educations", "教育经历"]]) {
    const items = content[key] || [];
    if (items.length) lines.push(`\n■ ${label}（${items.length} 条）`);
    for (const it of items.slice(0, 3)) {
      const head = it.company || it.project || it.school || "";
      const role = it.jobTitle || it.degree || "";
      lines.push(`  • ${head}${role ? " · " + role : ""}${it.date ? "（" + it.date + "）" : ""}`);
    }
    if (items.length > 3) lines.push(`  • …等 ${items.length} 条`);
  }
  const sk = content.skills || {};
  const skillNames = (sk.featuredSkills || []).map((s) => s.skill).filter(Boolean);
  if (skillNames.length) lines.push(`\n■ 技能：${skillNames.join(" / ")}`);

  const pre = document.createElement("div");
  pre.className = "ai-card";
  pre.style.whiteSpace = "pre-wrap";
  pre.textContent = lines.join("\n") || "（生成内容为空）";
  box.appendChild(pre);

  const actions = document.createElement("div");
  actions.className = "ai-actions";
  const btnNew = document.createElement("button");
  btnNew.className = "btn btn-primary btn-sm";
  btnNew.type = "button";
  btnNew.textContent = "应用到新文档";
  btnNew.addEventListener("click", () => applyGenerated(content, false));
  const btnReplace = document.createElement("button");
  btnReplace.className = "btn btn-sm";
  btnReplace.type = "button";
  btnReplace.textContent = "替换当前文档内容";
  btnReplace.addEventListener("click", () => applyGenerated(content, true));
  actions.appendChild(btnNew);
  actions.appendChild(btnReplace);
  box.appendChild(actions);
  box.hidden = false;
}

async function applyGenerated(content, replaceCurrent) {
  try {
    let doc;
    if (replaceCurrent && store.doc) {
      doc = store.doc;
      doc.content = content;
      const { document: saved } = await api.saveDocument(doc.id, doc);
      store.setDocument(saved);
    } else {
      const { document: created } = await api.createDocument("classic", "AI 生成简历");
      created.content = content;
      const { document: saved } = await api.saveDocument(created.id, created);
      store.setDocument(saved);
    }
    renderForm(document.getElementById("formArea"));
    closeAiPanel();
    toastSuccess(replaceCurrent ? "已替换当前文档内容" : "已生成新文档，可在表单中继续修改");
  } catch (e) {
    toastError("应用失败：" + e.message);
  }
}

/* ---------------- 修改建议 ---------------- */

async function runSuggest() {
  if (!ensureConfigured()) return;
  if (!store.doc) return;
  const btn = document.getElementById("btnAiSuggest");
  busy(btn, "分析中…");
  setStatus("aiSuggestStatus", "AI 正在通读简历…");
  document.getElementById("aiSuggestResult").hidden = true;
  try {
    const r = await api.postJson("/api/v1/llm/suggest", { document: store.doc });
    renderSuggestions(r);
    setStatus("aiSuggestStatus", `✅ 共 ${r.suggestions.length} 条建议`, "ok");
  } catch (e) {
    setStatus("aiSuggestStatus", e.message, "error");
  } finally {
    unbusy(btn);
  }
}

const PRIO_LABEL = { high: "重要", medium: "建议", low: "可选" };

function renderSuggestions(r) {
  const box = document.getElementById("aiSuggestResult");
  box.textContent = "";
  if (r.summary) {
    const s = document.createElement("div");
    s.className = "ai-card";
    s.style.background = "var(--accent-soft)";
    s.innerHTML = "<b>总体评价：</b>";
    s.appendChild(document.createTextNode(r.summary));
    box.appendChild(s);
  }
  for (const sug of r.suggestions) {
    const card = document.createElement("div");
    card.className = "ai-card";
    const head = document.createElement("div");
    head.className = "ai-card-head";
    const prio = document.createElement("span");
    prio.className = `ai-prio ${sug.priority}`;
    prio.textContent = PRIO_LABEL[sug.priority] || sug.priority;
    head.appendChild(prio);
    const title = document.createElement("span");
    title.className = "ai-card-title";
    title.textContent = sug.section || "整体";
    head.appendChild(title);
    card.appendChild(head);
    if (sug.issue) {
      const p = document.createElement("p");
      p.innerHTML = "<b>问题：</b>";
      p.appendChild(document.createTextNode(sug.issue));
      card.appendChild(p);
    }
    const p2 = document.createElement("p");
    p2.innerHTML = "<b>建议：</b>";
    p2.appendChild(document.createTextNode(sug.suggestion));
    card.appendChild(p2);
    if (sug.example) {
      const ex = document.createElement("div");
      ex.className = "ai-example";
      ex.textContent = "示例：" + sug.example;
      card.appendChild(ex);
      const copy = document.createElement("button");
      copy.className = "btn btn-sm btn-ghost";
      copy.type = "button";
      copy.style.marginTop = "6px";
      copy.textContent = "复制示例";
      copy.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(sug.example);
          toastSuccess("已复制");
        } catch {
          toast("复制失败，请手动选择", "error");
        }
      });
      card.appendChild(copy);
    }
    box.appendChild(card);
  }
  box.hidden = r.suggestions.length === 0 && !r.summary;
}

/* ---------------- JD 定制 ---------------- */

async function runTailor() {
  if (!ensureConfigured()) return;
  if (!store.doc) return;
  const jd = document.getElementById("aiJdText").value.trim();
  if (!jd) {
    setStatus("aiJdStatus", "请先粘贴 JD", "error");
    return;
  }
  const btn = document.getElementById("btnAiJd");
  busy(btn, "定制中…");
  setStatus("aiJdStatus", "AI 正在按 JD 改写…");
  document.getElementById("aiJdResult").hidden = true;
  try {
    const r = await api.postJson("/api/v1/llm/tailor", { document: store.doc, jd });
    renderTailor(r);
    setStatus("aiJdStatus", `✅ ${r.rewrites.length} 条改写建议`, "ok");
  } catch (e) {
    setStatus("aiJdStatus", e.message, "error");
  } finally {
    unbusy(btn);
  }
}

function renderTailor(r) {
  const box = document.getElementById("aiJdResult");
  box.textContent = "";
  if (r.summary) {
    const s = document.createElement("div");
    s.className = "ai-card";
    s.style.background = "var(--accent-soft)";
    s.innerHTML = "<b>匹配度简评：</b>";
    s.appendChild(document.createTextNode(r.summary));
    box.appendChild(s);
  }
  if (r.missing?.length) {
    const m = document.createElement("div");
    m.className = "ai-card";
    m.innerHTML = "<b>JD 要求但简历未体现：</b>";
    const row = document.createElement("div");
    row.className = "ai-missing";
    for (const k of r.missing) {
      const tag = document.createElement("span");
      tag.className = "rtag";
      tag.textContent = k;
      row.appendChild(tag);
    }
    m.appendChild(row);
    box.appendChild(m);
  }
  for (const rw of r.rewrites) {
    const card = document.createElement("div");
    card.className = "ai-card";
    const head = document.createElement("div");
    head.className = "ai-card-head";
    const title = document.createElement("span");
    title.className = "ai-card-title";
    title.textContent = `${rw.section} #${rw.index + 1}`;
    head.appendChild(title);
    card.appendChild(head);
    const diff = document.createElement("div");
    diff.className = "ai-diff";
    const oldD = document.createElement("div");
    oldD.className = "old";
    oldD.textContent = rw.original;
    const newD = document.createElement("div");
    newD.className = "new";
    newD.textContent = rw.rewritten;
    diff.appendChild(oldD);
    diff.appendChild(newD);
    card.appendChild(diff);
    const apply = document.createElement("button");
    apply.className = "btn btn-sm btn-primary";
    apply.type = "button";
    apply.style.marginTop = "6px";
    apply.textContent = "应用这条";
    apply.addEventListener("click", () => applyRewrite(rw, apply));
    card.appendChild(apply);
    box.appendChild(card);
  }
  box.hidden = r.rewrites.length === 0;
}

function applyRewrite(rw, btn) {
  const path = `content.${rw.section}.${rw.index}.${rw.field}.${rw.item}`;
  if (!applyToPath(path, rw.rewritten)) {
    toast("该位置在当前文档中不存在，可能文档已变化", "error");
    return;
  }
  btn.disabled = true;
  btn.textContent = "已应用";
  toastSuccess("已应用到简历");
}

/* ---------------- 字段级润色 ---------------- */

export function openPolish(path, value, context = "") {
  polishTarget = { path, original: value, context };
  document.getElementById("polishOriginal").textContent = value;
  const ta = document.getElementById("polishResult");
  ta.value = "";
  document.getElementById("polishOverlay").hidden = false;
  requestPolish();
}

async function requestPolish() {
  if (!polishTarget) return;
  const btn = document.getElementById("btnPolishApply");
  const retry = document.getElementById("btnPolishRetry");
  btn.disabled = true;
  retry.disabled = true;
  const ta = document.getElementById("polishResult");
  ta.value = "";
  try {
    // 配置未加载过先拉一次
    if (!aiCfg) aiCfg = await api.getJson("/api/v1/llm/config");
    if (!aiCfg.configured) {
      document.getElementById("polishOverlay").hidden = true;
      openAiPanel("settings");
      setStatus("aiConfigStatus", "请先完成 AI 配置", "error");
      toast("请先配置 AI 服务", "error");
      return;
    }
    await streamLlm("polish", { text: polishTarget.original, context: polishTarget.context }, {
      onChunk: (chunk) => {
        ta.value += chunk;   // 流式逐字显示
      },
      onDone: () => {
        btn.disabled = false;
      },
      onError: (msg) => {
        if (!ta.value) ta.value = "";
        toastError("润色失败：" + msg);
      },
    });
  } finally {
    retry.disabled = false;
  }
}

function applyPolish() {
  if (!polishTarget) return;
  const value = document.getElementById("polishResult").value.trim();
  if (!value) {
    toast("改写内容为空", "error");
    return;
  }
  if (applyToPath(polishTarget.path, value)) {
    document.getElementById("polishOverlay").hidden = true;
    toastSuccess("已替换");
  } else {
    toast("应用失败：字段不存在", "error");
  }
}

function applyToPath(path, value, allowAppend = false) {
  const doc = store.doc;
  if (!doc) return false;
  const keys = path.split(".");
  let o = doc;
  for (let i = 0; i < keys.length - 1; i++) {
    o = o?.[keys[i]];
    if (o == null) return false;
  }
  const last = keys[keys.length - 1];
  if (!(last in o)) {
    // 允许向数组末尾追加新条目（如新增一条要点）
    if (allowAppend && Array.isArray(o) && /^\d+$/.test(last) && Number(last) === o.length) {
      o.push(value);
    } else {
      return false;
    }
  } else {
    o[last] = value;
  }
  store.touch();
  syncInput(path, value);
  return true;
}

/** 同步表单输入框显示（文档变了但表单不整体重渲染，避免丢焦点）。 */
function syncInput(path, value) {
  const input = document.querySelector(`[data-path="${CSS.escape(path)}"]`);
  if (!input) return;
  input.value = value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

/* ---------------- 批量润色 ---------------- */

let batchCtx = null;   // {section, targets: [{path, original}]}

/** 收集区块内所有 list 条目，打开批量润色弹窗。 */
export function openBatchPolish(section) {
  const doc = store.doc;
  if (!doc) return;
  const targets = [];
  const key = section.key;

  const collectFrom = (arr, basePath) => {
    (arr || []).forEach((v, i) => {
      const t = String(v || "").trim();
      if (t) targets.push({ path: `${basePath}.${i}`, original: t });
    });
  };

  if (section.type === "array") {
    const items = doc.content?.[key] || [];
    const listField = (section.fields || []).find((f) => f.type === "list");
    const fk = listField?.key || "descriptions";
    items.forEach((item, i) => {
      if (Array.isArray(item?.[fk])) collectFrom(item[fk], `content.${key}.${i}.${fk}`);
    });
  } else if (section.type === "skills") {
    collectFrom(doc.content?.skills?.descriptions, `content.skills.descriptions`);
  } else {
    collectFrom(contentUtil.readList(doc.content?.[key]), `content.${key}.descriptions`);
  }

  if (!targets.length) {
    toastError("该区块没有可润色的条目");
    return;
  }
  if (targets.length > 12) {
    toastError("单次最多润色 12 条，请分批");
    return;
  }
  batchCtx = { section, targets, results: null };
  document.getElementById("batchHint").textContent =
    `将按 Google XYZ 公式润色「${section.title}」的 ${targets.length} 条内容（不编造数据）。`;
  document.getElementById("batchList").textContent = "";
  document.getElementById("batchOverlay").hidden = false;
  runBatchPolish();
}

async function runBatchPolish() {
  if (!batchCtx) return;
  if (!aiCfg) aiCfg = await api.getJson("/api/v1/llm/config");
  if (!aiCfg.configured) {
    document.getElementById("batchOverlay").hidden = true;
    openAiPanel("settings");
    setStatus("aiConfigStatus", "请先完成 AI 配置", "error");
    return;
  }
  const btn = document.getElementById("btnApplyBatch");
  busy(btn, "润色中…");
  document.getElementById("batchList").textContent = "";
  const loading = el("div", "ai-status", "AI 正在批量改写，请稍候…");
  document.getElementById("batchList").appendChild(loading);
  try {
    const r = await api.postJson("/api/v1/llm/polish-batch", {
      items: batchCtx.targets.map((t) => t.original),
      context: batchCtx.section.title,
    });
    batchCtx.results = r.results;
    renderBatchPreview(r.results);
  } catch (e) {
    document.getElementById("batchList").textContent = "";
    toastError("批量润色失败：" + e.message);
  } finally {
    unbusy(btn);
  }
}

function renderBatchPreview(results) {
  const box = document.getElementById("batchList");
  box.textContent = "";
  batchCtx.targets.forEach((t, i) => {
    const card = el("div", "ai-card");
    const diff = el("div", "ai-diff");
    const oldD = el("div", "old", t.original);
    const newD = el("div", "new", results[i] || t.original);
    diff.appendChild(oldD);
    diff.appendChild(newD);
    card.appendChild(diff);
    box.appendChild(card);
  });
}

function applyBatchPolish() {
  if (!batchCtx?.results) return;
  let n = 0;
  batchCtx.targets.forEach((t, i) => {
    const v = batchCtx.results[i];
    if (!v) return;
    const keys = t.path.split(".");
    let o = store.doc;
    for (let j = 0; j < keys.length - 1; j++) o = o?.[keys[j]];
    if (o && keys[keys.length - 1] in o) {
      o[keys[keys.length - 1]] = v;
      n++;
    }
  });
  if (n) {
    store.touch();
    // 同步表单输入框
    for (const t of batchCtx.targets) {
      const input = document.querySelector(`[data-path="${CSS.escape(t.path)}"]`);
      if (input) {
        input.value = store.doc && getByPathForBatch(t.path);
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
    }
  }
  document.getElementById("batchOverlay").hidden = true;
  toastSuccess(`已应用 ${n} 条润色`);
}

function getByPathForBatch(path) {
  const keys = path.split(".");
  let o = store.doc;
  for (const k of keys) o = o?.[k];
  return o == null ? "" : String(o);
}

/* ---------------- JD 匹配（纯本地） ---------------- */

const CAT_LABEL = { skill: "硬技能", education: "学历", position: "职位", soft: "软技能" };

async function runMatch() {
  if (!store.doc) return;
  const jd = document.getElementById("aiMatchJd").value.trim();
  if (!jd) {
    setStatus("aiMatchStatus", "请先粘贴 JD", "error");
    return;
  }
  const btn = document.getElementById("btnAiMatch");
  busy(btn, "分析中…");
  setStatus("aiMatchStatus", "");
  try {
    const r = await api.postJson("/api/v1/analyze", { document: store.doc, jd });
    renderMatch(r);
    setStatus("aiMatchStatus", `匹配率 ${r.score}%`, r.score >= 75 ? "ok" : "error");
  } catch (e) {
    setStatus("aiMatchStatus", e.message, "error");
  } finally {
    unbusy(btn);
  }
}

function renderMatch(r) {
  const box = document.getElementById("aiMatchResult");
  box.textContent = "";

  const head = el("div", "ai-card");
  head.style.background = r.score >= 75 ? "var(--accent-soft)" : r.score >= 60 ? "var(--warn-soft)" : "var(--danger-soft)";
  const score = el("div", null);
  score.style.fontSize = "26px";
  score.style.fontWeight = "800";
  score.style.color = r.score >= 75 ? "var(--ok)" : r.score >= 60 ? "var(--warn)" : "var(--danger)";
  score.textContent = `${r.score}%`;
  head.appendChild(score);
  const sub = el("div", null);
  sub.style.fontSize = "12px";
  sub.style.color = "var(--muted)";
  sub.textContent = `匹配 ${r.matchedCount} 项 · 缺失 ${r.missingCount} 项`;
  head.appendChild(sub);
  box.appendChild(head);

  for (const s of r.suggestions || []) {
    const p = el("p");
    p.style.fontSize = "12px";
    p.style.color = "var(--text-2)";
    p.style.lineHeight = "1.7";
    p.textContent = "• " + s;
    box.appendChild(p);
  }

  if (r.missing?.length) {
    const t = el("div", "design-group-title");
    t.style.marginTop = "12px";
    t.textContent = "缺失关键词（按权重排序）";
    box.appendChild(t);
    const row = el("div", "ai-missing");
    for (const m of r.missing) {
      const tag = el("span", "rtag", m.keyword);
      tag.title = `${CAT_LABEL[m.category] || m.category} · 权重 ${m.weight}`;
      row.appendChild(tag);
    }
    box.appendChild(row);
  }
  box.hidden = false;
}

/* ---------------- 对话式迭代 ---------------- */

let chatMessages = [];
let chatStreaming = false;

async function sendChat() {
  if (!ensureConfigured()) return;
  const input = document.getElementById("chatInput");
  const text = input.value.trim();
  if (!text || chatStreaming) return;

  if (!chatMessages.length) {
    // 首条消息：把当前简历 + 修改协议交给 AI
    chatMessages.push({
      role: "user",
      content:
        "这是我的简历数据（JSON）：\n" + JSON.stringify(store.doc.content) +
        "\n\n【修改协议】后续我让你修改简历时，你必须严格按这个 JSON 格式回复（可包在 ```json 代码块里）：\n" +
        '{"reply":"给用户的简短说明","edits":[{"path":"content.workExperiences.0.descriptions.0","old":"原文","new":"修改后的文本"}]}\n' +
        "路径规则：从 content 起按简历结构寻址，如 content.profile.name（姓名）、content.profile.title（职位）、" +
        "content.workExperiences.0.descriptions.1（第1段工作经历的第2条要点）、content.projects.0.descriptions.0、" +
        "content.educations.0.descriptions.0、content.skills.descriptions.0（第1条技能）、" +
        "content.selfEvaluation.descriptions.0（自我评价第1条）。" +
        "只输出需要改的条目、不要输出整份简历；纯问答时正常自然语言回复、不要带 edits。",
    });
    // 该上下文消息不展示
  }
  chatMessages.push({ role: "user", content: text });
  input.value = "";
  chatStreaming = true;
  renderChatLog();
  const bubble = appendChatBubble("assistant", "");
  let acc = "";
  const looksLikePlan = () => {
    const t = acc.trimStart();
    return t.startsWith("{") || t.startsWith("```");
  };

  await streamChat(chatMessages, {
    onChunk: (c) => {
      acc += c;
      // 流式过程中如果是方案 JSON，先显示占位，避免刷一屏原始 JSON
      bubble.textContent = looksLikePlan() ? "⏳ 正在生成修改方案…" : acc;
      bubble.parentElement.scrollIntoView({ block: "end" });
    },
    onDone: (r) => {
      const full = r.text || acc;
      chatMessages.push({ role: "assistant", content: full });
      chatStreaming = false;
      const plan = parseEditPlan(full);
      if (plan && plan.edits.length) {
        bubble.textContent = plan.reply || "修改方案如下：";
        renderPlanCard(bubble.parentElement, plan.edits);
      } else {
        bubble.textContent = full;
        addChatActions(bubble.parentElement, full);
      }
    },
    onError: (msg) => {
      bubble.textContent = "⚠️ " + msg;
      chatStreaming = false;
    },
  });
}

function renderChatLog() {
  const log = document.getElementById("chatLog");
  log.textContent = "";
  // 跳过第一条上下文消息
  const visible = chatMessages.slice(1);
  if (!visible.length) {
    const hint = el("div", "chat-empty-hint");
    hint.textContent = "直接说你要改什么，AI 会生成修改方案，确认后一键应用：" + String.fromCharCode(10) +
      "· 把第一条工作经历改短，突出量化结果" + String.fromCharCode(10) +
      "· 补充项目经历里的技术细节" + String.fromCharCode(10) +
      "· 专业技能按「后端」方向重写" + String.fromCharCode(10) +
      "· 自我评价压到两行以内";
    hint.style.whiteSpace = "pre-line";
    log.appendChild(hint);
    return;
  }
  for (const m of visible) {
    appendChatBubble(m.role, m.content, true);
  }
  log.scrollTop = log.scrollHeight;
}

function appendChatBubble(role, text, withActions = false) {
  const log = document.getElementById("chatLog");
  const wrap = el("div", "chat-msg " + role);
  const bubble = el("div", "chat-bubble", text);
  wrap.appendChild(bubble);
  if (withActions && role === "assistant") addChatActions(wrap, text);
  log.appendChild(wrap);
  log.scrollTop = log.scrollHeight;
  return bubble;
}

function addChatActions(wrap, text) {
  const acts = el("div", "chat-acts");
  const copy = el("button", "btn btn-sm btn-ghost", "复制");
  copy.type = "button";
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(text);
      toastSuccess("已复制");
    } catch {
      toast("复制失败", "error");
    }
  });
  acts.appendChild(copy);
  wrap.appendChild(acts);
}

/** 从回复中解析修改方案 JSON（容忍 ```json 围栏和前后杂音）。 */
function parseEditPlan(text) {
  const t = String(text || "").trim();
  if (!t) return null;
  let raw = "";
  const fence = t.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fence) {
    raw = fence[1].trim();
  } else {
    const s = t.indexOf("{");
    const e = t.lastIndexOf("}");
    if (s < 0 || e <= s) return null;
    raw = t.slice(s, e + 1);
  }
  try {
    const obj = JSON.parse(raw);
    if (!obj || !Array.isArray(obj.edits)) return null;
    const edits = obj.edits
      .filter((e) => e && typeof e.path === "string" && typeof e.new === "string")
      .map((e) => ({ path: e.path, new: e.new, old: typeof e.old === "string" ? e.old : "" }));
    return edits.length ? { reply: String(obj.reply || "").trim(), edits } : null;
  } catch {
    return null;
  }
}

/** 把 content.xxx.0.descriptions.1 之类的路径翻译成人话。 */
function formatEditPath(path) {
  const parts = String(path || "").replace(/^content\./, "").split(".");
  const sections = {
    profile: "基本信息", workExperiences: "工作经历", projects: "项目经历",
    educations: "教育经历", skills: "专业技能", selfEvaluation: "自我评价", certificates: "证书",
  };
  const fields = {
    descriptions: "要点", featuredSkills: "技能", name: "姓名", title: "职位",
    email: "邮箱", phone: "电话", location: "城市", company: "公司", jobTitle: "职位",
    project: "项目", school: "学校", degree: "学历", skill: "技能",
  };
  let label = sections[parts[0]] || parts[0] || "?";
  let i = 1;
  if (/^\d+$/.test(parts[i] || "")) {
    label += ` #${Number(parts[i]) + 1}`;
    i++;
  }
  if (parts[i]) label += ` · ${fields[parts[i]] || parts[i]}`;
  if (/^\d+$/.test(parts[i + 1] || "")) label += ` ${Number(parts[i + 1]) + 1}`;
  return label;
}

/** 渲染修改方案卡片（差异预览 + 应用全部）。 */
function renderPlanCard(wrap, edits) {
  const card = el("div", "ai-card chat-plan");
  const head = el("div", "ai-card-head");
  const title = el("span", "ai-card-title");
  title.textContent = `修改方案（${edits.length} 处）`;
  head.appendChild(title);
  card.appendChild(head);
  for (const e of edits) {
    const row = el("div", "plan-row");
    const loc = el("div", "plan-loc");
    loc.textContent = formatEditPath(e.path);
    row.appendChild(loc);
    const diff = el("div", "ai-diff");
    const oldD = el("div", "old");
    const cur = readPath(e.path);
    oldD.textContent = cur != null ? String(cur) : (e.old || "（新内容）");
    const newD = el("div", "new");
    newD.textContent = e.new;
    diff.appendChild(oldD);
    diff.appendChild(newD);
    row.appendChild(diff);
    card.appendChild(row);
  }
  const acts = el("div", "chat-acts");
  const applyBtn = el("button", "btn btn-sm btn-primary", "应用全部修改");
  applyBtn.type = "button";
  applyBtn.addEventListener("click", () => {
    const r = applyChatEdits(edits);
    if (r.ok) {
      applyBtn.disabled = true;
      applyBtn.textContent = "已应用";
      card.classList.add("applied");
      // 让后续对话知道已应用，保持上下文一致
      chatMessages.push({ role: "user", content: "[系统] 以上修改已全部应用到简历。" });
    }
    if (r.failed.length) {
      toast(`${r.failed.length} 处应用失败：${r.failed.map(formatEditPath).join("、")}`, "error");
    }
    if (r.ok) toastSuccess(`已应用 ${r.ok} 处修改（Ctrl+Z 可撤销）`);
  });
  const discard = el("button", "btn btn-sm btn-ghost", "忽略");
  discard.type = "button";
  discard.addEventListener("click", () => {
    card.remove();
  });
  acts.appendChild(applyBtn);
  acts.appendChild(discard);
  card.appendChild(acts);
  wrap.appendChild(card);
}

/** 读取路径当前值（不存在返回 null）。 */
function readPath(path) {
  let o = store.doc;
  for (const k of String(path || "").split(".")) {
    if (o == null) return null;
    o = o[k];
  }
  return o === undefined ? null : o;
}

/** 应用对话方案：逐条写入，返回成功/失败统计。 */
function applyChatEdits(edits) {
  let ok = 0;
  const failed = [];
  for (const e of edits) {
    if (applyToPath(e.path, e.new, true)) ok++;
    else failed.push(e.path);
  }
  return { ok, failed };
}

/* ---------------- 获取模型列表 ---------------- */

async function fetchModels() {
  const btn = document.getElementById("btnFetchModels");
  // 先把当前填的配置保存，确保服务端拿到最新的 base_url/key/format
  await saveAiConfig();
  busy(btn, "获取中…");
  const dd = document.getElementById("modelDropdown");
  dd.textContent = "";
  dd.hidden = false;
  const loading = el("div", "model-dd-item model-dd-loading", "正在从服务商拉取模型列表…");
  dd.appendChild(loading);
  try {
    const r = await api.getJson("/api/v1/llm/models");
    dd.textContent = "";
    if (!r.models?.length) {
      dd.appendChild(el("div", "model-dd-empty", "服务商未返回任何模型"));
      return;
    }
    for (const m of r.models) {
      const item = el("button", "model-dd-item" + (m.id === document.getElementById("aiModel").value ? " active" : ""), m.name || m.id);
      item.type = "button";
      item.title = m.id;
      item.addEventListener("click", () => {
        document.getElementById("aiModel").value = m.id;
        dd.hidden = true;
        setStatus("aiConfigStatus", `已选择模型 ${m.id}`, "");
        scheduleAiConfigSave();
      });
      dd.appendChild(item);
    }
    setStatus("aiConfigStatus", `共 ${r.models.length} 个可用模型，点击选择`, "ok");
  } catch (e) {
    dd.textContent = "";
    dd.appendChild(el("div", "model-dd-empty", e.message));
    setStatus("aiConfigStatus", e.message, "error");
  } finally {
    unbusy(btn);
  }
}

/* ---------------- 绑定 ---------------- */

export function bindAiPanel() {
  document.getElementById("btnAi").addEventListener("click", () => openAiPanel("generate"));
  document.getElementById("btnCloseAi").addEventListener("click", closeAiPanel);
  document.getElementById("aiOverlay").addEventListener("click", (e) => {
    if (e.target.id === "aiOverlay") closeAiPanel();
  });
  document.querySelectorAll(".ai-tab").forEach((b) =>
    b.addEventListener("click", () => switchAiTab(b.dataset.aiTab)));

  document.getElementById("btnAiSaveConfig").addEventListener("click", () => saveAiConfig());
  bindAiConfigAutosave();
  document.getElementById("aiConfigSelect").addEventListener("change", (e) => switchConfig(e.target.value));
  document.getElementById("btnNewConfig").addEventListener("click", createConfig);
  document.getElementById("btnDeleteConfig").addEventListener("click", deleteCurrentConfig);
  document.getElementById("btnFetchModels").addEventListener("click", fetchModels);
  bindAiResize();
  // 对话输入框自适应高度
  const chatInput = document.getElementById("chatInput");
  chatInput.addEventListener("input", () => {
    chatInput.style.height = "auto";
    chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + "px";
  });
  // 点击别处收起模型下拉
  document.addEventListener("click", (e) => {
    const dd = document.getElementById("modelDropdown");
    if (dd && !e.target.closest(".model-field")) dd.hidden = true;
  });
  document.getElementById("btnAiTest").addEventListener("click", testAiConnection);
  document.getElementById("aiPreset").addEventListener("change", (e) => {
    const opt = e.target.selectedOptions[0];
    if (opt?.dataset.baseUrl) {
      document.getElementById("aiBaseUrl").value = opt.dataset.baseUrl;
      document.getElementById("aiModel").value = opt.dataset.model || "";
      document.getElementById("aiFormat").value = opt.dataset.format || "openai";
      updateFormatHint();
      scheduleAiConfigSave();   // 预设带出的值也自动保存
    }
  });
  document.getElementById("aiFormat").addEventListener("change", updateFormatHint);

  document.getElementById("btnAiGenerate").addEventListener("click", runGenerate);
  document.getElementById("btnAiSuggest").addEventListener("click", runSuggest);
  document.getElementById("btnAiJd").addEventListener("click", runTailor);
  document.getElementById("btnAiMatch").addEventListener("click", runMatch);
  document.getElementById("btnMatchFillFromJd").addEventListener("click", () => {
    const v = document.getElementById("aiJdText").value.trim();
    if (v) document.getElementById("aiMatchJd").value = v;
  });
  document.getElementById("btnChatSend").addEventListener("click", sendChat);
  document.getElementById("btnApplyBatch").addEventListener("click", applyBatchPolish);
  document.getElementById("btnCloseBatch").addEventListener("click", () => (document.getElementById("batchOverlay").hidden = true));
  document.getElementById("btnCancelBatch").addEventListener("click", () => (document.getElementById("batchOverlay").hidden = true));
  document.getElementById("chatInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendChat();
    }
  });

  document.getElementById("btnPolishApply").addEventListener("click", applyPolish);
  document.getElementById("btnPolishRetry").addEventListener("click", requestPolish);
  document.getElementById("btnClosePolish").addEventListener("click", () => (document.getElementById("polishOverlay").hidden = true));
  document.getElementById("btnClosePolish2").addEventListener("click", () => (document.getElementById("polishOverlay").hidden = true));
}
