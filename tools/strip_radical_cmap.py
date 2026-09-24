"""剥离字体 cmap 中与汉字共用字形的部首区段（U+2E80–U+2FDF）。

Chromium 为 PDF 子集构建 ToUnicode 时按字形反查 Unicode，会命中部首码位
（如 U+2FBC ⾼ 而不是 U+9AD8 高），导致 pdfplumber/pdfminer 提取出错误字符。
pymupdf 不受影响，但 ATS 解析常用 pdfplumber，故必须修掉。

用法：python tools/strip_radical_cmap.py [fonts_dir]
"""
from __future__ import annotations

import sys
from pathlib import Path

from fontTools.ttLib import TTFont

# CJK Radicals Supplement + Kangxi Radicals：与汉字共用字形、简历中几乎不用
STRIP_RANGES = [(0x2E80, 0x2EFF), (0x2F00, 0x2FDF)]


def should_strip(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in STRIP_RANGES)


def strip_font(path: Path) -> int:
    font = TTFont(str(path))
    removed = 0
    for table in font["cmap"].tables:
        if not table.isUnicode:
            continue
        before = len(table.cmap)
        table.cmap = {cp: g for cp, g in table.cmap.items() if not should_strip(cp)}
        removed += before - len(table.cmap)
    if removed:
        font.save(str(path))
    return removed


def main() -> int:
    fonts_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "fonts"
    total = 0
    for ttf in sorted(fonts_dir.glob("*.ttf")):
        n = strip_font(ttf)
        total += n
        print(f"{ttf.name}: removed {n} radical cmap entries")
    print(f"total: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
