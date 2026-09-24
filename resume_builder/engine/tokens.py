"""设计令牌 -> CSS 变量。

模板只写「结构 + 版式」，所有可调参数（字体/字号/行距/间距/边距/主题色）
由这里统一生成 CSS 自定义属性，实现 SPEC 第 5.1 节的令牌体系。
"""
from __future__ import annotations

from typing import Any

from ..schema import DEFAULT_DESIGN, normalize_design

# 字体栈：内嵌 Noto 静态字体优先，回退到系统字体
FONT_SANS_STACK = "'Noto Sans SC', 'Microsoft YaHei', 'PingFang SC', 'Hiragino Sans GB', sans-serif"
FONT_SERIF_STACK = "'Noto Serif SC', 'SimSun', 'Songti SC', 'Source Han Serif SC', serif"

FONT_FILES = {
    "sans": [
        ("Noto Sans SC", 400, "NotoSansSC-Regular.ttf"),
        ("Noto Sans SC", 500, "NotoSansSC-Medium.ttf"),
        ("Noto Sans SC", 700, "NotoSansSC-Bold.ttf"),
    ],
    "serif": [
        ("Noto Serif SC", 400, "NotoSerifSC-Regular.ttf"),
        ("Noto Serif SC", 700, "NotoSerifSC-Bold.ttf"),
    ],
}


def font_face_css(base_url: str) -> str:
    """生成 @font-face 声明（内置 + 用户上传字体）。

    base_url 为字体目录的可访问基地址：
      - 预览模式（HTTP）：'/fonts'
      - PDF 模式（file://）：'file:///E:/.../fonts'
    """
    from ..services import font_manager

    entries = list(FONT_FILES["sans"] + FONT_FILES["serif"]) + font_manager.user_font_entries()
    rules = []
    for family, weight, filename in entries:
        rules.append(
            "@font-face {\n"
            f"  font-family: '{family}';\n"
            f"  src: url('{base_url}/{filename}') format('truetype');\n"
            f"  font-weight: {weight};\n"
            "  font-style: normal;\n"
            "  font-display: block;\n"
            "}"
        )
    return "\n".join(rules)


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return "#{:02x}{:02x}{:02x}".format(max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))


def mix(hex_a: str, hex_b: str, ratio: float) -> str:
    """按比例混合两个颜色，ratio 为 a 的权重。"""
    ra, ga, ba = _hex_to_rgb(hex_a)
    rb, gb, bb = _hex_to_rgb(hex_b)
    return _rgb_to_hex(
        round(ra * ratio + rb * (1 - ratio)),
        round(ga * ratio + gb * (1 - ratio)),
        round(ba * ratio + bb * (1 - ratio)),
    )


def _luminance(hex_c: str) -> float:
    r, g, b = (c / 255 for c in _hex_to_rgb(hex_c))

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def readable_on(hex_c: str) -> str:
    """返回在给定背景色上可读的前景色（黑或白）。"""
    return "#ffffff" if _luminance(hex_c) < 0.45 else "#1f2937"


def build_root_css(design: dict[str, Any] | None) -> str:
    """把设计参数编译为 :root CSS 变量块。"""
    d = normalize_design(design)
    scale = d["fontScale"]
    accent = d["accent"]

    # 派生色阶：主色的浅色底纹与深色变体
    accent_soft = mix(accent, "#ffffff", 0.10)
    accent_line = mix(accent, "#ffffff", 0.45)
    accent_deep = mix(accent, "#000000", 0.80)
    on_accent = readable_on(accent)

    body_font = FONT_SANS_STACK if d["fontFamily"] == "sans" else FONT_SERIF_STACK
    if d["fontFamily"] not in ("sans", "serif"):
        # 用户上传的自有字体：家族名直接作为正文字体栈（回退到内置黑体）
        body_font = f"'{d['fontFamily']}', 'Noto Sans SC', 'Microsoft YaHei', sans-serif"
    head_font = FONT_SANS_STACK  # 标题始终用黑体，保证层级清晰

    vars = {
        "--r-font-body": body_font,
        "--r-font-head": head_font,
        "--r-scale": f"{scale:.3f}",
        "--r-fs-body": f"calc(10.5pt * {scale:.3f})",
        "--r-fs-name": f"calc(17pt * {scale:.3f})",
        "--r-fs-h2": f"calc(12.5pt * {scale:.3f})",
        "--r-fs-h3": f"calc(11pt * {scale:.3f})",
        "--r-fs-small": f"calc(9.5pt * {scale:.3f})",
        "--r-fs-tiny": f"calc(8.5pt * {scale:.3f})",
        "--r-lh": f"{d['lineHeight']:.2f}",
        "--r-lh-tight": f"{min(d['lineHeight'], 1.25):.2f}",
        "--r-gap": f"{int(d['sectionGap'])}px",
        "--r-item-gap": f"{max(6, int(d['sectionGap'] * 0.55))}px",
        "--r-accent": accent,
        "--r-accent-soft": accent_soft,
        "--r-accent-line": accent_line,
        "--r-accent-deep": accent_deep,
        "--r-on-accent": on_accent,
        "--r-text": "#1f2937",
        "--r-text-soft": "#374151",
        "--r-text-mute": "#6b7280",
        "--r-line": "#e5e7eb",
        "--r-line-soft": "#f3f4f6",
        "--r-date-align": "flex-end" if d["dateAlign"] == "right" else "flex-start",
        "--r-margin": f"{d['pageMargin']:.1f}mm",
    }
    body = "\n".join(f"  {k}: {v};" for k, v in vars.items())
    return f":root {{\n{body}\n}}"


def page_css(design: dict[str, Any] | None) -> str:
    """@page 规则。边距用字面量（CSS 变量在 @page 中支持不稳定）。"""
    d = normalize_design(design)
    return (
        "@page {\n"
        "  size: A4;\n"
        f"  margin: {d['pageMargin']:.1f}mm;\n"
        "}"
    )
