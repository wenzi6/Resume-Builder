"""一键「适应一页」：自动迭代压缩设计参数，直到页数 ≤ 1 或触底。

参照 Rezi Auto-Adjust / 超级简历一键排版的思路：优先保持可读性，
按「行距 → 字号 → 间距 → 边距」的顺序温和压缩，每步都经过真实测量。
"""
from __future__ import annotations

import copy
from typing import Any

from ..engine import pdf as pdf_engine
from ..schema import normalize_design

# 固定压缩阶梯（fontScale, lineHeight, sectionGap, pageMargin）
# 第一档即 compact 预设；最后一档触到 schema 的合法下限
LADDER: list[tuple[float, float, int, float]] = [
    (0.94, 1.32, 12, 15.0),
    (0.92, 1.28, 10, 14.0),
    (0.90, 1.25, 9, 13.5),
    (0.88, 1.25, 8, 13.0),
    (0.86, 1.22, 8, 12.7),
    (0.84, 1.22, 8, 12.7),
    (0.82, 1.20, 8, 12.7),
    (0.80, 1.20, 8, 12.7),
]

MAX_STEPS = 8


def _steps_from(design: dict[str, Any]) -> list[tuple[float, float, int, float]]:
    """生成从当前设计出发的压缩阶梯（只保留比当前更紧的档位）。"""
    cur = (design["fontScale"], design["lineHeight"], design["sectionGap"], design["pageMargin"])
    steps = [s for s in LADDER if s < cur]
    if steps:
        return steps[:MAX_STEPS]
    # 当前已经比阶梯更紧：从当前值继续往下探
    fs, lh, gap, m = cur
    steps = []
    for i in range(1, MAX_STEPS + 1):
        nxt = (
            max(0.80, round(fs - 0.02 * i, 3)),
            max(1.20, round(lh - 0.03 * i, 3)),
            max(8, int(gap - 2 * i)),
            max(12.7, round(m - 1.0 * i, 1)),
        )
        if nxt < cur and nxt not in steps:
            steps.append(nxt)
    return steps[:MAX_STEPS]


def fit_to_one_page(doc: dict[str, Any]) -> dict[str, Any]:
    """迭代压缩 doc.design 直到页数 ≤ 1。

    返回 {design, pageCount, fitted, steps, warnings}；不修改传入的 doc。
    """
    d = copy.deepcopy(doc)
    design = normalize_design(d.get("design"))
    d["design"] = design

    info = pdf_engine.measure_pages(d)
    if info["pageCount"] <= 1:
        return {
            "design": design,
            "pageCount": info["pageCount"],
            "fitted": True,
            "steps": 0,
            "warnings": info.get("warnings", []),
        }

    for i, (fs, lh, gap, margin) in enumerate(_steps_from(design), 1):
        design = normalize_design({
            **design,
            "fontScale": fs,
            "lineHeight": lh,
            "sectionGap": gap,
            "pageMargin": margin,
        })
        d["design"] = design
        info = pdf_engine.measure_pages(d)
        if info["pageCount"] <= 1:
            return {
                "design": design,
                "pageCount": info["pageCount"],
                "fitted": True,
                "steps": i,
                "warnings": info.get("warnings", []),
            }

    return {
        "design": design,
        "pageCount": info["pageCount"],
        "fitted": False,
        "steps": MAX_STEPS,
        "warnings": info.get("warnings", []) + ["已压缩到下限仍超出一页，建议删减内容或设置手动分页"],
    }
