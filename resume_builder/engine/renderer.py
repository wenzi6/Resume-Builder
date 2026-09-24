"""模板引擎：Jinja2 渲染 + 设计令牌注入 + 区块组装。"""
from __future__ import annotations

import html as _html
import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import FONTS_DIR, TEMPLATES_DIR
from ..schema import DEFAULT_DESIGN, normalize_design, normalize_document
from . import sections as sec_mod
from . import tokens, typo
from .base_css import base_css
# 版式族 -> 布局容器类
LAYOUT_CLASSES = {
    "single": "layout-single",
    "sidebar-left": "layout-sidebar-left",
    "sidebar-right": "layout-sidebar-right",
    "header-band": "layout-header-band",
    "timeline": "layout-timeline",
}


# ---------------------------------------------------------------- 模板扫描

def _load_template_meta(template_dir: Path) -> dict[str, Any] | None:
    cfg = template_dir / "template.json"
    if not cfg.exists():
        return None
    try:
        meta = json.loads(cfg.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(meta, dict):
        return None
    meta["id"] = template_dir.name
    return meta


def list_templates() -> list[dict[str, Any]]:
    """扫描模板目录，返回元信息列表（含默认设计参数）。"""
    out = []
    if not TEMPLATES_DIR.exists():
        return out
    for d in sorted(TEMPLATES_DIR.iterdir()):
        if not d.is_dir():
            continue
        meta = _load_template_meta(d)
        if not meta:
            continue
        layout_file = d / "layout.html"
        if not layout_file.exists():
            continue
        default_design = dict(DEFAULT_DESIGN)
        if isinstance(meta.get("defaultDesign"), dict):
            default_design.update(meta["defaultDesign"])
        out.append({
            "id": meta["id"],
            "name": meta.get("name") or meta["id"],
            "description": meta.get("description") or "",
            "author": meta.get("author") or "",
            "version": meta.get("version") or "1.0",
            "layout": meta.get("layout") or "single",
            "atsSafe": bool(meta.get("atsSafe")),
            "slots": meta.get("slots") or {},
            "defaultDesign": default_design,
        })
    return out


def get_template(template_id: str) -> dict[str, Any] | None:
    for t in list_templates():
        if t["id"] == template_id:
            return t
    return None


# ---------------------------------------------------------------- Jinja 环境

def _make_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    typo.register_filters(env)
    return env


_ENV: Environment | None = None


def _env() -> Environment:
    global _ENV
    if _ENV is None:
        _ENV = _make_env()
    return _ENV


# ---------------------------------------------------------------- 渲染

def _assign_slots(template: dict[str, Any], sections: list[dict]) -> list[dict]:
    """按模板 slot 配置给每个可见区块分配位置（top/sidebar/main）。"""
    slots = template.get("slots") or {}
    result = []
    for s in sections:
        if not s.get("visible", True):
            continue
        slot = "main"
        for name, keys in slots.items():
            if isinstance(keys, list) and s["key"] in keys:
                slot = name
                break
        result.append({**s, "slot": slot})
    return result


def render_body_html(doc: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
    """渲染所有区块，返回按 slot 分组的 HTML。"""
    design = normalize_design(doc.get("design"))
    content = doc.get("content") or {}
    sections = doc.get("sections") or []
    page_breaks = set(doc.get("pageBreaks") or [])

    assigned = _assign_slots(template, sections)

    grouped: dict[str, list[str]] = {"top": [], "sidebar": [], "main": []}
    for s in assigned:
        body = sec_mod.render_section(s, content, design)
        if not body:
            continue
        if s["key"] in page_breaks:
            body = f'<div class="r-pagebreak" data-before="{_html.escape(s["key"])}"></div>' + body
        grouped.setdefault(s["slot"], []).append(body)

    return {
        "design": design,
        "top": "".join(grouped.get("top", [])),
        "sidebar": "".join(grouped.get("sidebar", [])),
        "main": "".join(grouped.get("main", [])),
        "sections": assigned,
        "profile": content.get("profile") if isinstance(content.get("profile"), dict) else {},
    }


def _font_base(mode: str) -> str:
    """字体基地址：预览走 HTTP 路由，PDF 走 file:// 绝对路径。"""
    if mode == "pdf":
        posix = FONTS_DIR.as_posix()
        return f"file:///{posix.lstrip('/')}"
    return "/fonts"


def render_html(doc: dict[str, Any], mode: str = "preview") -> str:
    """渲染完整 HTML 文档。

    mode: 'preview'（HTTP 预览，字体走 /fonts 路由）
          'pdf'（写入磁盘供 Playwright 打开，字体走 file:// 绝对路径）
    """
    doc = normalize_document(doc)
    all_templates = list_templates()
    template = get_template(doc["templateId"])
    if template is None:
        # 未知模板：回退到第一个可用模板（而非崩溃）
        if not all_templates:
            raise RuntimeError("templates/ 目录下没有任何可用模板")
        template = all_templates[0]
        doc["templateId"] = template["id"]
    template_id = template["id"]
    design = normalize_design(doc.get("design"))

    ctx = render_body_html(doc, template)

    layout_class = LAYOUT_CLASSES.get(template["layout"], "layout-single")
    body_class = f"resume {layout_class} resume-{template_id} resume-font-{design['fontFamily']}"
    if design["dateAlign"] == "below":
        body_class += " resume-date-below"
    if design["compact"]:
        body_class += " resume-compact"

    tpl = _env().get_template(f"{template_id}/layout.html")
    inner = tpl.render(
        template=template,
        design=design,
        body_class=body_class,
        top_sections=ctx["top"],
        sidebar_sections=ctx["sidebar"],
        main_sections=ctx["main"],
        sections=ctx["sections"],
        profile=ctx["profile"],
        layout=template["layout"],
    )

    css_file = TEMPLATES_DIR / template_id / "layout.css"
    template_css = css_file.read_text(encoding="utf-8") if css_file.exists() else ""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{_html.escape(doc.get('title') or '简历')}</title>
<style>
{tokens.font_face_css(_font_base(mode))}
</style>
<style>
{tokens.page_css(design)}
</style>
<style>
{tokens.build_root_css(design)}
</style>
<style>
{base_css(design["pageMargin"])}
</style>
<style>
{template_css}
</style>
</head>
<body>
{inner}
</body>
</html>"""


def render_preview(doc: dict[str, Any]) -> str:
    return render_html(doc, mode="preview")


def render_for_pdf(doc: dict[str, Any]) -> str:
    return render_html(doc, mode="pdf")
