/**
 * AI 助手：生成简历 / 修改建议 / JD 定制 / 设置 + 字段级润色对话框。
 *
 * 所有请求走 /api/v1/llm/*；key 只存在本机（GET config 不返回 key）。
 */
import { store } from "../store.js";
import { api } from "../api.js";
import { toast, toastSuccess, toastError } from "./toast.js";
import { t } from "../i18n.js";
import { renderForm } from "./form.js";

let aiCfg = null;
let polishTarget = null; // {path, original, context}

/* ---------------- 面板框架 ---------------- */

export function openAiPanel(tab = "generate") {
  document.getElementById("aiOverlay").hidden = false;
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
}

function cap(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
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
}

function updateFormatHint() {
  const fmt = document.getElementById("aiFormat").value;
  const hint = document.getElementById("aiFormatHint");
  const text = FORMAT_HINTS[fmt] || "";
  hint.textContent = text;
  hint.hidden = !text;
}

async function saveAiConfig() {
  const baseUrl = document.getElementById("aiBaseUrl").value.trim();
  const model = document.getElementById("aiModel").value.trim();
  const apiKey = document.getElementById("aiApiKey").value.trim();
  const format = document.getElementById("aiFormat").value;
  const timeout = parseInt(document.getElementById("aiTimeout").value, 10) || 90;
  try {
    aiCfg = await api.putJson("/api/v1/llm/config", { base_url: baseUrl, model, api_key: apiKey, format, timeout });
    document.getElementById("aiApiKey").value = "";
    document.getElementById("aiApiKey").placeholder = "已保存（留空则不修改）";
    setStatus("aiConfigStatus", "✅ 已保存", "ok");
    toastSuccess("AI 配置已保存");
  } catch (e) {
    setStatus("aiConfigStatus", e.message, "error");
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
  setStatus("aiConfigStatus", "请先完成 AI 配置并测试连接", "error");
  toast("请先配置 AI 服务", "error");
  return false;
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
  busy(btn, "生成中…（约 10-30 秒）");
  setStatus("aiGenStatus", "AI 正在生成，请稍候…");
  document.getElementById("aiGenResult").hidden = true;
  try {
    const r = await api.postJson("/api/v1/llm/generate", { brief });
    renderGenerateResult(r.content);
    setStatus("aiGenStatus", "✅ 生成完成", "ok");
  } catch (e) {
    setStatus("aiGenStatus", e.message, "error");
  } finally {
    unbusy(btn);
  }
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
  ta.value = "AI 思考中…";
  try {
    // 配置未加载过先拉一次
    if (!aiCfg) aiCfg = await api.getJson("/api/v1/llm/config");
    if (!aiCfg.configured) {
      ta.value = "";
      document.getElementById("polishOverlay").hidden = true;
      openAiPanel("settings");
      setStatus("aiConfigStatus", "请先完成 AI 配置", "error");
      toast("请先配置 AI 服务", "error");
      return;
    }
    const r = await api.postJson("/api/v1/llm/polish", {
      text: polishTarget.original,
      context: polishTarget.context,
    });
    ta.value = r.result;
    btn.disabled = false;
  } catch (e) {
    ta.value = "";
    toastError("润色失败：" + e.message);
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

function applyToPath(path, value) {
  const doc = store.doc;
  if (!doc) return false;
  const keys = path.split(".");
  let o = doc;
  for (let i = 0; i < keys.length - 1; i++) {
    o = o?.[keys[i]];
    if (o == null) return false;
  }
  if (!(keys[keys.length - 1] in o)) return false;
  o[keys[keys.length - 1]] = value;
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

/* ---------------- 绑定 ---------------- */

export function bindAiPanel() {
  document.getElementById("btnAi").addEventListener("click", () => openAiPanel("generate"));
  document.getElementById("btnCloseAi").addEventListener("click", closeAiPanel);
  document.getElementById("aiOverlay").addEventListener("click", (e) => {
    if (e.target.id === "aiOverlay") closeAiPanel();
  });
  document.querySelectorAll(".ai-tab").forEach((b) =>
    b.addEventListener("click", () => switchAiTab(b.dataset.aiTab)));

  document.getElementById("btnAiSaveConfig").addEventListener("click", saveAiConfig);
  document.getElementById("btnAiTest").addEventListener("click", testAiConnection);
  document.getElementById("aiPreset").addEventListener("change", (e) => {
    const opt = e.target.selectedOptions[0];
    if (opt?.dataset.baseUrl) {
      document.getElementById("aiBaseUrl").value = opt.dataset.baseUrl;
      document.getElementById("aiModel").value = opt.dataset.model || "";
      document.getElementById("aiFormat").value = opt.dataset.format || "openai";
      updateFormatHint();
    }
  });
  document.getElementById("aiFormat").addEventListener("change", updateFormatHint);

  document.getElementById("btnAiGenerate").addEventListener("click", runGenerate);
  document.getElementById("btnAiSuggest").addEventListener("click", runSuggest);
  document.getElementById("btnAiJd").addEventListener("click", runTailor);

  document.getElementById("btnPolishApply").addEventListener("click", applyPolish);
  document.getElementById("btnPolishRetry").addEventListener("click", requestPolish);
  document.getElementById("btnClosePolish").addEventListener("click", () => (document.getElementById("polishOverlay").hidden = true));
  document.getElementById("btnClosePolish2").addEventListener("click", () => (document.getElementById("polishOverlay").hidden = true));
}
