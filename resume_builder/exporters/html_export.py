"""HTML 自包含导出：字体 base64 内嵌的单文件简历。

分享 / 存档用：不依赖服务端，双击即可在浏览器打开，打印设置里选 A4 即可。
"""
from __future__ import annotations

import base64
import re
from typing import Any

from ..config import FONTS_DIR
from ..engine.renderer import render_preview

# 匹配 @font-face 中的 url('/fonts/xxx') 或 url('file:///.../fonts/xxx')
_FONT_URL_RE = re.compile(r"url\('(?:/fonts/|file:///[^']*?/fonts/)([^']+)'\)")


def _font_data_uri(rel_path: str) -> str | None:
    p = FONTS_DIR / rel_path
    if not p.is_file():
        return None
    mime = "font/ttf" if p.suffix.lower() == ".ttf" else "font/otf"
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def export_html(doc: dict[str, Any]) -> bytes:
    """渲染并把字体内嵌为 data URI，返回单文件 HTML 字节流。"""
    html = render_preview(doc)

    def _sub(m: re.Match) -> str:
        data_uri = _font_data_uri(m.group(1))
        return f"url('{data_uri}')" if data_uri else m.group(0)

    html = _FONT_URL_RE.sub(_sub, html)
    return html.encode("utf-8")
