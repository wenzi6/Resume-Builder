"""调试：检查 PDF 内嵌字体的原始信息 + 渲染页面图像。"""
import pymupdf

from resume_builder.engine import pdf as pdf_engine
from resume_builder.sample import sample_general
from resume_builder.config import OUTPUT_DIR


def main() -> None:
    doc = sample_general()
    doc["templateId"] = "classic"
    data = pdf_engine.render_pdf_bytes(doc)

    pdf = pymupdf.open(stream=data, filetype="pdf")
    print("pages:", pdf.page_count)
    for pno in range(pdf.page_count):
        page = pdf[pno]
        fonts = page.get_fonts(full=True)
        print(f"--- page {pno + 1}: {len(fonts)} fonts")
        for f in fonts:
            print("   ", f)

    # 渲染第一页为图像，供视觉检查
    pix = pdf[0].get_pixmap(dpi=110)
    img = OUTPUT_DIR / "_font_check_page1.png"
    pix.save(str(img))
    print("image:", img, pix.width, "x", pix.height)

    # 提取文本前 200 字
    txt = pdf[0].get_text()
    print("text sample:", repr(txt[:150]))
    pdf.close()


if __name__ == "__main__":
    main()
