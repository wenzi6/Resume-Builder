"""字体嵌入实证测试：渲染 test.html -> PDF，检查 @font-face 加载状态与 PDF 内嵌字体。"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

html = Path(sys.argv[1]).absolute()
pdf = Path(sys.argv[2]).absolute()
url = html.as_uri()

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page()
    page.goto(url)
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    css_fonts = page.evaluate(
        """() => {
            const out = [];
            document.fonts.forEach(f => out.push({family: f.family, weight: f.weight, status: f.status}));
            return out;
        }"""
    )
    page.pdf(path=str(pdf), format="A4", print_background=True)
    b.close()

import fitz  # pymupdf

doc = fitz.open(pdf)
embedded = []
for i, pg in enumerate(doc):
    for f in pg.get_fonts(full=True):
        xref, ext, ftype, basefont, name, encoding = f[0], f[1], f[2], f[3], f[4], f[5]
        try:
            basename, fext, fsubtype, buf = doc.extract_font(xref)
            emb_size = len(buf) if buf else 0
        except Exception as e:
            emb_size = -1
        embedded.append(
            {"page": i, "basefont": basefont, "type": ftype, "embedded_bytes": emb_size}
        )

print(
    json.dumps(
        {
            "css_fontfaces": css_fonts,
            "pdf_size_kb": round(pdf.stat().st_size / 1024, 1),
            "pdf_fonts": embedded,
        },
        ensure_ascii=False,
        indent=1,
    )
)
