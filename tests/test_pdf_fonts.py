"""字体回归测试（P0）：PDF 内嵌字体必须为 Type0 子集且中文可检索。

背景：Chromium 的 PDF 后端无法正确嵌入 CFF 轮廓的 web font，会降级为
Type3（文本层损坏、ATS 无法解析）。解决方案是把 fonts/ 下的 Noto OTF
一次性转换为 glyf TTF（tools/otf2ttf.py）。本测试守住这个结论。
"""
from __future__ import annotations

import re

import pytest

from resume_builder.engine import pdf as pdf_engine
from resume_builder.engine.renderer import render_for_pdf

TEMPLATES = ["classic", "modern", "minimal", "professional", "tech", "ats-plain"]


@pytest.mark.parametrize("tpl", TEMPLATES)
def test_pdf_fonts_type0_with_chinese(doc_general, tpl):
    """每套模板：无 Type3 字体 + 中文可检索（乱码文本通不过）。"""
    d = dict(doc_general)
    d["templateId"] = tpl
    data = pdf_engine.render_pdf_bytes(d)
    check = pdf_engine.verify_pdf_fonts(data)
    assert check["type3"] == [], f"{tpl} 出现 Type3 字体：{check['type3']}"
    assert check["textExtractable"], f"{tpl} 文本层不可提取"
    assert re.search(r"[\u4e00-\u9fff]", check["textSample"]), \
        f"{tpl} 文本层无中文（乱码）：{check['textSample']!r}"
    assert check["ok"]


def test_pdf_fonts_serif(doc_general):
    """serif 档（Noto Serif SC）同样必须是 Type0。"""
    d = dict(doc_general)
    d["templateId"] = "professional"
    d["design"] = {"fontFamily": "serif"}
    check = pdf_engine.verify_pdf_fonts(pdf_engine.render_pdf_bytes(d))
    assert check["type3"] == []
    assert check["ok"]


def test_pdf_fonts_known_chinese(doc_general):
    """具体中文字符串必须原样出现在文本层。"""
    d = dict(doc_general)
    d["templateId"] = "classic"
    data = pdf_engine.render_pdf_bytes(d)
    import pymupdf

    pdf = pymupdf.open(stream=data, filetype="pdf")
    text = "".join(p.get_text() for p in pdf)
    pdf.close()
    assert "张三" in text
    assert "高级前端工程师" in text
    assert "中山大学" in text


def test_render_for_pdf_uses_file_font_urls(doc_general):
    """PDF 模式字体必须走 file:// 绝对路径（预览模式走 /fonts HTTP 路由）。"""
    html = render_for_pdf(doc_general)
    assert "url('file:///" in html
    assert "format('truetype')" in html
    # 不应出现以 /fonts 开头的相对 URL（file:// 路径中间段的 /fonts/ 不算）
    assert "url('/fonts/" not in html
    assert 'url("/fonts/' not in html


def test_no_otf_left_in_fonts_dir():
    """fonts/ 只允许保留 glyf TTF（CFF OTF 会被降级为 Type3）。"""
    from resume_builder.config import FONTS_DIR

    otfs = list(FONTS_DIR.glob("*.otf"))
    assert not otfs, f"fonts/ 下仍有 CFF OTF：{otfs}"
    ttfs = list(FONTS_DIR.glob("*.ttf"))
    assert len(ttfs) >= 5
