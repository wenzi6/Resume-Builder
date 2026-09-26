"""渲染冒烟测试：6 套模板 × 2 份示例数据，验证语义标记完整。"""
from __future__ import annotations

import pytest

from resume_builder.engine.renderer import render_preview
from resume_builder.sample import sample_general, sample_tech

TEMPLATES = ["classic", "modern", "minimal", "professional", "tech", "ats-plain"]

# 所有模板共享的语义标记（sections.py 产出，模板 CSS 只做视觉差异化）
REQUIRED_MARKERS = [
    'class="r-sheet',
    'data-section="profile"',
    'data-section="workExperiences"',
    'data-section="projects"',
    'data-section="educations"',
    'data-section="skills"',
    'class="rsec-title"',
    'class="ritem"',
    'class="rlist"',
    "@font-face",
    "@page",
    ":root",
]


@pytest.mark.parametrize("tpl", TEMPLATES)
@pytest.mark.parametrize("sample", ["general", "tech"])
def test_render_has_all_markers(sample, tpl):
    doc = sample_general() if sample == "general" else sample_tech()
    doc["templateId"] = tpl
    html = render_preview(doc)
    for marker in REQUIRED_MARKERS:
        assert marker in html, f"{sample}/{tpl} 缺少语义标记 {marker}"


@pytest.mark.parametrize("tpl", TEMPLATES)
def test_render_contains_sample_content(tpl):
    doc = sample_general()
    doc["templateId"] = tpl
    html = render_preview(doc)
    assert "张三" in html
    assert "某科技有限公司" in html
    assert "中山大学" in html
    assert "React" in html


@pytest.mark.parametrize("tpl", TEMPLATES)
def test_render_preview_font_urls(tpl):
    """预览模式字体走 /fonts 路由（PDF 模式走 file://）。"""
    doc = sample_general()
    doc["templateId"] = tpl
    html = render_preview(doc)
    assert "/fonts/NotoSansSC-Regular.ttf" in html
    assert "file:///" not in html


def test_empty_document_renders_empty_state():
    """全空文档渲染出 .r-empty 占位而不是崩溃。"""
    from resume_builder.schema import new_document

    doc = new_document(template_id="classic", title="空文档")
    html = render_preview(doc)
    assert "r-sheet" in html
    assert "r-empty" in html


def test_design_tokens_in_css():
    """设计参数正确编译为 CSS 变量。"""
    from resume_builder.engine.tokens import build_root_css

    css = build_root_css({"accent": "#ff0000", "fontScale": 1.1, "compact": True})
    assert "--r-accent: #ff0000" in css
    # compact 会把 fontScale 联动为 0.94（COMPACT_DESIGN）
    assert "--r-fs-body: calc(10.5pt * 0.940)" in css
    # compact 时行距/间距/边距联动
    assert "--r-lh: 1.32" in css
    assert "--r-gap: 12px" in css
    assert "--r-margin: 15.0mm" in css


# ---------------- 手动分页点 + 常驻 worker 进程池 ----------------


def test_render_pdf_with_breaks(doc_tech):
    """render_pdf_bytes 支持手动分页点（worker pdf 模式的 breaks 参数）。"""
    from resume_builder.engine import pdf as pdf_engine

    d = dict(doc_tech)
    d["templateId"] = "classic"
    base = pdf_engine.render_pdf_bytes(d)
    with_breaks = pdf_engine.render_pdf_bytes(d, breaks=["selfEvaluation"])
    import pymupdf

    def pages(b):
        with pymupdf.open(stream=b, filetype="pdf") as p:
            return p.page_count

    assert pages(with_breaks) == pages(base) + 1


def test_worker_pool_warm_reuse(doc_general):
    """常驻 worker：热请求显著快于冷请求（Chromium 复用）。"""
    import time

    from resume_builder.engine import pdf as pdf_engine

    doc = dict(doc_general)
    doc["templateId"] = "classic"
    t0 = time.time()
    pdf_engine.measure_pages(doc)          # 冷：可能含 Chromium 启动
    t_cold = time.time() - t0
    t0 = time.time()
    for _ in range(3):
        pdf_engine.measure_pages(doc)
    t_warm = (time.time() - t0) / 3
    pdf_engine._pool.close()
    assert t_warm < t_cold * 1.5, f"warm={t_warm:.2f}s cold={t_cold:.2f}s"


def test_worker_pool_survives_death(doc_general):
    """worker 被杀后自动重启，请求仍成功。"""
    from resume_builder.engine import pdf as pdf_engine

    doc = dict(doc_general)
    doc["templateId"] = "classic"
    first = pdf_engine.measure_pages(doc)
    proc = pdf_engine._pool._proc
    if proc:
        proc.kill()
        proc.wait(timeout=5)
        pdf_engine._pool._proc = None
    second = pdf_engine.measure_pages(doc)
    assert second["pageCount"] == first["pageCount"]
    pdf_engine._pool.close()


def test_worker_pool_fallback_on_broken(doc_general, monkeypatch):
    """worker 无法启动时回退单次子进程（_broken 标记）。"""
    from resume_builder.engine import pdf as pdf_engine

    doc = dict(doc_general)
    doc["templateId"] = "classic"

    def boom(self):
        raise RuntimeError("spawn failed")

    monkeypatch.setattr(pdf_engine._WorkerPool, "_spawn", boom)
    info = pdf_engine.measure_pages(doc)
    assert info["pageCount"] >= 1
    info2 = pdf_engine.measure_pages(doc)
    assert info2["pageCount"] >= 1


# ---------------- 排版深度：标题字体 + 区块级覆盖 ----------------


def test_head_font_design(doc_general):
    """headFont 独立于 fontFamily 生效。"""
    from resume_builder.engine.tokens import build_root_css

    css = build_root_css({"fontFamily": "sans", "headFont": "serif"})
    assert "Noto Serif SC" in css.split("--r-font-head:")[1].split(";")[0]
    assert "Noto Sans SC" in css.split("--r-font-body:")[1].split(";")[0]


def test_section_design_hide_title(doc_general):
    """区块级 hideTitle：标题不渲染，内容仍在。"""
    import re

    from resume_builder.engine.renderer import render_preview

    d = dict(doc_general)
    for s in d["sections"]:
        if s["key"] == "skills":
            s["design"] = {"hideTitle": True}
    html = render_preview(d)
    assert 'data-section="skills"' in html
    m = re.search(r'<section class="rsec" data-section="skills">(.{0,120})', html, re.S)
    assert "rsec-title" not in (m.group(1) if m else ""), "hideTitle 未生效"


def test_section_design_columns(doc_general):
    """区块级 columns=2：技能双列类名。"""
    from resume_builder.engine.renderer import render_preview

    d = dict(doc_general)
    for s in d["sections"]:
        if s["key"] == "skills":
            s["design"] = {"columns": 2}
    html = render_preview(d)
    assert "rskills-cols" in html, "columns=2 未生效"


    html = render_preview(d)
    assert "rskills-cols" in html or True


# ---------------- 自由大框（技能等文本型区块） ----------------

def test_skills_renders_as_free_box():
    """技能渲染为一个自由大框：无星级、无标签 pill。"""
    from resume_builder.engine import sections as sec

    section = {"key": "skills", "type": "free", "title": "专业技能",
               "fields": [{"key": "descriptions", "type": "free"}]}
    content = {"skills": {"descriptions": ["熟悉招聘全流程", "熟悉 IT 技术岗位招聘"]}}
    html = sec.render_free(section, content, {})
    assert 'class="rfree"' in html
    assert "熟悉招聘全流程" in html
    assert "rrate" not in html and "rtag" not in html


def test_legacy_skills_migrated_to_free_list():
    """旧数据（featuredSkills 星级 + descriptions）归一化时合并成自由列表。"""
    from resume_builder.schema import normalize_document
    from resume_builder.sample import sample_general

    doc = sample_general()
    doc["content"]["skills"] = {
        "featuredSkills": [{"skill": "React", "rating": 5}, {"skill": "Vue", "rating": 4}],
        "descriptions": ["Webpack", "Vite"],
    }
    out = normalize_document(doc)
    skills = out["content"]["skills"]
    assert "featuredSkills" not in skills
    assert set(skills["descriptions"]) == {"React", "Vue", "Webpack", "Vite"}
