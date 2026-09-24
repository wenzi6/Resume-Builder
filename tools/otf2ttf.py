"""CFF(OTF) -> glyf(TTF) 转换器。

Chromium 的 PDF 后端对 CFF 轮廓的 web font 会降级为 Type3（文本层损坏），
而 glyf 轮廓能正常嵌入为 Type0 子集。因此把下载到的静态 OTF 一次性转换为 TTF。

用法：python tools/otf2ttf.py <in.otf> <out.ttf>
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable

MAX_ERR = 1.0


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


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    t0 = time.time()
    font = TTFont(str(src))
    font = otf_to_ttf(font)
    font.save(str(dst))
    print(f"{src.name} -> {dst.name}  {dst.stat().st_size/1024/1024:.1f} MB  {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
