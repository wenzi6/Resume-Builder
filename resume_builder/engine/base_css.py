"""基础样式层：重置、语义标记默认样式、中文排版、打印/分页规则。

所有模板共享；模板 CSS 只做「视觉差异化」覆盖。
分页规则来自 Chromium 分页技术调研（docs/SPEC.md 5.4），是「完美分页」
第一道防线。
"""
from __future__ import annotations


def base_css(page_margin_mm: float) -> str:
    m = f"{page_margin_mm:.1f}mm"
    return f"""
/* ============ 重置 ============ */
*, *::before, *::after {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; background: #fff; }}
img {{ max-width: 100%; display: block; }}
ul, ol {{ margin: 0; padding: 0; }}
h1, h2, h3, h4, p, figure {{ margin: 0; }}

/* ============ 页面容器 ============ */
/* 屏幕：A4 纸张效果（794px @96dpi）；打印：交由 @page 边距控制 */
.r-sheet {{
  width: 794px;
  min-height: 1123px;
  margin: 24px auto;
  padding: {m};
  background: #fff;
  color: var(--r-text);
  font-family: var(--r-font-body);
  font-size: var(--r-fs-body);
  line-height: var(--r-lh);
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}}

/* ============ 中文排版 ============ */
.r-sheet {{
  /* 中西文间距（Python 端已做盘古之白，这里双保险） */
  text-autospace: ideograph-alpha ideograph-numeric ideograph-parenthesis;
  /* 避头尾：点号/括号不居行首 */
  line-break: strict;
  /* 行尾标点悬挂半字宽 */
  hanging-punctuation: allow-end;
  word-break: normal;
  overflow-wrap: break-word;
}}

/* ============ 个人信息 ============ */
.rsec-profile {{ margin-bottom: var(--r-gap); }}
.r-profile {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }}
.r-profile-text {{ flex: 1 1 auto; min-width: 0; }}
.r-name {{
  font-family: var(--r-font-head);
  font-size: var(--r-fs-name);
  font-weight: 700;
  line-height: 1.15;
  letter-spacing: 0.02em;
  color: var(--r-text);
}}
.r-role {{
  font-size: var(--r-fs-h3);
  font-weight: 500;
  color: var(--r-accent);
  margin-top: 2px;
}}
.r-contacts {{
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  margin-top: 6px;
  font-size: var(--r-fs-small);
  color: var(--r-text-soft);
}}
.r-contact {{ display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; }}
.r-ico {{ display: inline-flex; width: 1em; height: 1em; flex: none; }}
.r-ico svg {{ width: 100%; height: 100%; }}
.r-summary {{
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid var(--r-line);
  color: var(--r-text-soft);
  text-align: justify;
}}
.r-summary p + p {{ margin-top: 4px; }}
.r-photo {{
  flex: none;
  width: 88px; height: 112px;
  border-radius: 3px;
  overflow: hidden;
  background: var(--r-line-soft);
}}
.r-photo img {{ width: 100%; height: 100%; object-fit: cover; }}

/* ============ 区块 ============ */
.rsec {{ margin-bottom: var(--r-gap); }}
.rsec:last-child {{ margin-bottom: 0; }}
.rsec-title {{
  font-family: var(--r-font-head);
  font-size: var(--r-fs-h2);
  font-weight: 700;
  line-height: var(--r-lh-tight);
  color: var(--r-text);
  margin-bottom: 8px;
  padding-left: 9px;
  border-left: 3px solid var(--r-accent);
}}
.rsec-body {{ display: block; }}

/* ============ 条目 ============ */
.ritem {{ margin-bottom: var(--r-item-gap); }}
.ritem:last-child {{ margin-bottom: 0; }}
.ritem-head {{
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}}
.ritem-heading {{ display: flex; align-items: baseline; flex-wrap: wrap; gap: 2px 8px; min-width: 0; }}
.ritem-title {{ font-weight: 600; font-size: var(--r-fs-h3); color: var(--r-text); }}
.ritem-sub {{ color: var(--r-accent); font-weight: 500; }}
.ritem-date {{
  flex: none;
  font-size: var(--r-fs-small);
  color: var(--r-text-mute);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}}
/* 日期对齐方式：below 时独占一行 */
.resume-date-below .ritem-head {{ flex-wrap: wrap; }}
.resume-date-below .ritem-date {{
  flex-basis: 100%;
  text-align: left;
  order: 3;
  margin-top: 1px;
}}

/* ============ 列表 ============ */
.rlist {{ list-style: none; margin-top: 3px; }}
.rlist li {{
  position: relative;
  padding-left: 12px;
  color: var(--r-text-soft);
}}
.rlist li::before {{
  content: "";
  position: absolute;
  left: 2px;
  top: 0.62em;
  width: 4px; height: 4px;
  border-radius: 50%;
  background: var(--r-accent);
}}
.rlist li + li {{ margin-top: 2px; }}
.rlist-plain li::before {{ background: var(--r-text-mute); }}

/* 键值行（自定义区块的附加字段） */
.rkv {{ color: var(--r-text-soft); margin-top: 2px; }}
.rkv-k {{ font-weight: 600; color: var(--r-text); }}

/* ============ 技能 ============ */
.rskills {{ display: block; }}
.rskills-cols {{
  column-count: 2;
  column-gap: 4px 18px;
}}
.rskills-cols .rskill {{ break-inside: avoid; }}
.rskill {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 2px 0;
}}
.rskill-name {{ font-weight: 500; color: var(--r-text); }}
.rrate {{ display: inline-flex; gap: 3px; flex: none; }}
.rrate i {{
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--r-line);
}}
.rrate i.on {{ background: var(--r-accent); }}
.rtag-row {{ display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }}
.rtag {{
  font-size: var(--r-fs-small);
  color: var(--r-text-soft);
  background: var(--r-accent-soft);
  border: 1px solid var(--r-accent-line);
  border-radius: 3px;
  padding: 1px 7px;
  line-height: 1.5;
}}

/* ============ 手动分页锚点 ============ */
.r-pagebreak {{ break-before: page; page-break-before: always; height: 0; }}
.r-pagebreak:last-child {{ break-before: auto; page-break-before: auto; }}

/* ============ 双栏容器 ============ */
.r-cols {{ display: flex; align-items: flex-start; gap: var(--r-col-gap, 20px); }}
.r-sidebar {{ flex: none; width: var(--r-col-sidebar, 34%); }}
.r-main {{ flex: 1 1 auto; min-width: 0; }}

/* ============ 打印 / 分页（第一道防线） ============ */
@media print {{
  html, body {{ background: #fff; }}
  * {{
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }}
  .r-sheet {{
    width: auto !important;
    min-height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    box-shadow: none !important;
    border-radius: 0 !important;
    border: none !important;
  }}
  /* 区块尽量整体不拆分（Chromium 对超高一页的元素会尽力拆分） */
  .rsec {{ break-inside: avoid; page-break-inside: avoid; }}
  /* 标题不与正文分离 */
  .rsec-title {{ break-after: avoid-page; page-break-after: avoid; }}
  /* 条目不拆分 */
  .ritem {{ break-inside: avoid; page-break-inside: avoid; }}
  .r-profile, .rskill, .ritem-head {{ break-inside: avoid; page-break-inside: avoid; }}
  /* 孤行寡行 */
  p, li, .rkv {{ orphans: 3; widows: 3; }}
  /* 手动分页 */
  .r-pagebreak {{ break-before: page; page-break-before: always; }}
  /* 末元素分页防空白页 */
  .r-pagebreak:last-child {{ break-before: auto; page-break-before: auto; }}
  /* 分页点前的底部间距清零，避免页底留白 */
  .r-pagebreak + .rsec {{ margin-top: 0 !important; }}
  .rsec:has(+ .r-pagebreak) {{ margin-bottom: 0 !important; }}
  /* 最后一节不额外留白 */
  .rsec:last-child {{ margin-bottom: 0 !important; }}
  /* 双栏在打印时保持，但不允许栏内溢出 */
  .r-cols {{ gap: 16px; }}
}}
"""
