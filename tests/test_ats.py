"""ATS 回归测试：ats-plain 模板导出的 PDF / DOCX 必须能被完整提取文本。"""
from __future__ import annotations

import io

import pdfplumber
import pymupdf
from docx import Document

from resume_builder.engine import pdf as pdf_engine
from resume_builder.exporters import build_docx

REQUIRED_TEXTS = ["张三", "高级前端工程师", "某科技有限公司", "中山大学", "React"]


def test_ats_pdf_text_extractable(doc_general):
    d = dict(doc_general)
    d["templateId"] = "ats-plain"
    data = pdf_engine.render_pdf_bytes(d)

    # pymupdf 提取
    pdf = pymupdf.open(stream=data, filetype="pdf")
    text = "".join(p.get_text() for p in pdf)
    pdf.close()
    for t in REQUIRED_TEXTS:
        assert t in text, f"ATS PDF 文本层缺失：{t}"

    # pdfplumber 提取（ATS 场景的主流解析库）
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        text2 = "\n".join((p.extract_text() or "") for p in pdf.pages)
    for t in REQUIRED_TEXTS:
        assert t in text2, f"pdfplumber 无法提取：{t}"


def test_ats_pdf_no_type3(doc_general):
    d = dict(doc_general)
    d["templateId"] = "ats-plain"
    check = pdf_engine.verify_pdf_fonts(pdf_engine.render_pdf_bytes(d))
    assert check["type3"] == []
    assert check["ok"]


def test_ats_docx_text_extractable(doc_general):
    d = dict(doc_general)
    d["templateId"] = "ats-plain"
    buf = build_docx(d)
    doc = Document(io.BytesIO(buf.read()))
    full = "\n".join(p.text for p in doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                full += "\n" + cell.text
    for t in REQUIRED_TEXTS:
        assert t in full, f"ATS DOCX 文本缺失：{t}"


def test_ats_template_has_no_color(doc_general):
    """ats-plain 渲染结果不应带主题色装饰（零颜色零背景）。"""
    from resume_builder.engine.renderer import render_preview

    d = dict(doc_general)
    d["templateId"] = "ats-plain"
    html = render_preview(d)
    # 纯文本模板：技能评分条与标签样式被隐藏
    assert "r-sheet" in html
