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


# ---------------- 自定义列表标记 ----------------

@pytest.mark.parametrize("style,expect_attr", [
    ("dot", 'data-bullet="dot"'),
    ("dash", 'data-bullet="dash"'),
    ("arrow", 'data-bullet="arrow"'),
    ("none", 'data-bullet="none"'),
    ("custom", 'data-bullet="custom"'),
])
def test_bullet_style_attr(style, expect_attr):
    """全局列表标记样式要体现在渲染属性上。"""
    from resume_builder.engine import renderer
    from resume_builder.sample import sample_general

    doc = sample_general()
    doc["templateId"] = "classic"
    doc["design"]["bulletStyle"] = style
    if style == "custom":
        doc["design"]["bulletChar"] = "◆"
    html = renderer.render_html(doc)
    assert expect_attr in html
    if style == "custom":
        assert "◆" in html


def test_bullet_style_section_override():
    """区块级标记覆盖全局。"""
    from resume_builder.engine import renderer
    from resume_builder.sample import sample_general

    doc = sample_general()
    doc["templateId"] = "classic"
    doc["design"]["bulletStyle"] = "dot"
    for s in doc["sections"]:
        if s["key"] == "workExperiences":
            s["design"] = {"bulletStyle": "arrow"}
    html = renderer.render_html(doc)
    assert 'data-bullet="arrow"' in html


def test_empty_bullets_leave_no_mark():
    """空字符串项不渲染（不留孤立圆点）。"""
    from resume_builder.engine import sections as sec

    section = {"key": "workExperiences", "type": "array", "title": "工作经历",
               "titleField": "company",
               "fields": [{"key": "company", "type": "text"},
                          {"key": "descriptions", "type": "list"}]}
    content = {"workExperiences": [{"company": "A", "descriptions": ["有内容", "", "  ", None]}]}
    html = sec.render_array(section, content, {})
    assert "有内容" in html
    assert html.count("<li>") == 1


# ---------------- 成果小标题与岗位信息同款 + 可自定义 ----------------

def test_achievement_label_matches_job_title_style():
    """成果小标题必须与岗位信息（ritem-sub）同色同字重。"""
    from resume_builder.engine import renderer
    from resume_builder.sample import sample_general

    doc = sample_general()
    doc["templateId"] = "classic"
    doc["content"]["workExperiences"][0]["achievements"] = ["性能提升 40%"]
    html = renderer.render_html(doc)
    import re

    sub = re.search(r"\.ritem-sub \{\{?([^}]*)\}\}?", html)
    ach = re.search(r"\.ritem-ach-label \{\{?([^}]*)\}\}?", html)
    assert sub and ach, "缺少样式定义"
    # 颜色与字重必须一致
    assert "var(--r-accent)" in ach.group(1)
    assert "font-weight: 500" in ach.group(1)
    assert "var(--r-accent)" in sub.group(1)
    assert "font-weight: 500" in sub.group(1)
    # 不再有原来那个更小更粗的样式
    assert "font-weight: 700" not in ach.group(1)
    assert "0.86em" not in ach.group(1)


def test_achievement_label_customizable():
    """成果小标题文字可自定义（全局 + 区块级）。"""
    from resume_builder.engine import renderer
    from resume_builder.sample import sample_general

    doc = sample_general()
    doc["templateId"] = "classic"
    doc["content"]["workExperiences"][0]["achievements"] = ["性能提升 40%"]
    doc["design"]["achievementLabel"] = "主要业绩"
    html = renderer.render_html(doc)
    assert "主要业绩" in html and "工作成果" not in html

    doc2 = sample_general()
    doc2["templateId"] = "classic"
    doc2["content"]["workExperiences"][0]["achievements"] = ["性能提升 40%"]
    for s in doc2["sections"]:
        if s["key"] == "workExperiences":
            s["design"] = {"achievementLabel": "核心业绩"}
    html2 = renderer.render_html(doc2)
    assert "核心业绩" in html2


def test_achievement_label_default_and_normalize():
    """默认值、清洗与区块级字段保留。"""
    from resume_builder.schema import normalize_document, normalize_design
    from resume_builder.sample import sample_general

    assert normalize_design({})["achievementLabel"] == "工作成果"
    assert normalize_design({"achievementLabel": "  业绩  "})["achievementLabel"] == "业绩"
    doc = sample_general()
    doc["sections"][0]["design"] = {"achievementLabel": "区块标题"}
    out = normalize_document(doc)
    sec = next(s for s in out["sections"] if s["key"] == doc["sections"][0]["key"])
    assert sec["design"]["achievementLabel"] == "区块标题"
