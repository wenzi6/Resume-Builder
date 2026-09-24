"""对照实验：可变字体的两种声明方式，检查 PDF 内嵌字体类型。"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
import fitz

html = Path("control.html").absolute()
pdf = Path("control.pdf").absolute()

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page()
    page.goto(html.as_uri())
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    css_fonts = page.evaluate(
        "() => { const out = []; document.fonts.forEach(f => out.push({family: f.family, status: f.status})); return out; }"
    )
    page.pdf(path=str(pdf), format="A4", print_background=True)
    b.close()

doc = fitz.open(pdf)
fonts = []
for pg in doc:
    for f in pg.get_fonts(full=True):
        fonts.append({"basefont": f[3], "type": f[2]})
print(json.dumps({"css": css_fonts, "pdf_kb": round(pdf.stat().st_size / 1024, 1), "fonts": fonts}, ensure_ascii=False))
