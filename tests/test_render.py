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
