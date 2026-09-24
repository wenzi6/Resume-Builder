"""视觉回归测试：6 套模板渲染为位图，与基线做像素对比。

基线生成 / 更新：REGEN_BASELINES=1 python -m pytest tests/test_visual_regression.py
判定：任一通道差值 > 8 的像素超过 0.1% 即失败（抗渲染抖动，抓排版事故）。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from resume_builder.engine import pdf as pdf_engine
from resume_builder.sample import sample_general

BASELINES = Path(__file__).resolve().parent / "baselines"
TEMPLATES = ["classic", "modern", "minimal", "professional", "tech", "ats-plain"]
DPI = 100
# 允许的差异像素比例（渲染抗锯齿等微小抖动）
TOLERANCE_RATIO = 0.001


def _render_pix(doc, dpi=DPI):
    import pymupdf

    data = pdf_engine.render_pdf_bytes(doc)
    pdf = pymupdf.open(stream=data, filetype="pdf")
    pix = pdf[0].get_pixmap(dpi=dpi)
    pdf.close()
    return pix


def _diff_ratio(a, b) -> float:
    """两个 Pixmap 的差异像素比例（尺寸不同直接返回 1.0）。"""
    if a.width != b.width or a.height != b.height or a.n != b.n:
        return 1.0
    sa, sb = a.samples, b.samples
    total = a.width * a.height
    diff = 0
    step = a.n
    for i in range(0, len(sa), step):
        if (
            abs(sa[i] - sb[i]) > 8
            or abs(sa[i + 1] - sb[i + 1]) > 8
            or abs(sa[i + 2] - sb[i + 2]) > 8
        ):
            diff += 1
    return diff / total


@pytest.mark.parametrize("tpl", TEMPLATES)
def test_visual_regression(tpl):
    doc = sample_general()
    doc["templateId"] = tpl
    pix = _render_pix(doc)

    baseline_path = BASELINES / f"{tpl}.png"
    if os.environ.get("REGEN_BASELINES") == "1":
        BASELINES.mkdir(parents=True, exist_ok=True)
        pix.save(str(baseline_path))
        pytest.skip(f"baseline regenerated: {tpl}")
    if not baseline_path.exists():
        pytest.skip(f"baseline 不存在（REGEN_BASELINES=1 生成）：{tpl}")

    import pymupdf

    baseline = pymupdf.Pixmap(str(baseline_path))
    ratio = _diff_ratio(pix, baseline)
    assert ratio <= TOLERANCE_RATIO, (
        f"{tpl} 模板渲染结果与基线差异过大（{ratio:.2%} > {TOLERANCE_RATIO:.2%}）——"
        "如果是预期的排版改动，请用 REGEN_BASELINES=1 更新基线"
    )


def test_all_baselines_exist():
    """防止有人删了基线目录导致回归测试静默跳过。"""
    if os.environ.get("REGEN_BASELINES") == "1":
        pytest.skip("regen 模式")
    missing = [t for t in TEMPLATES if not (BASELINES / f"{t}.png").exists()]
    assert not missing, f"缺少基线图：{missing}"
