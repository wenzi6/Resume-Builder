// @ts-check
/**
 * schema 驱动的表单渲染器。
 *
 * 数据流：渲染结构一次；输入事件只 mutate store.doc.content 并 store.touch()，
 * 不重渲染表单（保住输入焦点）。结构性变化（增删条目 / 上下移 / 换文档）
 * 才局部或整体重渲染。
 */

import { store, contentUtil } from "../store.js";
import { toastError, toastSuccess } from "./toast.js";
import { openPolish, openBatchPolish } from "./aiPanel.js";

/* ---------------- 图标 ---------------- */
const ICONS = {
  user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
  briefcase: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/></svg>',
  folder: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/></svg>',
  school: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="m22 9-10-5L2 9l10 5 10-5Z"/><path d="M6 11.5V16c0 1.1 2.7 3 6 3s6-1.9 6-3v-4.5"/></svg>',
  star: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="m12 2 3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2Z"/></svg>',
  quote: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 21c3 0 7-1 7-8V5c0-1.25-.756-2-2-2H4c-1.25 0-2 .75-2 2v3c0 1.25.75 2 2 2h1c1 0 1 0 1 1v1c0 1-1 2-2 2s-2 .5-2 1.5S2 21 3 21Z"/></svg>',
  dots: '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>',
  layers: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="m12 2 9 4.5-9 4.5-9-4.5L12 2Z"/><path d="m3 11.5 9 4.5 9-4.5"/></svg>',
};

function iconFor(section) {
  if (section.icon && ICONS[section.icon]) return ICONS[section.icon];
  if (section.type === "array") return ICONS.layers;
  return ICONS.dots;
}

/* ---------------- 路径工具 ---------------- */
function getByPath(obj, path) {
  return path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);
}

function setByPath(obj, path, value) {
  const keys = path.split(".");
  let o = obj;
  for (let i = 0; i < keys.length - 1; i++) {
    if (o[keys[i]] == null) o[keys[i]] = {};
    o = o[keys[i]];
  }
  o[keys[keys.length - 1]] = value;
}

/* ---------------- 小控件 ---------------- */
function el(tag, className, text) {
  const e = document.createElement(tag);
  if (className) e.className = className;
  if (text != null) e.textContent = text;
  return e;
}

function autoGrow(ta) {
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight, 220) + "px";
}

function fieldLabel(field) {
  const label = el("label", "field-label");
  label.textContent = field.label || field.key;
  if (field.required) {
    const req = el("span", "req", "*");
    label.appendChild(req);
  }
  if (field.type === "textarea") {
    const ai = el("button", "ai-field-btn", "✨");
    ai.type = "button";
    ai.title = "AI 润色这条内容";
    label.appendChild(ai);
    label._aiBtn = ai;
  }
  return label;
}

function hintOf(field) {
  if (!field.hint) return null;
  const p = el("p", "field-hint");
  p.textContent = field.hint;
  return p;
}

/** 单值字段（text / date / textarea）。 */
function renderScalarField(sectionKey, field, container, value, path) {
  const wrap = el("div", "field");
  wrap.appendChild(fieldLabel(field));
  let input;
  if (field.type === "textarea") {
    input = el("textarea", "field-textarea");
    input.rows = 2;
    input.value = value || "";
    requestAnimationFrame(() => autoGrow(input));
  } else {
    input = el("input", "field-input");
    input.type = "text";
    input.value = value || "";
    if (field.type === "date") input.placeholder = "2021-03 – 至今";
  }
  input.dataset.path = path;
  input.addEventListener("input", () => {
    if (input.tagName === "TEXTAREA") autoGrow(input);
    setByPath(store.doc, path, input.value);
    store.touch();
    if (sectionKey && field.type !== "textarea") updateItemCardTitle(wrap, sectionKey, path);
  });
  // textarea 字段：label 上的 ✦ 按钮润色整段
  if (field.type === "textarea") {
    wrap.querySelector(".ai-field-btn")?.addEventListener("click", () => {
      const v = String(getByPath(store.doc, path) || "").trim();
      if (!v) {
        toastError("请先输入内容再润色");
        return;
      }
      openPolish(path, v, `${sectionKey || ""} ${field.label || ""}`.trim());
    });
  }
  wrap.appendChild(input);
  const hint = hintOf(field);
  if (hint) wrap.appendChild(hint);
  container.appendChild(wrap);
  return wrap;
}

/** 列表字段：每行一条，可增删、上下移。 */
function renderListField(sectionKey, field, container, items, basePath, opts = {}) {
  const wrap = el("div", "field");
  const label = fieldLabel(field);
  wrap.appendChild(label);
  if (field.hint) wrap.appendChild(hintOf(field));

  const list = el("div", "list-editor");
  const rows = Array.isArray(items) ? items : [];

  const renderRows = () => {
    list.textContent = "";
    rows.forEach((val, i) => {
      const row = el("div", "list-row");
      const ta = el("textarea", "field-textarea");
      ta.rows = 1;
      ta.value = val == null ? "" : String(val);
      ta.placeholder = opts.placeholder || "每行一条内容";
      ta.dataset.path = `${basePath}.${i}`;
      ta.addEventListener("input", () => {
        autoGrow(ta);
        rows[i] = ta.value;
        setByPath(store.doc, basePath, rows);
        store.touch();
      });
      row.appendChild(ta);

      // 行内 AI 润色
      const ai = el("button", "ai-field-btn", "✨");
      ai.type = "button";
      ai.title = "AI 润色这一条";
      ai.addEventListener("click", () => {
        const v = String(rows[i] || "").trim();
        if (!v) {
          toastError("请先输入内容再润色");
          return;
        }
        openPolish(`${basePath}.${i}`, v, `${field.label || ""}`.trim());
      });
      row.appendChild(ai);

      const up = el("button", "list-row-act", "↑");
      up.type = "button";
      up.title = "上移";
      up.disabled = i === 0;
      up.style.opacity = i === 0 ? "0.35" : "";
      up.addEventListener("click", () => {
        [rows[i - 1], rows[i]] = [rows[i], rows[i - 1]];
        setByPath(store.doc, basePath, rows);
        store.touch();
        renderRows();
      });
      row.appendChild(up);

      const down = el("button", "list-row-act", "↓");
      down.type = "button";
      down.title = "下移";
      down.disabled = i === rows.length - 1;
      down.style.opacity = i === rows.length - 1 ? "0.35" : "";
      down.addEventListener("click", () => {
        [rows[i + 1], rows[i]] = [rows[i], rows[i + 1]];
        setByPath(store.doc, basePath, rows);
        store.touch();
        renderRows();
      });
      row.appendChild(down);

      const del = el("button", "list-row-act danger", "✕");
      del.type = "button";
      del.title = "删除";
      del.addEventListener("click", () => {
        rows.splice(i, 1);
        setByPath(store.doc, basePath, rows);
        store.touch();
        renderRows();
      });
      row.appendChild(del);

      list.appendChild(row);
      requestAnimationFrame(() => autoGrow(ta));
    });
  };

  renderRows();

  const add = el("button", "add-btn", "+ 添加一行");
  add.type = "button";
  add.addEventListener("click", () => {
    rows.push("");
    setByPath(store.doc, basePath, rows);
    store.touch();
    renderRows();
    const tas = list.querySelectorAll("textarea");
    tas[tas.length - 1]?.focus();
  });
  wrap.appendChild(list);
  wrap.appendChild(add);
  container.appendChild(wrap);
  return wrap;
}

/** 更新数组条目卡片标题（输入主标题字段时实时同步）。 */
function updateItemCardTitle(inputEl, sectionKey, path) {
  const card = inputEl.closest(".item-card");
  if (!card) return;
  const titleEl = card.querySelector(".item-card-title");
  if (!titleEl) return;
  const m = path.match(new RegExp(`^content\\.${sectionKey}\\.(\\d+)\\.(.+)$`));
  if (!m) return;
  const idx = Number(m[1]);
  const fieldKey = m[2];
  const section = store.doc.sections.find((s) => s.key === sectionKey);
  if (!section) return;
  const titleField = titleFieldOf(section);
  if (!titleField || fieldKey !== titleField) return;
  const item = store.doc.content?.[sectionKey]?.[idx];
  titleEl.textContent = (item && String(item[titleField] || "").trim()) || `第 ${idx + 1} 条`;
}

function titleFieldOf(section) {
  const candidates = ["name", "company", "school", "project", "title"];
  for (const f of section.fields || []) {
    if (candidates.includes(f.key)) return f.key;
  }
  return null;
}

/* ---------------- 区块渲染 ---------------- */

function renderSectionForm(section) {
  const doc = store.doc;
  const sec = el("section", "form-section");
  sec.id = `form-${section.key}`;
  sec.dataset.section = section.key;

  const head = el("header");
  const icon = el("span", "form-sec-icon");
  icon.innerHTML = iconFor(section);
  head.appendChild(icon);
  const title = el("span", "form-sec-title", section.title || section.key);
  head.appendChild(title);

  // 区块级设计覆盖（双列 / 隐藏标题）
  if (section.type !== "object") {
    const gear = el("button", "sec-act", "⚙");
    gear.type = "button";
    gear.title = "区块排版设置";
    gear.addEventListener("click", () => openSectionDesign(section));
    head.appendChild(gear);
  }

  const typeBadge = el("span", "sec-type", {
    object: "单组", array: "列表", skills: "技能", simple: "文本",
  }[section.type] || section.type);
  head.appendChild(typeBadge);

  // 批量润色（有 list 字段的区块）
  const hasList = (section.fields || []).some((f) => f.type === "list") || section.type === "skills";
  if (hasList && section.type !== "object") {
    const batch = el("button", "sec-act", "✨");
    batch.type = "button";
    batch.title = "AI 批量润色本区块所有条目";
    batch.style.color = "#7c3aed";
    batch.addEventListener("click", () => openBatchPolish(section));
    head.appendChild(batch);
  }

  const visBtn = el("button", "sec-act", section.visible === false ? "🚫" : "👁");
  visBtn.type = "button";
  visBtn.title = section.visible === false ? "当前隐藏，点击显示" : "点击在简历中隐藏";
  if (section.visible === false) visBtn.classList.add("off");
  visBtn.addEventListener("click", () => {
    section.visible = section.visible === false;
    store.touch();
    renderForm(document.getElementById("formArea"));
  });
  head.appendChild(visBtn);
  sec.appendChild(head);

  const body = el("div", "form-sec-body");
  sec.appendChild(body);

  if (section.visible === false) {
    const tip = el("p", "field-hint", "该区块已在简历中隐藏，内容仍会保留。");
    body.appendChild(tip);
  } else {
    renderSectionBody(section, body);
  }
  return sec;
}

function renderSectionBody(section, body) {
  const doc = store.doc;
  const key = section.key;

  if (section.type === "object") {
    const data = (doc.content[key] = doc.content[key] || {});
    for (const f of section.fields || []) {
      renderScalarField(key, f, body, data[f.key], `content.${key}.${f.key}`);
    }
    return;
  }

  if (section.type === "array") {
    const items = contentUtil.ensureArray(doc.content, key);
    items.forEach((item, idx) => body.appendChild(renderArrayItem(section, item, idx)));
    const add = el("button", "add-btn", `+ 添加${section.itemLabel || "一条记录"}`);
    add.type = "button";
    add.addEventListener("click", () => {
      const blank = {};
      for (const f of section.fields || []) {
        blank[f.key] = f.type === "list" ? [] : "";
      }
      items.push(blank);
      store.touch();
      body.insertBefore(renderArrayItem(section, blank, items.length - 1), add);
      add.scrollIntoView({ block: "nearest" });
    });
    body.appendChild(add);
    return;
  }

  if (section.type === "skills") {
    const data = contentUtil.ensureDict(doc.content, key);
    const featured = (data.featuredSkills = Array.isArray(data.featuredSkills) ? data.featuredSkills : []);

    // 主要技能（名称 + 星级）
    const fg = el("div", "field");
    fg.appendChild(fieldLabel({ label: "主要技能（带熟练度）" }));
    const rows = el("div");
    featured.forEach((fs, i) => rows.appendChild(renderSkillRow(featured, fs, i)));
    fg.appendChild(rows);
    const addSkill = el("button", "add-btn", "+ 添加技能");
    addSkill.type = "button";
    addSkill.addEventListener("click", () => {
      featured.push({ skill: "", rating: 3 });
      store.touch();
      fg.insertBefore(renderSkillRow(featured, featured[featured.length - 1], featured.length - 1), addSkill);
    });
    fg.appendChild(addSkill);
    body.appendChild(fg);

    // 其他技能（标签行）
    renderListField(
      key,
      { label: "其他技能（标签）", hint: "每行一个，如 Webpack / Vite" },
      body,
      data.descriptions,
      `content.${key}.descriptions`,
      { placeholder: "技能名称" },
    );
    return;
  }

  // simple
  const data = contentUtil.ensureDict(doc.content, key);
  renderListField(key, section.fields?.[0] || { label: "内容" }, body, data.descriptions, `content.${key}.descriptions`);
}

function renderArrayItem(section, item, idx) {
  const card = el("div", "item-card");
  card.dataset.index = idx;

  const head = el("header");
  const num = el("span", "item-num", String(idx + 1));
  head.appendChild(num);
  const titleField = titleFieldOf(section);
  const cardTitle = el("span", "item-card-title", (titleField && String(item[titleField] || "").trim()) || `第 ${idx + 1} 条`);
  head.appendChild(cardTitle);

  const acts = el("span", "sec-actions");
  const mk = (label, title, fn, danger) => {
    const b = el("button", "sec-act" + (danger ? " danger" : ""), label);
    b.type = "button";
    b.title = title;
    b.addEventListener("click", fn);
    acts.appendChild(b);
    return b;
  };
  const items = contentUtil.ensureArray(store.doc.content, section.key);
  mk("↑", "上移", () => moveItem(section, idx, -1), false).style.opacity = idx === 0 ? "0.35" : "";
  mk("↓", "下移", () => moveItem(section, idx, 1), false).style.opacity =
    idx === items.length - 1 ? "0.35" : "";
  mk("✕", "删除此条", () => {
    items.splice(idx, 1);
    store.touch();
    card.remove();
    // 重新编号
    const body = card.parentElement;
    if (body) {
      body.querySelectorAll(".item-card").forEach((c, i) => {
        c.querySelector(".item-num").textContent = String(i + 1);
        c.dataset.index = i;
      });
    }
  }, true);
  head.appendChild(acts);
  card.appendChild(head);

  const body = el("div", "item-card-body");
  for (const f of section.fields || []) {
    if (f.type === "list") {
      const arr = Array.isArray(item[f.key]) ? item[f.key] : [];
      item[f.key] = arr;
      renderListField(section.key, f, body, arr, `content.${section.key}.${idx}.${f.key}`, {
        placeholder: `${f.label || "内容"}…`,
      });
    } else {
      renderScalarField(section.key, f, body, item[f.key], `content.${section.key}.${idx}.${f.key}`);
    }
  }
  card.appendChild(body);
  return card;
}

function moveItem(section, idx, dir) {
  const items = store.doc.content[section.key];
  const target = idx + dir;
  if (target < 0 || target >= items.length) return;
  [items[idx], items[target]] = [items[target], items[idx]];
  store.touch();
  renderForm(document.getElementById("formArea"));
}

function renderSkillRow(featured, fs, idx) {
  const row = el("div", "skill-row");
  const input = el("input", "field-input");
  input.type = "text";
  input.value = fs.skill || "";
  input.placeholder = "技能名称，如 React";
  input.addEventListener("input", () => {
    featured[idx].skill = input.value;
    store.touch();
  });
  row.appendChild(input);

  const rating = el("span", "rating");
  rating.title = "熟练度";
  for (let s = 1; s <= 5; s++) {
    const star = el("button", "rating-star" + (s <= (fs.rating || 0) ? " on" : ""), "★");
    star.type = "button";
    star.title = `${s} 星`;
    star.addEventListener("click", () => {
      featured[idx].rating = s;
      store.touch();
      rating.querySelectorAll(".rating-star").forEach((b, i) => b.classList.toggle("on", i < s));
    });
    rating.appendChild(star);
  }
  row.appendChild(rating);

  const del = el("button", "list-row-act danger", "✕");
  del.type = "button";
  del.title = "删除";
  del.addEventListener("click", () => {
    featured.splice(idx, 1);
    store.touch();
    row.remove();
  });
  row.appendChild(del);
  return row;
}

/* ---------------- 整体渲染 ---------------- */

/** 全量渲染表单（换文档 / 区块结构变化时调用）。 */
export function renderForm(container) {
  const doc = store.doc;
  container.textContent = "";
  if (!doc) {
    container.appendChild(el("div", "editor-loading", "没有打开的文档"));
    return;
  }
  const sections = (doc.sections || []).filter((s) => s && s.key);
  if (!sections.length) {
    container.appendChild(el("div", "editor-loading", "没有任何区块，请在左侧「添加区块」"));
    return;
  }
  for (const s of sections) container.appendChild(renderSectionForm(s));
}

/** 单个区块的表单重渲染（区块配置变化时）。 */
export function rerenderSectionForm(key) {
  const old = document.getElementById(`form-${CSS.escape(key)}`);
  const doc = store.doc;
  const section = doc?.sections?.find((s) => s.key === key);
  if (!old || !section) {
    renderForm(document.getElementById("formArea"));
    return;
  }
  old.replaceWith(renderSectionForm(section));
}


/* ---------------- 区块排版设置 ---------------- */

let secDesignTarget = null;

export function openSectionDesign(section) {
  secDesignTarget = section;
  const d = section.design || {};
  document.getElementById("secCols").value = String(d.columns || 1);
  document.getElementById("secHideTitle").checked = !!d.hideTitle;
  document.getElementById("secDesignOverlay").hidden = false;
}

export function bindSectionDesign() {
  document.getElementById("btnSaveSecDesign").addEventListener("click", () => {
    if (!secDesignTarget) return;
    const cols = parseInt(document.getElementById("secCols").value, 10) || 1;
    const hide = document.getElementById("secHideTitle").checked;
    const design = {};
    if (cols === 2) design.columns = 2;
    if (hide) design.hideTitle = true;
    if (Object.keys(design).length) secDesignTarget.design = design;
    else delete secDesignTarget.design;
    store.touch();
    document.getElementById("secDesignOverlay").hidden = true;
    toastSuccess("区块排版已更新");
  });
  document.getElementById("btnCloseSecDesign").addEventListener("click", () => {
    document.getElementById("secDesignOverlay").hidden = true;
  });
  document.getElementById("secDesignOverlay").addEventListener("click", (e) => {
    if (e.target.id === "secDesignOverlay") e.target.hidden = true;
  });
}

export function scrollToSection(key) {
  document.getElementById(`form-${CSS.escape(key)}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
}
