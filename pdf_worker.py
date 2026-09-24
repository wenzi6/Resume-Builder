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
  const rectOf = (el) => {
    const r = el.getBoundingClientRect();
    return { top: r.top + window.scrollY - sheetTop, h: r.height };
  };

  // ---- 收集不可分割原子（模拟 Chromium 分页）----
  // 规则与 engine/base_css.py 的打印规则一一对应：
  //   · 高度 ≤ 一页的 .rsec 是单原子（break-inside:avoid → 放不下就整块挪到下页）
  //   · 超过一页的 .rsec 由引擎拆分：标题+首条目 绑定，其余逐条目
  //   · .r-pagebreak 是强制换页伪原子
  const atoms = [];
  const addAtom = (top, h, key, pushFirst = false, el = null) => {
    if (h > 0.5) atoms.push({ top, h, key, pushFirst, el });
  };
  const naturalH = new Map();   // key -> 区块自然高度（含内部间隙）

  for (const sec of sheet.querySelectorAll('.rsec')) {
    const key = sec.getAttribute('data-section') || '';
    const r = rectOf(sec);
    if (r.h <= pageH) {
      addAtom(r.top, r.h, key, false, sec);
      naturalH.set(key, r.h);
      continue;
    }
    // 超过一页的区块：Chromium 对 break-inside:avoid 的处理是「先挪到下一页
    // 再拆分」——首原子打上 pushFirst 标记，模拟时先浪费当前页剩余空间。
    const title = sec.querySelector('.rsec-title');
    const body = sec.querySelector('.rsec-body') || sec;
    const kids = [...body.querySelectorAll(
      ':scope > .ritem, :scope > .rskills > .rskill, :scope > .rkv, :scope > .rtag-row, :scope > .rlist > li, :scope > p')];
    if (!kids.length) {
      addAtom(r.top, r.h, key, true, sec);
      naturalH.set(key, r.h);
      continue;
    }
    const fr = rectOf(kids[0]);
    if (title) {
      const tr = rectOf(title);
      addAtom(tr.top, fr.top + fr.h - tr.top, key, true, sec);   // 标题与首条目不分离
    } else {
      addAtom(fr.top, fr.h, key, true, sec);
    }
    for (let i = 1; i < kids.length; i++) {
      const kr = rectOf(kids[i]);
      addAtom(kr.top, kr.h, key, false, kids[i]);
    }
    naturalH.set(key, r.h);
  }

  const breakEls = [...sheet.querySelectorAll('.r-pagebreak')];

  // ---- 分 flow 模拟 ----
  // 多栏模板（如 modern 的 sidebar/main）各栏是独立竖向流：分别模拟，
  // 页数取各流最大值；手动分页点只影响它所在栏的流。
  const colOf = (el) => (el && el.closest ? el.closest('.r-sidebar, .r-main') : null);
  const flows = new Map();
  const fullFlow = { atoms: [], breaks: [] };
  flows.set('full', fullFlow);
  for (const a of atoms) {
    const col = colOf(a.el);
    if (!col) { fullFlow.atoms.push(a); continue; }
    if (!flows.has(col)) flows.set(col, { atoms: [], breaks: [] });
    flows.get(col).atoms.push(a);
  }
  for (const b of breakEls) {
    const col = colOf(b);
    const flow = col ? (flows.get(col) || fullFlow) : fullFlow;
    flow.breaks.push(b);
  }

  let pages = 1;
  const atomResult = new Map();   // atom -> {startPage, endPage, effTop, posInPage}
  const breakEff = [];

  for (const flow of flows.values()) {
    const events = [
      ...flow.atoms.map(a => ({ type: 'atom', top: a.top, h: a.h, key: a.key, pushFirst: a.pushFirst, ref: a })),
      ...flow.breaks.map(b => ({ type: 'break', top: rectOf(b).top, ref: b })),
      // .r-pagebreak 与紧随的区块顶部坐标相同，必须让分页点先处理，
      // 否则区块会被放进去之后才换页（手动分页失效）
    ].sort((a, b) => a.top - b.top || (a.type === 'break' ? -1 : 1));

    let shift = 0;
    for (const ev of events) {
      const posInPage = () => {
        const ep = ev.top + shift;
        return ep - Math.floor(ep / pageH) * pageH;
      };
      if (ev.type === 'break') {
        const p = posInPage();
        if (p > 0.5) shift += pageH - p;   // 强制换页：浪费当前页剩余空间
        breakEff.push({ top: Math.round(ev.top), effTop: Math.round(ev.top + shift) });
        continue;
      }
      let p = posInPage();
      // 超高一页区块的首原子：Chromium 先把它挪到页首再拆分
      if (ev.pushFirst && p > 0.5) {
        shift += pageH - p;
        p = 0;
      } else if (ev.h <= pageH && p + ev.h > pageH + 0.5) {
        shift += pageH - p;                 // 整块挪到下页
        p = 0;
      }
      const ep = ev.top + shift;
      const start = Math.floor(ep / pageH);
      const end = Math.floor((ep + ev.h - 1) / pageH);
      atomResult.set(ev.ref, {
        startPage: start + 1, endPage: end + 1,
        effTop: Math.round(ep), posInPage: Math.round(p),
      });
      if (end + 1 > pages) pages = end + 1;
    }
  }
  breakEff.sort((a, b) => a.top - b.top);

  // ---- 汇总到区块级 ----
  const byKey = new Map();
  for (const a of atoms) {
    const res = atomResult.get(a);
    if (!res) continue;
    const cur = byKey.get(a.key);
    if (!cur) {
      byKey.set(a.key, {
        key: a.key, top: Math.round(a.top),
        height: Math.round(naturalH.get(a.key) ?? a.h),
        effTop: res.effTop, startPage: res.startPage, endPage: res.endPage,
        firstPosInPage: res.posInPage,
      });
    } else {
      cur.startPage = Math.min(cur.startPage, res.startPage);
      cur.endPage = Math.max(cur.endPage, res.endPage);
    }
  }
  const sections = [...byKey.values()].map(s => ({
    ...s,
    straddles: s.startPage !== s.endPage,
    tallerThanPage: false,   // 由 Python 侧按 height > pageH 判定
  }));

  // 内容总高（多流取所有原子的最深位置）
  let maxBottom = 0;
  for (const a of atoms) {
    const res = atomResult.get(a);
    if (res) maxBottom = Math.max(maxBottom, res.effTop + a.h);
  }
  const totalH = Math.max(maxBottom, sheet.scrollHeight);
  const pageCount = Math.max(1, pages);

  // 建议分页点：区块起始落在页面底部 12% 以内、且自身不超过一页
  const suggested = [];
  for (const s of sections) {
    if (s.height > pageH || s.straddles) continue;
    if (s.effTop % pageH > pageH * 0.88) suggested.push(s.key);
  }
  return { pageCount, pageHeightPx: Math.round(pageH), sections,
           contentHeight: Math.round(totalH), suggestedBreaks: suggested,
           breaks: breakEff };
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


_READ_MARGIN_JS = r"""
() => {
  for (const rule of document.styleSheets) {
    let rules;
    try { rules = rule.cssRules; } catch (e) { continue; }
    for (const r of rules) {
      const isPage = (r.constructor && r.constructor.name === 'CSSPageRule') || r.type === 6;
      if (!isPage) continue;
      const m = r.style.marginTop || r.style.margin;
      if (m && String(m).endsWith('mm')) return parseFloat(m);
    }
  }
  return 20;
}
"""


def _measure_js_with(browser, html_path: str) -> dict:
    """JS 原子模拟测量（不渲染 PDF）。返回含 sections/pageCount(估算) 的结果。"""
    page = browser.new_page()
    try:
        page.goto(Path(html_path).absolute().as_uri())
        page.emulate_media(media="print")
        _wait_fonts(page)
        # print 媒体下 .r-sheet 是 width:auto，会按视口宽度布局——必须把视口
        # 设为 A4 内容宽度，否则换行与真实打印不符。
        margin_mm = page.evaluate(_READ_MARGIN_JS)
        content_w = max(320, round((210 - margin_mm * 2) * 96 / 25.4))
        page.set_viewport_size({"width": content_w, "height": 1200})
        _wait_fonts(page)
        return page.evaluate(MEASURE_JS)
    finally:
        page.close()


def _finalize_measure(result: dict) -> dict:
    """补 warnings / tallerThanPage（Python 侧判定）。"""
    page_h = result.get("pageHeightPx") or 0
    for s in result.get("sections", []):
        s["tallerThanPage"] = bool(page_h) and s.get("height", 0) > page_h
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


def _pageinfo_with(browser, html_path: str, pdf_path: str) -> dict:
    """一次页面加载同时做：JS 分页测量 + 实际 PDF 渲染。

    页数以 PDF 实际渲染为准（ground truth，保证与导出永远一致）；
    JS 模拟提供各区块落位，供分页覆盖层使用。
    """
    page = browser.new_page()
    try:
        page.goto(Path(html_path).absolute().as_uri())
        page.emulate_media(media="print")
        _wait_fonts(page)
        margin_mm = page.evaluate(_READ_MARGIN_JS)
        content_w = max(320, round((210 - margin_mm * 2) * 96 / 25.4))
        page.set_viewport_size({"width": content_w, "height": 1200})
        _wait_fonts(page)

        result = page.evaluate(MEASURE_JS)
        page.pdf(
            path=pdf_path,
            format="A4",
            print_background=True,
            prefer_css_page_size=True,
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
        )
        result = _finalize_measure(result)
        result["estimatedPages"] = result.get("pageCount")
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
            # ensure_ascii=True：防父进程本地编码解码失败（见 _reply 注释）
            print(json.dumps(_finalize_measure(_measure_js_with(browser, html_path))))
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
    # ensure_ascii=True：父进程可能用本地编码（Windows GBK）读 stdout，
    # 含中文的非 ASCII 输出会 UnicodeDecodeError 导致读取线程崩溃
    sys.stdout.write(json.dumps(obj) + "\n")
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
            if req.get("mode") == "pageinfo":
                # 分页信息：JS 测量 + 实际 PDF（页数 ground truth）
                result = _pageinfo_with(browser, req["html_path"], req["pdf_path"])
                _reply({"id": rid, "ok": True, "result": result, "pdf_path": req["pdf_path"]})
            elif req.get("mode") == "measure":
                _reply({"id": rid, "ok": True, "result": _finalize_measure(_measure_js_with(browser, req["html_path"]))})
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
