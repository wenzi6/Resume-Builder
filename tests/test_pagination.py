"""分页回归测试：1 / 2 / 3 页内容的页数正确、无空白页、标题不落页底。"""
from __future__ import annotations

import pymupdf
import pytest

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


# ---------------- 编码回归：worker 中文输出 ----------------

def test_measure_with_chinese_warnings(doc_general):
    """区块超过一页 → worker 输出含中文警告。

    回归：父进程曾用 Windows 本地编码（GBK）读 worker 的 UTF-8 输出，
    UnicodeDecodeError 导致读取线程崩溃、worker 被误判死亡、分页测量整体失败。
    """
    from resume_builder.engine import pdf as pdf_engine

    d = dict(doc_general)
    d["templateId"] = "classic"
    # 造一个超过一页的区块（触发 tallerThanPage 中文警告）
    for i in range(14):
        d["content"]["workExperiences"].append({
            "company": f"高公司{i}", "jobTitle": "工程师",
            "date": "2020-01 – 2021-01",
            "descriptions": ["负责系统建设与维护，保障稳定性与性能指标" for _ in range(4)],
        })
    info = pdf_engine.measure_pages(d)
    assert info["pageCount"] >= 2
    # 警告必须原样回来（中文）
    assert any("高度超过一页" in w for w in info["warnings"]), info["warnings"]


def test_measure_fallback_path_with_chinese(doc_general, monkeypatch):
    """单次子进程兜底路径同样不能因中文输出崩溃。"""
    from resume_builder.engine import pdf as pdf_engine

    d = dict(doc_general)
    d["templateId"] = "classic"
    for i in range(14):
        d["content"]["workExperiences"].append({
            "company": f"兜底公司{i}", "jobTitle": "工程师",
            "date": "2020-01 – 2021-01",
            "descriptions": ["负责系统建设与维护，保障稳定性与性能指标" for _ in range(4)],
        })
    # 强制走兜底：_broken = True
    pdf_engine._pool._broken = True
    try:
        info = pdf_engine.measure_pages(d)
        assert info["pageCount"] >= 2
        assert any("高度超过一页" in w for w in info["warnings"])
    finally:
        pdf_engine._pool._broken = False


# ---------------- 核心契约：测量页数 == 实际导出页数 ----------------

def _actual_pdf_pages(data: bytes) -> int:
    import pymupdf

    with pymupdf.open(stream=data, filetype="pdf") as p:
        return p.page_count


@pytest.mark.parametrize("tpl", ["classic", "modern", "minimal", "professional", "tech", "ats-plain"])
def test_measured_pages_match_actual(doc_general, tpl):
    """页数必须与真实导出一致（徽章/分页线/自动适应都依赖它）。

    历史 bug：测量按屏幕布局估算，与 Chromium 真实分页系统性不符
    （双栏模板、break-inside:avoid 挪页、视口宽度等），导致徽章说 2 页
    导出却是 3 页。现在页数以实际渲染的 PDF 为准。
    """
    from resume_builder.engine import pdf as pdf_engine

    d = dict(doc_general)
    d["templateId"] = tpl
    info = pdf_engine.measure_pages(d)
    actual = _actual_pdf_pages(pdf_engine.render_pdf_bytes(d))
    assert info["pageCount"] == actual, f"{tpl}: measured={info['pageCount']} actual={actual}"


def test_measured_pages_match_actual_multicolumn(doc_tech):
    """双栏模板（modern）也必须一致——各栏是独立竖向流。"""
    from resume_builder.engine import pdf as pdf_engine

    d = dict(doc_tech)
    d["templateId"] = "modern"
    info = pdf_engine.measure_pages(d)
    actual = _actual_pdf_pages(pdf_engine.render_pdf_bytes(d))
    assert info["pageCount"] == actual


@pytest.mark.parametrize("extra", [0, 5, 9, 12])
def test_measured_pages_match_actual_growing(doc_general, extra):
    """内容增减时页数始终与实际一致（自动适应一页的正确性基础）。"""
    from resume_builder.engine import pdf as pdf_engine

    d = dict(doc_general)
    d["templateId"] = "classic"
    for i in range(extra):
        d["content"]["workExperiences"].append({
            "company": f"回归公司{i}", "jobTitle": "工程师",
            "date": "2020-01 – 2021-01",
            "descriptions": ["负责系统建设与维护，保障稳定性", "优化性能指标 30%"],
        })
    info = pdf_engine.measure_pages(d)
    actual = _actual_pdf_pages(pdf_engine.render_pdf_bytes(d))
    assert info["pageCount"] == actual, f"extra={extra}: measured={info['pageCount']} actual={actual}"


def test_measured_pages_match_actual_with_breaks(doc_tech):
    """手动分页后页数仍与实际一致。"""
    from resume_builder.engine import pdf as pdf_engine

    d = dict(doc_tech)
    d["templateId"] = "classic"
    d["pageBreaks"] = ["selfEvaluation"]
    info = pdf_engine.measure_pages(d)
    actual = _actual_pdf_pages(pdf_engine.render_pdf_bytes(d, breaks=["selfEvaluation"]))
    assert info["pageCount"] == actual
