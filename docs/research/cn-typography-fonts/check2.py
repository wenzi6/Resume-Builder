"""检查 PDF 文本可提取性 + 渲染对比截图。"""
import fitz

doc = fitz.open("out.pdf")
page = doc[0]
text = page.get_text()
print("=== extracted text ===")
print(text)

# 渲染整页为 PNG 供视觉对比
pix = page.get_pixmap(dpi=110)
pix.save("compare.png")
print("saved compare.png", pix.width, "x", pix.height)

# 每行文字用的实际字体（span 级）
print("=== spans (font, size, text) ===")
d = page.get_text("dict")
for block in d["blocks"]:
    for line in block.get("lines", []):
        for span in line["spans"]:
            print(f"{span['font']!r:45} {round(span['size'],1):>5}  {span['text'][:30]}")
