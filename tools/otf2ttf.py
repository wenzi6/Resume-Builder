"""CFF(OTF) -> glyf(TTF) 转换器（CLI 封装，实现在 resume_builder.engine.font_convert）。

Chromium 的 PDF 后端对 CFF 轮廓的 web font 会降级为 Type3（文本层损坏），
而 glyf 轮廓能正常嵌入为 Type0 子集。因此把下载到的静态 OTF 一次性转换为 TTF。

用法：python tools/otf2ttf.py <in.otf> <out.ttf>
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fontTools.ttLib import TTFont

from resume_builder.engine.font_convert import otf_to_ttf


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
