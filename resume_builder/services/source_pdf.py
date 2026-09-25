"""对照导入的原始 PDF 页面渲染（服务端栅格化，全环境可靠）。

无头 Chromium 的 PDF 插件渲染不稳定，浏览器间也有差异；把 PDF 页面用
pymupdf 渲染成 PNG 后展示，保证「原格式」在任何环境下都一致可见。
同时保留原生查看器入口（/data/ 路由直接发 PDF）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import config


# 渲染倍率：2 ≈ 144dpi，A4 约 1191×1684px，清晰度与体积的平衡点
RENDER_DPI = 2


def _data_dir() -> Path:
    """运行时读取（测试会把它指向临时目录）。"""
    return config.DATA_DIR


def _pages_dir(stem: str) -> Path:
    d = _data_dir() / "imports" / "pages" / stem
    d.mkdir(parents=True, exist_ok=True)
    return d


def render_pages(rel_path: str, dpi: float = RENDER_DPI) -> list[dict[str, Any]]:
    """把原始 PDF 渲染为逐页 PNG（带缓存），返回 [{page, url, width, height}]。"""
    import pymupdf

    src = _data_dir() / rel_path
    if not src.is_file():
        return []
    stem = src.stem
    out_dir = _pages_dir(stem)
    result: list[dict[str, Any]] = []

    with pymupdf.open(str(src)) as pdf:
        for i, page in enumerate(pdf, 1):
            png = out_dir / f"page-{i}.png"
            if not png.exists():
                pix = page.get_pixmap(dpi=int(dpi * 72))
                pix.save(str(png))
            result.append({
                "page": i,
                "url": f"/data/imports/pages/{stem}/page-{i}.png",
                "width": round(page.rect.width),
                "height": round(page.rect.height),
            })
    return result


def render_live_pages(pdf_bytes: bytes, dpi: float = RENDER_DPI) -> tuple[list[dict[str, Any]], str]:
    """把打过补丁的 PDF 字节流渲染为逐页 PNG。

    按内容哈希缓存目录（data/imports/pages/live/<hash>/），内容没变时
    复用已有 PNG，编辑后只重渲染变化的那一版。返回 (pages, hash)。
    """
    import hashlib

    import pymupdf

    digest = hashlib.sha1(pdf_bytes).hexdigest()[:16]
    out_dir = _pages_dir(f"live/{digest}")
    result: list[dict[str, Any]] = []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
        for i, page in enumerate(pdf, 1):
            png = out_dir / f"page-{i}.png"
            if not png.exists():
                pix = page.get_pixmap(dpi=int(dpi * 72))
                pix.save(str(png))
            result.append({
                "page": i,
                "url": f"/data/imports/pages/live/{digest}/page-{i}.png",
                "width": round(page.rect.width),
                "height": round(page.rect.height),
            })
    return result, digest


def sweep_live_pages(keep: int = 12) -> int:
    """清理过期的实时预览缓存（按目录 mtime，保留最近 keep 份）。"""
    import shutil

    base = _pages_dir("live")
    if not base.is_dir():
        return 0
    dirs = sorted((d for d in base.iterdir() if d.is_dir()),
                  key=lambda d: d.stat().st_mtime, reverse=True)
    removed = 0
    for d in dirs[keep:]:
        shutil.rmtree(d, ignore_errors=True)
        removed += 1
    return removed


def delete_pages(rel_path: str) -> None:
    """删除某份 PDF 的页面缓存（文档删除时调用）。"""
    import shutil

    stem = Path(rel_path).stem
    d = _data_dir() / "imports" / "pages" / stem
    shutil.rmtree(d, ignore_errors=True)
