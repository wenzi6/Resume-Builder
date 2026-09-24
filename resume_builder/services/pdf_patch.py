"""原格式 PDF 导出：把模块编辑「打补丁」到原始 PDF 上。

设计目标（对照导入的闭环）：用户导入 PDF → 原格式保留 → 在旁边模块里改内容
→ 导出时**仍是原来的版式**，只有改动的文字被替换掉，未改动部分字节级不变。

实现：PyMuPDF 文本Span级替换——定位旧值所在 Span →  redact 该区域 →
按原字体字号颜色插回新文本（超宽自动缩字号）。删除了的内容只 redact 不插入。
无法定位的改动进入 warnings，由前端明确告知用户。
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from .. import config

# 与 services/pdf_import.norm_text 保持一致的轻量归一（保证能找到 Span）
_VARIANT_MAP = {
    "戶": "户", "戸": "户", "兒": "儿", "裏": "里", "喫": "吃", "傘": "伞",
    "畫": "画", "與": "与", "閱": "阅", "敵": "敌", "響": "响", "願": "愿",
    "顧": "顾", "體": "体", "實": "实", "寶": "宝", "術": "术", "網": "网",
    "統": "统", "錯": "错", "門": "门", "問": "问", "隊": "队", "際": "际",
    "驗": "验", "戰": "战", "稱": "称", "種": "种", "節": "节", "風": "风",
    "讀": "读", "變": "变", "萬": "万", "衆": "众",
}

# 字号缩放下限（pt），低于此值认为放不下，进 warnings
MIN_FONT_SIZE = 5.0


def _norm(s: str) -> str:
    if not isinstance(s, str):
        return ""
    out = unicodedata.normalize("NFKC", s)
    for frm, to in _VARIANT_MAP.items():
        if frm in out:
            out = out.replace(frm, to)
    return re.sub(r"\s+", "", out)


# ---------------------------------------------------------------- content 展平


def flatten_content(content: Any) -> dict[str, str]:
    """把 content 展平为 {路径: 字符串值}（列表带序号）。"""
    out: dict[str, str] = {}

    def walk(v: Any, path: str) -> None:
        if isinstance(v, str):
            if v.strip():
                out[path] = v
        elif isinstance(v, list):
            for i, item in enumerate(v):
                walk(item, f"{path}.{i}")
        elif isinstance(v, dict):
            for k, item in v.items():
                if k in ("rating",):  # 数值型不参与文本替换
                    continue
                walk(item, f"{path}.{k}" if path else k)

    walk(content if isinstance(content, dict) else {}, "")
    return out


def diff_content(old_content: Any, new_content: Any) -> list[dict[str, Any]]:
    """逐路径比较，返回 [{path, old, new}]；new=None 表示该内容被删除。"""
    old_map = flatten_content(old_content)
    new_map = flatten_content(new_content)
    changes: list[dict[str, Any]] = []
    for path, old_val in old_map.items():
        new_val = new_map.get(path)
        if new_val is None:
            changes.append({"path": path, "old": old_val, "new": None})
        elif new_val != old_val:
            changes.append({"path": path, "old": old_val, "new": new_val})
    for path in new_map:
        if path not in old_map:
            changes.append({"path": path, "old": None, "new": new_map[path]})
    return changes


# ---------------------------------------------------------------- PDF 补丁


def _page_spans(page) -> list[dict[str, Any]]:
    """收集页面全部文本 Span（含几何与样式信息）。"""
    spans: list[dict[str, Any]] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span.get("text", "").strip():
                    spans.append(span)
    return spans


def _span_baseline(span) -> tuple[float, float]:
    origin = span.get("origin")
    if origin and len(origin) == 2:
        return float(origin[0]), float(origin[1])
    bbox = span["bbox"]
    return float(bbox[0]), float(bbox[3]) - float(bbox[3] - bbox[1]) * 0.22


def _fit_size(text: str, fontname: str, size: float, avail_w: float) -> float:
    import fitz

    if avail_w <= 0:
        return size
    w = fitz.get_text_length(text, fontname=fontname, fontsize=size)
    if w <= avail_w or w <= 0:
        return size
    return max(MIN_FONT_SIZE, size * avail_w / w)


def _insert_text(page, point, text, size, fontname, color, bold: bool) -> None:
    page.insert_text(point, text, fontsize=size, fontname=fontname, color=color)
    if bold:
        page.insert_text((point[0] + size * 0.03, point[1]), text,
                         fontsize=size, fontname=fontname, color=color)


def patch_pdf(source_rel: str, old_content: Any, new_content: Any) -> dict[str, Any]:
    """把 new_content 相对 old_content 的改动应用到原始 PDF。

    返回 {data, applied:[{path}], failed:[{path, reason}], unchanged: bool}
    """
    import fitz

    src = config.DATA_DIR / source_rel
    if not src.is_file():
        raise FileNotFoundError(f"原始 PDF 不存在：{source_rel}")

    changes = diff_content(old_content, new_content)
    original = src.read_bytes()
    if not changes:
        return {"data": original, "applied": [], "failed": [], "unchanged": True}

    doc = fitz.open(stream=original, filetype="pdf")
    applied: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for ch in changes:
        old_val, new_val, path = ch["old"], ch["new"], ch["path"]
        if old_val is None:
            failed.append({"path": path, "reason": "新增内容无法在原始版式中定位"})
            continue

        target = _norm(old_val)
        if not target:
            continue
        hit = False
        for page in doc:
            spans = _page_spans(page)
            for span in spans:
                span_norm = _norm(span["text"])
                if target not in span_norm:
                    continue
                # 在该 Span 文本中定位原始片段（精确优先，归一化兜底）
                raw_old = old_val if old_val in span["text"] else _locate_raw(span["text"], old_val)
                if raw_old is None:
                    continue
                bbox = fitz.Rect(span["bbox"])
                color = span.get("color", 0)
                if isinstance(color, int):
                    color = ((color >> 16) & 255) / 255, ((color >> 8) & 255) / 255, (color & 255) / 255
                bold = "bold" in (span.get("font", "") or "").lower()
                size = float(span.get("size") or 10.0)

                if new_val is None:
                    # 删除：只 redact
                    page.add_redact_annot(bbox)
                    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
                    hit = True
                    applied.append({"path": path})
                    continue

                new_span_text = span["text"].replace(raw_old, new_val)
                if new_span_text == span["text"] and _norm(new_span_text) == span_norm:
                    new_span_text = new_val  # 整段替换
                fontname = "china-s" if re.search(r"[\u4e00-\u9fff]", new_span_text) else "helv"
                fit_size = _fit_size(new_span_text, fontname, size, bbox.width)
                page.add_redact_annot(bbox)
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
                x, y = _span_baseline(span)
                _insert_text(page, (x, y), new_span_text, fit_size, fontname, color, bold)
                if fit_size < size * 0.92:
                    (applied if fit_size >= MIN_FONT_SIZE else failed).append(
                        {"path": path, "reason": f"字号缩至 {fit_size:.1f}pt 以适配原宽度"}
                        if fit_size >= MIN_FONT_SIZE else
                        {"path": path, "reason": "新内容过长，原版式放不下"})
                    if fit_size < MIN_FONT_SIZE:
                        hit = False
                        break
                hit = True
                applied.append({"path": path})
            if hit:
                break
        if not hit:
            failed.append({"path": path, "reason": "未能在原始 PDF 中定位旧内容"})

    buf = doc.tobytes(deflate=True, garbage=3)
    doc.close()
    return {"data": buf, "applied": applied, "failed": failed, "unchanged": False}


def _locate_raw(span_text: str, old_val: str) -> str | None:
    """Span 文本中与 old_val 对应的原始片段（处理空格/全半角差异）。"""
    if old_val in span_text:
        return old_val
    # 去空格后在原文中找对应切片
    target = _norm(old_val)
    if not target:
        return None
    idx_map: list[int] = []  # 归一化索引 -> 原文索引
    norm_chars: list[str] = []
    for i, c in enumerate(span_text):
        if c.isspace():
            continue
        nc = unicodedata.normalize("NFKC", c)
        for cc in _VARIANT_MAP:
            nc = nc.replace(cc, _VARIANT_MAP[cc])
        norm_chars.append(nc)
        idx_map.append(i)
    joined = "".join(norm_chars)
    pos = joined.find(target)
    if pos < 0:
        return None
    start = idx_map[pos]
    end = idx_map[min(pos + len(target) - 1, len(idx_map) - 1)] + 1
    return span_text[start:end]
