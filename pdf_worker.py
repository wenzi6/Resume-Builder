"""PDF 渲染 / 分页测量子进程。

两种用法：
1) 常驻服务模式（默认，由 engine/pdf.py 的进程池管理）：
       python pdf_worker.py serve
   stdin/stdout 走 JSON 行协议，Chromium 全程只启动一次，请求间复用。
2) 单次 CLI 模式（调试 / 兜底）：
       python pdf_worker.py measure <html_path>
       python pdf_worker.py pdf     <html_path> <pdf_path> [breaks_json]

在干净进程中运行 Playwright，避免与 Flask 请求线程的事件循环 / greenlet 冲突。
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
  const effBreakTops = [];
  for (const bt of breakTops) {
    const eb = bt + _shift;
    effBreakTops.push(eb);
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
      effTop: Math.round(et),
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
           contentHeight: Math.round(totalH), suggestedBreaks: suggested,
           breaks: breakTops.map((t, i) => ({ top: Math.round(t), effTop: Math.round(effBreakTops[i]) })) };
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


def _measure_with(browser, html_path: str) -> dict:
    """在给定 browser 上执行分页测量（每次请求独立 page，避免状态残留）。"""
    page = browser.new_page()
    try:
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
        return result
    finally:
        page.close()


def _pdf_with(browser, html_path: str, pdf_path: str, breaks: list | None = None) -> str:
    """在给定 browser 上渲染 PDF。"""
    page = browser.new_page()
    try:
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
        return pdf_path
    finally:
        page.close()


def run_measure(html_path: str) -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            print(json.dumps(_measure_with(browser, html_path), ensure_ascii=False))
        finally:
            browser.close()
    return 0


def run_pdf(html_path: str, pdf_path: str, breaks: list | None = None) -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            _pdf_with(browser, html_path, pdf_path, breaks)
        finally:
            browser.close()
    return 0


# ---------------------------------------------------------------- 常驻服务模式
#
# JSON 行协议（stdin/stdout，一行一个请求/响应）：
#   -> {"id": 1, "mode": "measure", "html_path": "..."}
#   <- {"id": 1, "ok": true, "result": {...}}
#   -> {"id": 2, "mode": "pdf", "html_path": "...", "pdf_path": "...", "breaks": [...]}
#   <- {"id": 2, "ok": true, "pdf_path": "..."}
#   -> {"mode": "exit"}
# 启动后先输出 {"ready": true}。Chromium 全程只启动一次，请求间复用。


def _reply(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def serve() -> int:
    from playwright.sync_api import sync_playwright

    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
    except Exception as e:  # noqa: BLE001
        _reply({"ready": False, "error": f"Chromium 启动失败：{e}"})
        return 1
    _reply({"ready": True})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        if req.get("mode") == "exit":
            break
        rid = req.get("id")
        try:
            if req.get("mode") == "measure":
                _reply({"id": rid, "ok": True, "result": _measure_with(browser, req["html_path"])})
            elif req.get("mode") == "pdf":
                _pdf_with(browser, req["html_path"], req["pdf_path"], req.get("breaks"))
                _reply({"id": rid, "ok": True, "pdf_path": req["pdf_path"]})
            else:
                _reply({"id": rid, "ok": False, "error": f"unknown mode: {req.get('mode')}"})
        except Exception as e:  # noqa: BLE001 单请求失败不影响常驻进程
            _reply({"id": rid, "ok": False, "error": str(e)})

    try:
        browser.close()
        pw.stop()
    except Exception:  # noqa: BLE001
        pass
    return 0


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "serve":
        return serve()
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
