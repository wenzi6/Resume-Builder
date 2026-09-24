"""PDF 渲染与分页测量（子进程封装）。"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from ..config import BASE_DIR, OUTPUT_DIR, PDF_TIMEOUT

WORKER = BASE_DIR / "pdf_worker.py"
RENDER_DIR = OUTPUT_DIR / ".render"


def _ensure_render_dir() -> Path:
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    return RENDER_DIR


def sweep_stale_renders(max_age_s: int = 3600) -> int:
    """清理渲染临时目录中的过期文件（进程被 kill 时的残留）。"""
    import time

    if not RENDER_DIR.exists():
        return 0
    now = time.time()
    removed = 0
    for p in RENDER_DIR.iterdir():
        try:
            if p.is_file() and now - p.stat().st_mtime > max_age_s:
                p.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def _write_html(html: str) -> Path:
    d = _ensure_render_dir()
    path = d / f"render_{uuid.uuid4().hex}.html"
    path.write_text(html, encoding="utf-8")
    return path


def _run_worker(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(WORKER), *args],
        capture_output=True,
        text=True,
        timeout=PDF_TIMEOUT,
        cwd=str(BASE_DIR),
    )


def measure_pages(doc: dict[str, Any]) -> dict[str, Any]:
    """测量简历页数与各区块落位，返回分页信息。"""
    from .renderer import render_for_pdf

    html_path = _write_html(render_for_pdf(doc))
    try:
        result = _run_worker(["measure", str(html_path)])
        if result.returncode != 0:
            msg = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(msg or "分页测量失败")
        # worker 最后一行是 JSON
        lines = [ln for ln in result.stdout.strip().splitlines() if ln.strip()]
        return json.loads(lines[-1])
    finally:
        html_path.unlink(missing_ok=True)


def render_pdf_bytes(doc: dict[str, Any]) -> bytes:
    """渲染简历为 PDF 字节流。"""
    from .renderer import render_for_pdf

    d = _ensure_render_dir()
    html_path = _write_html(render_for_pdf(doc))
    pdf_path = d / f"resume_{uuid.uuid4().hex}.pdf"
    try:
        result = _run_worker(["pdf", str(html_path), str(pdf_path)])
        if result.returncode != 0 or not pdf_path.exists():
            msg = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(msg or "PDF 渲染失败")
        data = pdf_path.read_bytes()
        if not data.startswith(b"%PDF"):
            raise RuntimeError("PDF 输出无效")
        return data
    finally:
        html_path.unlink(missing_ok=True)
        pdf_path.unlink(missing_ok=True)


def render_pdf_to_file(doc: dict[str, Any], out_path: str | Path) -> Path:
    data = render_pdf_bytes(doc)
    out = Path(out_path)
    out.write_bytes(data)
    return out


def verify_pdf_fonts(pdf_bytes: bytes) -> dict[str, Any]:
    """校验 PDF 中的中文字体是否为 Type0 子集（而非 Type3 降级）。

    可变字体 / CFF webfont 被 Chromium 降级为 Type3 时文本不可检索，这是字体回归测试的核心。
    注意：Type3 字体的 basefont 可能是空字符串，不能按名字过滤（曾因过滤导致永远 ok=True）。
    """
    import re

    import pymupdf

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    fonts: set[str] = set()
    types: dict[str, str] = {}
    for page in doc:
        for f in page.get_fonts(full=True):
            # f = (xref, ext, type, basefont, name, encoding, ...)
            ftype = f[2] if len(f) > 2 else ""
            basefont = (f[3] if len(f) > 3 else "") or "(unnamed)"
            fonts.add(basefont)
            types[basefont] = ftype
    text = "".join(page.get_text() for page in doc)
    doc.close()
    type3 = [k for k, v in types.items() if "Type3" in v]
    # 文本层必须能提取出中文（乱码 / Type3 降级时提取不出真正的汉字）
    text_ok = bool(text.strip()) and bool(re.search(r"[\u4e00-\u9fff]", text))
    return {
        "fonts": sorted(fonts),
        "types": types,
        "type3": type3,
        "textExtractable": bool(text.strip()),
        "textSample": text[:120],
        "ok": not type3 and text_ok,
    }
