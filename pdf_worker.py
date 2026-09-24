"""PDF 渲染 / 分页测量子进程。

由后端通过 subprocess 调用，在干净进程中运行 Playwright，避免与 Flask
请求线程的事件循环 / greenlet 冲突。

用法：
    python pdf_worker.py pdf     <html_path> <pdf_path> [breaks_json]
    python pdf_worker.py measure <html_path>

measure 输出 JSON 到 stdout：
    { "pageCount": 2, "pageHeightPx": 991, "sections": [...],
      "warnings": [...], "suggestedBreaks": [...] }
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# A4 @ 96dpi
A4_HEIGHT_MM = 297.0
PX_PER_MM = 96.0 / 25.4

MEASURE_JS = r"""
() => {
  const sheet = document.querySelector('.r-sheet') || document.body;
  const mm = 96 / 25.4;
  // 从 @page 规则读取边距；读不到则退回 20mm
  let marginMm = 20;
  for (const rule of document.styleSheets) {
    let rules;
    try { rules = rule.cssRules; } catch (e) { continue; }
    for (const r of rules) {
      const isPage = (r.constructor && r.constructor.name === 'CSSPageRule') || r.type === 6;
      if (!isPage) continue;
      const m = r.style.marginTop || r.style.margin;
      if (m && String(m).endsWith('mm')) marginMm = parseFloat(m);
    }
  }
  const pageH = (297 - marginMm * 2) * mm;
  const sheetTop = sheet.getBoundingClientRect().top + window.scrollY;

  // 手动分页点（.r-pagebreak 高度为 0，但会使其后内容从新页开始）。
  // 用「累计页尾浪费」模型把自然坐标换算为打印有效坐标。
  const breakTops = [...sheet.querySelectorAll('.r-pagebreak')]
    .map(el => el.getBoundingClientRect().top + window.scrollY - sheetTop)
    .sort((a, b) => a - b);
  const effTop = (top) => {
    let shift = 0;
    for (const bt of breakTops) {
      const eb = bt + shift;
      if (eb > top) break;
      shift += pageH - (eb % pageH);
    }
    return top + shift;
  };
  let _shift = 0;
  for (const bt of breakTops) {
    const eb = bt + _shift;
    _shift += pageH - (eb % pageH);
  }

  const sections = [];
  for (const el of sheet.querySelectorAll('.rsec')) {
    const rect = el.getBoundingClientRect();
    const top = rect.top + window.scrollY - sheetTop;
    const h = rect.height;
    if (h < 1) continue;
    const et = effTop(top);
    const startPage = Math.floor(et / pageH);
    const endPage = Math.floor((et + h - 1) / pageH);
    sections.push({
      key: el.getAttribute('data-section') || '',
      top: Math.round(top),
      height: Math.round(h),
      startPage: startPage + 1,
      endPage: endPage + 1,
      straddles: startPage !== endPage,
      tallerThanPage: h > pageH,
    });
  }
  const totalH = sheet.scrollHeight + _shift;
  const pageCount = Math.max(1, Math.ceil((totalH - 0.5) / pageH));

  // 建议分页点：起始位置落在页面底部 12% 以内、且自身不太高的区块
  const suggested = [];
  for (const s of sections) {
    if (s.tallerThanPage || s.straddles) continue;
    const posInPage = effTop(s.top) % pageH;
    if (posInPage > pageH * 0.88) suggested.push(s.key);
  }
  return { pageCount, pageHeightPx: Math.round(pageH), sections,
           contentHeight: Math.round(totalH), suggestedBreaks: suggested };
}
"""


def _wait_fonts(page, timeout_ms: int = 8000) -> None:
    try:
        page.wait_for_function(
            "() => document.fonts && document.fonts.status === 'loaded'",
            timeout=timeout_ms,
        )
    except Exception:
        pass  # 字体加载失败不阻塞渲染，CSS 会回退系统字体


def run_measure(html_path: str) -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(Path(html_path).absolute().as_uri())
            page.emulate_media(media="print")
            _wait_fonts(page)
            result = page.evaluate(MEASURE_JS)

            warnings = []
            for s in result.get("sections", []):
                if s.get("tallerThanPage"):
                    warnings.append(f"区块「{s['key']}」高度超过一页，将被拆分")
            if result.get("pageCount", 1) > 1:
                used = result.get("contentHeight", 0) - result.get("pageHeightPx", 0) * (result["pageCount"] - 1)
                if 0 < used < result.get("pageHeightPx", 0) * 0.25:
                    warnings.append("最后一页内容很少，可开启「压缩到一页」或删减内容")
            result["warnings"] = warnings
            print(json.dumps(result, ensure_ascii=False))
        finally:
            browser.close()
    return 0


def run_pdf(html_path: str, pdf_path: str, breaks: list | None = None) -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(Path(html_path).absolute().as_uri())
            page.emulate_media(media="print")
            _wait_fonts(page)

            if breaks:
                page.evaluate(
                    """(keys) => {
                        const sheet = document.querySelector('.r-sheet') || document.body;
                        for (const key of keys) {
                            const el = sheet.querySelector('.rsec[data-section="' + key + '"]');
                            if (!el) continue;
                            const prev = el.previousElementSibling;
                            if (prev && prev.classList.contains('r-pagebreak')) continue;
                            const div = document.createElement('div');
                            div.className = 'r-pagebreak';
                            div.setAttribute('data-before', key);
                            el.parentNode.insertBefore(div, el);
                        }
                    }""",
                    breaks,
                )

            page.pdf(
                path=pdf_path,
                format="A4",
                print_background=True,
                prefer_css_page_size=True,
                margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
            )
        finally:
            browser.close()
    return 0


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    mode = sys.argv[1]
    if mode == "measure":
        return run_measure(sys.argv[2])
    if mode == "pdf":
        if len(sys.argv) < 4:
            print("usage: pdf_worker.py pdf <html> <pdf> [breaks_json]", file=sys.stderr)
            return 2
        breaks = json.loads(sys.argv[4]) if len(sys.argv) > 4 else None
        if breaks is not None and not isinstance(breaks, list):
            breaks = None
        return run_pdf(sys.argv[2], sys.argv[3], breaks)
    print(f"unknown mode: {mode}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"pdf_worker error: {e}", file=sys.stderr)
        sys.exit(1)
