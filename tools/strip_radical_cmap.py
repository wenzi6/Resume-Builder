"""剥离字体 cmap 中与汉字共用字形的部首区段（CLI 封装）。

Chromium 为 PDF 子集构建 ToUnicode 时按字形反查 Unicode，会命中部首码位
（如 U+2FBC ⾼ 而不是 U+9AD8 高），导致 pdfplumber/pdfminer 提取出错误字符。
pymupdf 不受影响，但 ATS 解析常用 pdfplumber，故必须修掉。

用法：python tools/strip_radical_cmap.py [fonts_dir]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fontTools.ttLib import TTFont

from resume_builder.engine.font_convert import strip_radical_cmap


def main() -> int:
    fonts_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "fonts"
    total = 0
    for ttf in sorted(fonts_dir.glob("*.ttf")):
        font = TTFont(str(ttf))
        n = strip_radical_cmap(font)
        if n:
            font.save(str(ttf))
        font.close()
        total += n
        print(f"{ttf.name}: removed {n} radical cmap entries")
    print(f"total: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
