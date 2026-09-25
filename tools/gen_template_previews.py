"""生成模板预览图：每套模板渲染示例简历 → PDF 首页 → PNG。

用法：python tools/gen_template_previews.py
输出：templates/<id>/preview.png（约 300px 宽，供编辑器模板菜单显示）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf

from resume_builder.engine import pdf as pdf_engine
from resume_builder.config import TEMPLATES_DIR
from resume_builder.sample import sample_general

WIDTH = 300  # 预览图宽度（px）


def main() -> int:
    doc = sample_general()
    ok = 0
    for tpl_dir in sorted(p for p in TEMPLATES_DIR.iterdir() if p.is_dir()):
        if not (tpl_dir / "layout.html").exists():
            continue
        d = dict(doc)
        d["templateId"] = tpl_dir.name
        try:
            data = pdf_engine.render_pdf_bytes(d)
            with pymupdf.open(stream=data, filetype="pdf") as pdf:
                pix = pdf[0].get_pixmap(dpi=72)
                # 缩放到目标宽度
                scale = WIDTH / pix.width
                pix = pdf[0].get_pixmap(matrix=pymupdf.Matrix(scale * 72 / 72, scale * 72 / 72))
                pix.save(str(tpl_dir / "preview.png"))
            print(f"{tpl_dir.name}: preview.png ({pix.width}x{pix.height})")
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"{tpl_dir.name}: FAILED {e}")
    print(f"done: {ok}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
