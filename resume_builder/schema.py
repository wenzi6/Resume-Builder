"""简历文档数据模型：默认值、归一化、校验、旧版(v1)迁移。

Document 结构见 docs/SPEC.md 第 4 节。所有对外数据都经过 normalize_document()
归一化，保证引擎拿到的形状稳定。
"""
from __future__ import annotations

import copy
import time
import uuid
from typing import Any

from . import registry
from .config import MAX_PAGE_MARGIN_MM, MIN_PAGE_MARGIN_MM

DOCUMENT_VERSION = 2

# 设计参数默认值（与 SPEC 5.1 一致）
DEFAULT_DESIGN: dict[str, Any] = {
    "fontFamily": "sans",       # sans | serif
    "fontScale": 1.0,           # 0.90 ~ 1.15
    "lineHeight": 1.45,         # 1.20 ~ 1.80
    "sectionGap": 18,           # px, 8 ~ 32
    "pageMargin": 20.0,         # mm, 12.7 ~ 25
    "accent": "#0f766e",
    "dateAlign": "right",       # right | below
    "showPhoto": False,
    "compact": False,
}

DESIGN_LIMITS = {
    "fontScale": (0.80, 1.15),   # 下限 0.80：一键适应一页的压缩阶梯需要（8.4pt 仍是可读下限）
    "lineHeight": (1.20, 1.80),
    "sectionGap": (8, 32),
    "pageMargin": (MIN_PAGE_MARGIN_MM, MAX_PAGE_MARGIN_MM),
}

# 一键压缩到一页时的参数（参照 Rezi Auto-Adjust / 超级简历一键排版）
COMPACT_DESIGN = {
    "fontScale": 0.94,
    "lineHeight": 1.32,
    "sectionGap": 12,
    "pageMargin": 15.0,
}


def _clamp(value: float, lo: float, hi: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, v))


def normalize_design(design: dict[str, Any] | None) -> dict[str, Any]:
    """把任意输入收敛为合法设计参数。"""
    d = copy.deepcopy(DEFAULT_DESIGN)
    if not isinstance(design, dict):
        return d
    for key in ("fontScale", "lineHeight", "sectionGap", "pageMargin"):
        if key in design:
            lo, hi = DESIGN_LIMITS[key]
            d[key] = round(_clamp(design[key], lo, hi), 3)
    if design.get("fontFamily") in ("sans", "serif"):
        d["fontFamily"] = design["fontFamily"]
    elif isinstance(design.get("fontFamily"), str) and design["fontFamily"]:
        # 用户上传的自有字体：家族名必须是已注册的
        from .services.font_manager import valid_families

        if design["fontFamily"] in valid_families():
            d["fontFamily"] = design["fontFamily"]
    if design.get("dateAlign") in ("right", "below"):
        d["dateAlign"] = design["dateAlign"]
    if isinstance(design.get("accent"), str) and _is_hex_color(design["accent"]):
        d["accent"] = design["accent"].lower()
    d["showPhoto"] = bool(design.get("showPhoto"))
    d["compact"] = bool(design.get("compact"))
    if d["compact"]:
        d.update({k: v for k, v in COMPACT_DESIGN.items()})
    return d


def _is_hex_color(s: str) -> bool:
    if not isinstance(s, str) or not s.startswith("#"):
        return False
    hexpart = s[1:]
    return len(hexpart) in (3, 6) and all(c in "0123456789abcdefABCDEF" for c in hexpart)


def default_sections() -> list[dict[str, Any]]:
    """默认区块配置：全部内置区块、默认顺序、全部可见。"""
    out = []
    for s in registry.builtin_section_defs():
        out.append({
            "key": s["key"],
            "title": s["title"],
            "type": s["type"],
            "fields": s["fields"],
            "visible": True,
        })
    return out


def empty_content() -> dict[str, Any]:
    """按注册表生成空 content 骨架。"""
    content: dict[str, Any] = {}
    for s in registry.BUILTIN_SECTIONS:
        t = s["type"]
        if t == "object":
            content[s["key"]] = {f["key"]: "" for f in s["fields"]}
        elif t == "array":
            content[s["key"]] = []
        elif t == "skills":
            content[s["key"]] = {"featuredSkills": [], "descriptions": []}
        else:  # simple
            content[s["key"]] = {"descriptions": []}
    return content


def new_document(template_id: str = "classic", title: str = "未命名简历") -> dict[str, Any]:
    now = time.time()
    return {
        "id": uuid.uuid4().hex,
        "title": title,
        "templateId": template_id,
        "design": copy.deepcopy(DEFAULT_DESIGN),
        "sections": default_sections(),
        "content": empty_content(),
        "pageBreaks": [],
        "version": DOCUMENT_VERSION,
        "createdAt": now,
        "updatedAt": now,
    }


# ---------- 归一化 ----------

def _norm_section(sec: Any) -> dict[str, Any] | None:
    if not isinstance(sec, dict):
        return None
    key = sec.get("key")
    if not isinstance(key, str) or not key:
        return None
    builtin = registry.section_def(key)
    if builtin:
        return {
            "key": key,
            "title": str(sec.get("title") or builtin["title"]),
            "type": builtin["type"],
            "fields": builtin["fields"],
            "visible": bool(sec.get("visible", True)),
        }
    # 自定义区块
    sec_type = sec.get("type") if sec.get("type") in ("array", "simple") else "array"
    fields = sec.get("fields")
    if not isinstance(fields, list):
        fields = registry.default_field_for(sec_type)
    fields = [f for f in fields if isinstance(f, dict) and f.get("key")]
    fields = [
        {
            "key": str(f["key"]),
            "label": str(f.get("label") or f["key"]),
            "type": f.get("type") if f.get("type") in ("text", "date", "textarea", "list") else "text",
        }
        for f in fields
    ]
    return {
        "key": key,
        "title": str(sec.get("title") or key),
        "type": sec_type,
        "fields": fields,
        "visible": bool(sec.get("visible", True)),
    }


def normalize_document(doc: Any) -> dict[str, Any]:
    """把外部输入归一化为完整合法的 Document。"""
    if not isinstance(doc, dict):
        doc = {}
    if doc.get("version") != DOCUMENT_VERSION and (doc.get("_sections") or "content" not in doc):
        doc = migrate_legacy(doc)

    out = new_document(template_id="classic")
    out["id"] = str(doc.get("id") or out["id"])
    out["title"] = str(doc.get("title") or "未命名简历")[:80]
    out["templateId"] = str(doc.get("templateId") or "classic")[:60]

    # sections：保留顺序；缺省的内置区块补在末尾；过滤不可见区块的可见性
    raw_sections = doc.get("sections")
    if isinstance(raw_sections, list) and raw_sections:
        sections = [s for s in (_norm_section(x) for x in raw_sections) if s]
    else:
        sections = default_sections()
    seen = {s["key"] for s in sections}
    for d in default_sections():
        if d["key"] not in seen:
            sections.append(d)
    out["sections"] = sections

    # content：按 sections 的形状收敛
    content = doc.get("content")
    out["content"] = _normalize_content(content if isinstance(content, dict) else {}, sections)

    # pageBreaks：合法化
    pb = doc.get("pageBreaks")
    keys = {s["key"] for s in sections}
    if isinstance(pb, list):
        out["pageBreaks"] = [str(x) for x in pb if isinstance(x, str) and x in keys]

    out["design"] = normalize_design(doc.get("design"))
    out["updatedAt"] = float(doc.get("updatedAt") or time.time())
    out["createdAt"] = float(doc.get("createdAt") or out["updatedAt"])
    return out


def _normalize_content(content: dict[str, Any], sections: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for sec in sections:
        key, sec_type = sec["key"], sec["type"]
        val = content.get(key)
        if sec_type == "object":
            obj = val if isinstance(val, dict) else {}
            out[key] = {f["key"]: _clean_scalar(obj.get(f["key"])) for f in sec["fields"]}
        elif sec_type == "array":
            items = val if isinstance(val, list) else []
            cleaned = []
            for item in items:
                if isinstance(item, dict):
                    cleaned.append({f["key"]: _clean_field(item.get(f["key"]), f.get("type"))
                                    for f in sec["fields"]})
                elif item not in (None, ""):
                    cleaned.append({sec["fields"][0]["key"] if sec["fields"] else "value": str(item)})
            out[key] = cleaned
        elif sec_type == "skills":
            obj = val if isinstance(val, dict) else {}
            featured = obj.get("featuredSkills")
            featured = featured if isinstance(featured, list) else []
            out[key] = {
                "featuredSkills": [
                    {"skill": _clean_scalar(fs.get("skill")),
                     "rating": int(_clamp(fs.get("rating", 0), 0, 5)) if str(fs.get("rating", "")).strip() else 0}
                    for fs in featured if isinstance(fs, dict)
                ],
                "descriptions": _as_str_list(obj.get("descriptions")),
            }
        else:  # simple
            if isinstance(val, dict):
                out[key] = {"descriptions": _as_str_list(val.get("descriptions"))}
            elif isinstance(val, list):
                out[key] = {"descriptions": _as_str_list(val)}
            else:
                out[key] = {"descriptions": _as_str_list(val)}
    return out


def _clean_scalar(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        return str(v)
    if not isinstance(v, str):
        v = str(v)
    return v.strip()


def _clean_field(v: Any, ftype: str | None) -> Any:
    if ftype == "list":
        return _as_str_list(v)
    return _clean_scalar(v)


def _as_str_list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if x not in (None, "") and str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [line.strip() for line in v.splitlines() if line.strip()]
    return []


# ---------- v1 迁移 ----------

def migrate_legacy(old: dict[str, Any]) -> dict[str, Any]:
    """把 v1 数据（_sections + 扁平 content）迁移到 v2 结构。"""
    old = old if isinstance(old, dict) else {}
    sections_cfg = old.get("_sections")
    content: dict[str, Any] = {}

    if isinstance(sections_cfg, list) and sections_cfg:
        sections = []
        for s in sections_cfg:
            norm = _norm_section(s)
            if norm:
                sections.append(norm)
        seen = {s["key"] for s in sections}
        for d in default_sections():
            if d["key"] not in seen:
                sections.append(d)
    else:
        sections = default_sections()

    # v1 的 content 就是顶层扁平字段
    for k, v in old.items():
        if k == "_sections":
            continue
        content[k] = v

    return {
        "id": old.get("id"),
        "title": old.get("title") or "导入的简历",
        "templateId": old.get("templateId") or "classic",
        "design": old.get("design") if isinstance(old.get("design"), dict) else None,
        "sections": sections,
        "content": content,
        "pageBreaks": old.get("pageBreaks") if isinstance(old.get("pageBreaks"), list) else [],
        "version": DOCUMENT_VERSION,
        "createdAt": old.get("createdAt"),
        "updatedAt": old.get("updatedAt"),
    }
