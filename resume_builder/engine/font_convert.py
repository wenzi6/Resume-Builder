"""字体转换与清洗（包内单一事实来源）。

Chromium 的 PDF 后端对 CFF 轮廓的 web font 会降级为 Type3（文本层损坏），
只有 glyf 轮廓能正常嵌入为 Type0 子集；此外 Noto CJK 字体的 cmap 中康熙
部首（U+2E80–U+2FDF）与汉字共用字形，Chromium 构建 ToUnicode 时按字形
反查会命中部首码位，导致 pdfplumber/pdfminer 提取乱码。

tools/otf2ttf.py 与 tools/strip_radical_cmap.py 是本模块的 CLI 封装。
"""
from __future__ import annotations

from pathlib import Path

from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable

MAX_ERR = 1.0

# CJK Radicals Supplement + Kangxi Radicals：与汉字共用字形、简历中几乎不用
RADICAL_RANGES = [(0x2E80, 0x2EFF), (0x2F00, 0x2FDF)]


def is_cff(font: TTFont) -> bool:
    return font.sfntVersion == "OTTO" and "CFF " in font


def glyphs_to_quadratic(glyphset, max_err: float = MAX_ERR):
    quad = {}
    for old_name in glyphset.keys():
        glyph = glyphset[old_name]
        tt_pen = TTGlyphPen(glyphset)
        cu2qu_pen = Cu2QuPen(tt_pen, max_err, reverse_direction=True)
        glyph.draw(cu2qu_pen)
        quad[old_name] = tt_pen.glyph()
    return quad


def update_hmtx(font, glyf) -> None:
    hmtx = font["hmtx"]
    for glyph_name, glyph in glyf.glyphs.items():
        if hasattr(glyph, "xMin"):
            hmtx[glyph_name] = (hmtx[glyph_name][0], glyph.xMin)


def otf_to_ttf(font: TTFont, post_format: float = 2.0, **kwargs) -> TTFont:
    """CFF(OTF) -> glyf(TTF)。fontTools 官方配方。"""
    assert font.sfntVersion == "OTTO", "not a CFF OTF"
    assert "CFF " in font, "no CFF table"

    glyph_order = font.getGlyphOrder()

    font["loca"] = newTable("loca")
    font["glyf"] = glyf = newTable("glyf")
    glyf.glyphOrder = glyph_order
    glyf.glyphs = glyphs_to_quadratic(font.getGlyphSet(), **kwargs)

    del font["CFF "]
    if "VORG" in font:
        del font["VORG"]

    glyf.compile(font)
    update_hmtx(font, glyf)

    font["maxp"] = maxp = newTable("maxp")
    maxp.tableVersion = 0x00010000
    maxp.maxZones = 1
    maxp.maxTwilightPoints = 0
    maxp.maxFunctionDefs = 0
    maxp.maxInstructionDefs = 0
    maxp.maxStorage = 0
    maxp.maxStackElements = 0
    maxp.maxSizeOfInstructions = 0
    maxp.maxComponentElements = max(
        (len(getattr(g, "components", [])) for g in glyf.glyphs.values()), default=0
    )
    maxp.compile(font)

    post = font["post"]
    post.formatType = post_format
    post.extraNames = []
    post.mapping = {}
    post.glyphOrder = glyph_order

    font.sfntVersion = "\000\001\000\000"
    return font


def strip_radical_cmap(font: TTFont) -> int:
    """剥离 cmap 中与汉字共用字形的部首区段，返回移除的条目数。"""
    removed = 0
    for table in font["cmap"].tables:
        if not table.isUnicode:
            continue
        before = len(table.cmap)
        table.cmap = {
            cp: g for cp, g in table.cmap.items()
            if not any(lo <= cp <= hi for lo, hi in RADICAL_RANGES)
        }
        removed += before - len(table.cmap)
    return removed


def ensure_embeddable(font: TTFont) -> TTFont:
    """CFF → glyf + 剥离部首 cmap，返回可安全嵌入 PDF 的字体。"""
    if is_cff(font):
        font = otf_to_ttf(font)
    strip_radical_cmap(font)
    return font


# ---------------- 字体元信息 ----------------

def read_font_meta(path: str | Path) -> dict:
    """读取字体家族名与字重（用于注册与展示）。"""
    font = TTFont(str(path))
    family = ""
    weight = 400
    try:
        name = font["name"]
        # 优先 Windows 英文家族名（nameID 1, platformID 3）
        for nid in (1, 16):
            rec = name.getName(nid, 3, 1, 0x409) or name.getName(nid, 1, 0, 0)
            if rec:
                family = str(rec).strip()
                if family:
                    break
        sub = name.getName(2, 3, 1, 0x409) or name.getName(2, 1, 0, 0)
        sub_l = str(sub).lower() if sub else ""
        if "bold" in sub_l or "black" in sub_l or "heavy" in sub_l:
            weight = 700
        elif "medium" in sub_l or "demibold" in sub_l or "semibold" in sub_l:
            weight = 500
        elif "light" in sub_l or "thin" in sub_l or "extralight" in sub_l:
            weight = 300
        else:
            try:
                weight = int(font["OS/2"].usWeightClass)
            except Exception:  # noqa: BLE001
                weight = 400
    finally:
        font.close()
    if not family:
        family = Path(path).stem
    return {"family": family, "weight": weight}
