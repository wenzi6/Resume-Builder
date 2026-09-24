/**
 * 设计面板：字体 / 字号 / 行距 / 间距 / 边距 / 主题色 / 日期位置 / 照片 / 压缩。
 * 面板值直接写入 doc.design，后端编译为 CSS 变量，前端不算样式。
 */

import { store } from "../store.js";

const LIMITS = {
  fontScale: [0.9, 1.15],
  lineHeight: [1.2, 1.8],
  sectionGap: [8, 32],
  pageMargin: [12.7, 25],
};

const ACCENT_PRESETS = [
  "#0f766e", "#1f4e79", "#1d4ed8", "#7c2d12", "#111827",
  "#b91c1c", "#c2410c", "#4d7c0f", "#0e7490", "#6d28d9",
];

const COMPACT_OVERRIDES = { fontScale: 0.94, lineHeight: 1.32, sectionGap: 12, pageMargin: 15 };

function el(tag, className, text) {
  const e = document.createElement(tag);
  if (className) e.className = className;
  if (text != null) e.textContent = text;
  return e;
}

function slider({ label, key, format }) {
  const [lo, hi] = LIMITS[key];
  const row = el("div", "design-row");
  row.dataset.key = key;
  const lab = el("div", "design-label");
  lab.appendChild(el("span", null, label));
  const val = el("span", "design-value");
  lab.appendChild(val);
  row.appendChild(lab);
  const input = el("input");
  input.type = "range";
  input.min = lo;
  input.max = hi;
  input.step = key === "fontScale" || key === "lineHeight" ? 0.01 : key === "pageMargin" ? 0.1 : 1;
  input.dataset.slider = key;
  input.addEventListener("input", () => {
    store.doc.design[key] = parseFloat(input.value);
    store.touch({ pageInfo: true });
    syncDesignValues();
  });
  row.appendChild(input);
  return { row, input, val, format };
}

const sliders = {};

export function renderDesignPanel(container) {
  container.textContent = "";
  const design = store.doc?.design || {};

  /* ---- 字体 ---- */
  const gFont = el("div", "design-group");
  gFont.appendChild(el("div", "design-group-title", "字体"));
  const fontRow = el("div", "design-row");
  const fontSeg = el("div", "seg");
  for (const [v, label] of [["sans", "黑体（通用）"], ["serif", "宋体（正式）"]]) {
    const b = el("button", design.fontFamily === v ? "active" : "", label);
    b.type = "button";
    b.dataset.font = v;
    b.addEventListener("click", () => {
      store.doc.design.fontFamily = v;
      store.touch();
      syncDesignValues();
    });
    fontSeg.appendChild(b);
  }
  fontRow.appendChild(fontSeg);
  gFont.appendChild(fontRow);
  container.appendChild(gFont);

  /* ---- 排版 ---- */
  const gTypo = el("div", "design-group");
  gTypo.appendChild(el("div", "design-group-title", "排版"));

  const sScale = slider({ label: "字号缩放", key: "fontScale", format: (v) => `${Math.round(v * 100)}%` });
  const sLh = slider({ label: "行距", key: "lineHeight", format: (v) => v.toFixed(2) });
  const sGap = slider({ label: "区块间距", key: "sectionGap", format: (v) => `${v}px` });
  const sMargin = slider({ label: "页边距", key: "pageMargin", format: (v) => `${v.toFixed(1)}mm` });

  sliders.fontScale = sScale;
  sliders.lineHeight = sLh;
  sliders.sectionGap = sGap;
  sliders.pageMargin = sMargin;

  for (const s of [sScale, sLh, sGap, sMargin]) {
    s.row.dataset.designKey = s.input.dataset.slider;
    gTypo.appendChild(s.row);
  }
  container.appendChild(gTypo);

  /* ---- 主题色 ---- */
  const gColor = el("div", "design-group");
  gColor.appendChild(el("div", "design-group-title", "主题色"));
  const colorRow = el("div", "design-row");
  const swatches = el("div", "swatches");
  for (const c of ACCENT_PRESETS) {
    const sw = el("button", "swatch");
    sw.type = "button";
    sw.style.background = c;
    sw.title = c;
    sw.dataset.color = c;
    sw.addEventListener("click", () => {
      store.doc.design.accent = c;
      store.touch();
      syncDesignValues();
    });
    swatches.appendChild(sw);
  }
  const picker = el("input", "color-input");
  picker.type = "color";
  picker.id = "accentPicker";
  picker.addEventListener("input", () => {
    store.doc.design.accent = picker.value;
    store.touch();
    syncDesignValues();
  });
  swatches.appendChild(picker);
  colorRow.appendChild(swatches);
  gColor.appendChild(colorRow);
  container.appendChild(gColor);

  /* ---- 日期与照片 ---- */
  const gMisc = el("div", "design-group");
  gMisc.appendChild(el("div", "design-group-title", "日期与照片"));
  const dateRow = el("div", "design-row");
  const dateSeg = el("div", "seg");
  for (const [v, label] of [["right", "日期右对齐"], ["below", "日期在标题下"]]) {
    const b = el("button", design.dateAlign === v ? "active" : "", label);
    b.type = "button";
    b.dataset.dateAlign = v;
    b.addEventListener("click", () => {
      store.doc.design.dateAlign = v;
      store.touch();
      syncDesignValues();
    });
    dateSeg.appendChild(b);
  }
  dateRow.appendChild(dateSeg);
  gMisc.appendChild(dateRow);

  const photoRow = el("label", "check-row");
  photoRow.style.marginTop = "10px";
  const photoCb = el("input");
  photoCb.type = "checkbox";
  photoCb.checked = !!design.showPhoto;
  photoCb.id = "showPhotoCb";
  photoCb.addEventListener("change", () => {
    store.doc.design.showPhoto = photoCb.checked;
    store.touch();
  });
  photoRow.appendChild(photoCb);
  photoRow.appendChild(el("span", null, "显示照片（ATS 场景建议关闭）"));
  gMisc.appendChild(photoRow);
  container.appendChild(gMisc);

  /* ---- 一键压缩 ---- */
  const gCompact = el("div", "design-group");
  gCompact.appendChild(el("div", "design-group-title", "一页压缩"));
  const compactRow = el("label", "check-row");
  const compactCb = el("input");
  compactCb.type = "checkbox";
  compactCb.checked = !!design.compact;
  compactCb.id = "compactCb";
  compactCb.addEventListener("change", () => {
    store.doc.design.compact = compactCb.checked;
    store.touch({ pageInfo: true });
    syncDesignValues();
  });
  compactRow.appendChild(compactCb);
  compactRow.appendChild(el("span", null, "压缩到一页（自动缩小字号 / 行距 / 间距 / 边距）"));
  gCompact.appendChild(compactRow);
  container.appendChild(gCompact);

  syncDesignValues();
}

/** 把 store 中的当前值同步到控件（compact 时显示生效值并禁用滑块）。 */
export function syncDesignValues() {
  const design = store.doc?.design;
  if (!design) return;
  const compact = !!design.compact;
  for (const [key, s] of Object.entries(sliders)) {
    const effective = compact && key in COMPACT_OVERRIDES ? COMPACT_OVERRIDES[key] : design[key];
    s.input.value = effective;
    s.val.textContent = s.format(effective);
    s.row.classList.toggle("design-disabled", compact && key in COMPACT_OVERRIDES);
  }
  document.querySelectorAll("[data-font]").forEach((b) => {
    b.classList.toggle("active", b.dataset.font === design.fontFamily);
  });
  document.querySelectorAll("[data-dateAlign]").forEach((b) => {
    b.classList.toggle("active", b.dataset.dateAlign === design.dateAlign);
  });
  document.querySelectorAll("[data-color]").forEach((b) => {
    b.classList.toggle("active", (b.dataset.color || "").toLowerCase() === (design.accent || "").toLowerCase());
  });
  const picker = document.getElementById("accentPicker");
  if (picker && design.accent) picker.value = design.accent;
  const cb = document.getElementById("showPhotoCb");
  if (cb) cb.checked = !!design.showPhoto;
  const cc = document.getElementById("compactCb");
  if (cc) cc.checked = !!design.compact;
}
