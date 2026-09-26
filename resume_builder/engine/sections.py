"""区块 -> 规范化 HTML。

所有模板共享同一套语义标记（.rsec/.ritem/.rlist/...），视觉差异完全由
模板 CSS 决定。这样保证：
  1. 六套模板的排版质量一致，不会出现某套模板漏掉某种内容；
  2. 打印/分页规则只需写一份（engine/print.css）；
  3. 自定义区块与内置区块走同一条渲染管线。
"""
from __future__ import annotations

import html
import re
from typing import Any

from . import typo

# ---------------------------------------------------------------- 图标
# 内联 SVG，currentColor 继承主题色；不需要图标的模板用 CSS 隐藏即可。

_ICONS = {
    "phone": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6A19.79 19.79 0 0 1 2.12 4.18 2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z"/></svg>',
    "mail": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 6L2 7"/></svg>',
    "location": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/></svg>',
    "user": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
    "calendar": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>',
    "coin": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 6v12M9.5 9.5h5M9.5 14.5h5"/></svg>',
}


def _icon(name: str) -> str:
    return f'<span class="r-ico">{_ICONS[name]}</span>'


def _esc(v: Any) -> str:
    """转义 + 排版清洗（盘古之白/空白压缩）。"""
    return html.escape(typo.tidy("" if v is None else str(v)))


def _clean(v: Any) -> bool:
    if v in (None, "", [], {}):
        return False
    if isinstance(v, str):
        return bool(v.strip())
    return True


def _is_empty(value: Any) -> bool:
    if value in (None, "", [], {}):
        return True
    if isinstance(value, dict):
        return not any(_clean(v) for v in value.values())
    if isinstance(value, list):
        return not any(_clean(v) for v in value)
    return not _clean(value)


def _list_html(items: Any, cls: str = "rlist") -> str:
    """列表字段 -> <ul>；空则返回空串。"""
    if isinstance(items, str):
        items = typo.split_lines(items)
    if not isinstance(items, list):
        return ""
    lis = []
    for it in items:
        txt = it.get("text") if isinstance(it, dict) else it
        txt = typo.tidy("" if txt is None else str(txt))
        if txt:
            lis.append(f"<li>{html.escape(txt)}</li>")
    return f'<ul class="{cls}">{"".join(lis)}</ul>' if lis else ""


# ---------------------------------------------------------------- 个人信息


def _safe_photo_src(src: str) -> bool:
    """照片地址只允许 http(s) 链接或站内 / 路径（防 file:// 等本地文件读取）。"""
    src = src.strip()
    if not src:
        return False
    if src.startswith(("http://", "https://")):
        return True
    if src.startswith("/") and not src.startswith("//") and ".." not in src:
        return True
    return False


def render_profile(section: dict, content: dict, design: dict) -> str:
    p = content.get("profile")
    if not isinstance(p, dict):
        return ""
    name = typo.tidy(str(p.get("name") or ""))
    if not name:
        return ""
    role = typo.tidy(str(p.get("title") or ""))

    # 联系信息：顺序固定，空值自动省略
    contacts = []
    for key, icon, label in (
        ("phone", "phone", ""), ("email", "mail", ""), ("location", "location", ""),
        ("age", "user", ""), ("gender", "user", ""),
        ("desiredSalary", "coin", "期望薪资 "), ("availableDate", "calendar", "到岗 "),
    ):
        val = typo.tidy(str(p.get(key) or ""))
        if val:
            contacts.append(
                f'<span class="r-contact">{_icon(icon)}'
                f'<span class="r-contact-t">{html.escape(label)}{html.escape(val)}</span></span>'
            )
    contact_html = f'<div class="r-contacts">{"".join(contacts)}</div>' if contacts else ""

    photo = ""
    photo_src = str(p.get("photo") or "").strip()
    if design.get("showPhoto") and _safe_photo_src(photo_src):
        src = html.escape(photo_src, quote=True)
        photo = f'<div class="r-photo"><img src="{src}" alt=""/></div>'

    summary_lines = typo.split_lines(str(p.get("summary") or ""))
    summary_html = ""
    if summary_lines:
        paras = "".join(f"<p>{_esc(ln)}</p>" for ln in summary_lines)
        summary_html = f'<div class="r-summary">{paras}</div>'

    return (
        '<section class="rsec rsec-profile" data-section="profile">'
        '<div class="r-profile">'
        '<div class="r-profile-text">'
        f'<h1 class="r-name">{_esc(name)}</h1>'
        + (f'<div class="r-role">{_esc(role)}</div>' if role else "")
        + contact_html
        + f"</div>{photo}</div>{summary_html}</section>"
    )


# ---------------------------------------------------------------- 列表型区块

_TITLE_FIELD_CANDIDATES = (
    "name", "company", "school", "project", "title",
    "certificate", "item", "organization",
)


def _title_field_of(section: dict) -> str | None:
    for f in section.get("fields", []):
        if isinstance(f, dict) and f.get("key") in _TITLE_FIELD_CANDIDATES:
            return f["key"]
    return None


def _sec_design(section: dict) -> dict:
    """区块级设计覆盖（columns / hideTitle）。"""
    d = section.get("design")
    return d if isinstance(d, dict) else {}


def _title_html(section: dict, key: str, default: str = "") -> str | None:
    """区块标题（hideTitle 时返回 None）。"""
    if _sec_design(section).get("hideTitle"):
        return None
    return f'<h2 class="rsec-title">{_esc(section.get("title") or default or key)}</h2>'


def render_array(section: dict, content: dict, design: dict) -> str:
    key = section["key"]
    items = content.get(key)
    if not isinstance(items, list) or not items:
        return ""

    fields = [f for f in section.get("fields", []) if isinstance(f, dict) and f.get("key")]
    if not fields:
        return ""
    title_field = _title_field_of(section)
    date_field = "date" if any(f.get("key") == "date" for f in fields) else None

    parts = []
    for item in items:
        if not isinstance(item, dict) or _is_empty(item):
            continue

        # --- 头部：主标题 + 副标题 + 日期
        title_html = ""
        if title_field:
            tv = typo.tidy(str(item.get(title_field) or ""))
            if tv:
                title_html = f'<span class="ritem-title">{_esc(tv)}</span>'

        sub_html = ""
        kv_rows = []
        lists = []
        sub_used = False
        for f in fields:
            fk = f["key"]
            if fk in (title_field, date_field):
                continue
            val = item.get(fk)
            if isinstance(val, list):
                lst = _list_html(val)
                if lst:
                    lists.append(lst)
                continue
            sv = typo.tidy("" if val is None else str(val))
            if not sv:
                continue
            if not sub_used:
                sub_html = f'<span class="ritem-sub">{_esc(sv)}</span>'
                sub_used = True
            else:
                label = str(f.get("label") or fk)
                kv_rows.append(
                    f'<div class="rkv"><span class="rkv-k">{_esc(label)}：</span>'
                    f'<span class="rkv-v">{_esc(sv)}</span></div>'
                )

        date_html = ""
        if date_field:
            dv = typo.normalize_date(str(item.get(date_field) or ""))
            if dv:
                date_html = f'<span class="ritem-date">{_esc(dv)}</span>'

        if not (title_html or sub_html or date_html or lists or kv_rows):
            continue

        # 成果：独立分组 + 标签（与职责描述区分开，简历不单调）
        ach = item.get("achievements")
        if isinstance(ach, list) and any(str(x).strip() for x in ach):
            ach_lst = _list_html(ach, cls="rlist rlist-ach")
            if ach_lst:
                lists.append(
                    '<div class="ritem-ach">'
                    '<span class="ritem-ach-label">成果</span>'
                    f'{ach_lst}</div>'
                )

        heading = f'<div class="ritem-heading">{title_html}{sub_html}</div>'
        head = f'<div class="ritem-head">{heading}{date_html}</div>'
        body = "".join(lists) + "".join(kv_rows)
        parts.append(f'<div class="ritem">{head}{body}</div>')

    if not parts:
        return ""
    title_html = _title_html(section, key)
    return (
        f'<section class="rsec" data-section="{html.escape(key)}">'
        f'{(title_html or "")}'
        f'<div class="rsec-body">{"".join(parts)}</div></section>'
    )


# ---------------------------------------------------------------- 技能


def render_free(section: dict, content: dict, design: dict) -> str:
    """自由大框：技能 / 自我评价 / 其他信息等文本型区块。

    不用星级行、不用标签 pill——一个带边框的文本块，每行一段，
    用户想怎么写就怎么写（技能名、熟练程度、整句描述都行）。
    """
    key = section["key"]
    val = content.get(key)
    if isinstance(val, dict):
        items = val.get("descriptions")
    elif isinstance(val, list):
        items = val
    elif val:
        items = typo.split_lines(str(val))
    else:
        items = []
    lines = [typo.tidy(str(x)) for x in (items or []) if str(x or "").strip()]
    lines = [x for x in lines if x]
    if not lines:
        return ""
    paras = "".join(f"<p>{_esc(x)}</p>" for x in lines)
    title_html = _title_html(section, key)
    return (
        f'<section class="rsec" data-section="{html.escape(key)}">'
        f'{(title_html or "")}'
        f'<div class="rsec-body"><div class="rfree">{paras}</div></div></section>'
    )


RENDERERS = {
    "array": render_array,
    "skills": render_free,
    "free": render_free,
    "simple": render_free,
}


def render_section(section: dict, content: dict, design: dict) -> str:
    """渲染单个区块；内容为空时返回空串（自然实现「一页」约束）。"""
    if section.get("key") == "profile":
        return render_profile(section, content, design)
    fn = RENDERERS.get(section.get("type", "array"), render_array)
    try:
        return fn(section, content, design)
    except Exception:
        return ""
