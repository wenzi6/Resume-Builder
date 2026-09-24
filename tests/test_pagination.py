"""分页回归测试：1 / 2 / 3 页内容的页数正确、无空白页、标题不落页底。"""
from __future__ import annotations

import pymupdf

from resume_builder.engine import pdf as pdf_engine

PAGE_TEMPLATE = "classic"


def _render_pdf(doc):
    return pdf_engine.render_pdf_bytes(doc)


def _page_texts(pdf_bytes):
    pdf = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    texts = [p.get_text().strip() for p in pdf]
    pdf.close()
    return texts


def test_single_page(doc_general):
    d = dict(doc_general)
    d["templateId"] = PAGE_TEMPLATE
    info = pdf_engine.measure_pages(d)
    assert info["pageCount"] == 1


def test_two_pages(doc_tech):
    d = dict(doc_tech)
    d["templateId"] = PAGE_TEMPLATE
    info = pdf_engine.measure_pages(d)
    assert info["pageCount"] == 2


def test_three_pages(long_doc):
    d = dict(long_doc)
    d["templateId"] = PAGE_TEMPLATE
    info = pdf_engine.measure_pages(d)
    assert info["pageCount"] == 3


def test_no_blank_pages(long_doc):
    """每一页都必须有实际内容（空白页是排版事故）。"""
    d = dict(long_doc)
    d["templateId"] = PAGE_TEMPLATE
    texts = _page_texts(_render_pdf(d))
    assert len(texts) >= 2
    for i, t in enumerate(texts):
        assert len(t) > 20, f"第 {i + 1} 页内容过少（疑似空白页）：{t[:40]!r}"


def test_manual_pagebreak_adds_page(doc_tech):
    """手动分页点把 2 页内容拆到 3 页（测量必须算上 .r-pagebreak）。"""
    d = dict(doc_tech)
    d["templateId"] = PAGE_TEMPLATE
    before = pdf_engine.measure_pages(d)["pageCount"]
    assert before == 2
    d["pageBreaks"] = ["selfEvaluation"]
    after = pdf_engine.measure_pages(d)["pageCount"]
    assert after == before + 1


def test_section_title_not_at_page_bottom(doc_tech):
    """区块标题不应落在页面底部 12% 内（会被 CSS break-after 规则挪走，
    这里验证测量数据能识别这种风险位置）。"""
    d = dict(doc_tech)
    d["templateId"] = PAGE_TEMPLATE
    info = pdf_engine.measure_pages(d)
    page_h = info["pageHeightPx"]
    risky = [
        s for s in info["sections"]
        if not s["tallerThanPage"] and not s["straddles"]
        and s["top"] % page_h > page_h * 0.88
    ]
    # 有风险位置时应给出建议分页点
    if risky:
        assert set(s["key"] for s in risky) <= set(info["suggestedBreaks"])


def test_last_page_not_near_empty(doc_general):
    """一页简历不应触发「末页内容过少」警告。"""
    d = dict(doc_general)
    d["templateId"] = PAGE_TEMPLATE
    info = pdf_engine.measure_pages(d)
    assert info["pageCount"] == 1
    assert not any("最后一页内容很少" in w for w in info["warnings"])
