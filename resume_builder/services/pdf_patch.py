"""原格式 PDF 导出：把模块编辑「打补丁」到原始 PDF 上。

设计目标（对照导入的闭环）：用户导入 PDF → 原格式保留 → 在旁边模块里改内容
→ 导出时**仍是原来的版式**，只有改动的文字被替换掉，未改动部分字节级不变。

实现：PyMuPDF 文本Span级替换——定位旧值所在 Span →  redact 该区域 →
按原字体字号颜色插回新文本（超宽自动缩字号）。删除了的内容只 redact 不插入。
无法定位的改动进入 warnings，由前端明确告知用户。
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from .. import config

# 与 services/pdf_import.norm_text 保持一致的轻量归一（保证能找到 Span）
_VARIANT_MAP_LEGACY = {
    "戶": "户", "戸": "户", "兒": "儿", "裏": "里", "喫": "吃", "傘": "伞",
    "畫": "画", "與": "与", "閱": "阅", "敵": "敌", "響": "响", "願": "愿",
    "顧": "顾", "體": "体", "實": "实", "寶": "宝", "術": "术", "網": "网",
    "統": "统", "錯": "错", "門": "门", "問": "问", "隊": "队", "際": "际",
    "驗": "验", "戰": "战", "稱": "称", "種": "种", "節": "节", "風": "风",
    "讀": "读", "變": "变", "萬": "万", "衆": "众",
}

# 归一化映射与导入侧保持一致（含 CJK 部首补充块），避免旧值在原始 PDF 中定位不到
from .pdf_import import VARIANT_MAP as _VARIANT_MAP

# 内置字体缓存（bold / regular 各一份，避免每次插字都加载 10MB TTF）
_FONT_CACHE: dict[str, Any] = {}

# 字号缩放下限（pt），低于此值认为放不下，进 warnings
MIN_FONT_SIZE = 5.0


def _norm(s: str) -> str:
    if not isinstance(s, str):
        return ""
    out = unicodedata.normalize("NFKC", s)
    for frm, to in _VARIANT_MAP.items():
        if frm in out:
            out = out.replace(frm, to)
    return re.sub(r"\s+", "", out)


# ---------------------------------------------------------------- content 展平


def flatten_content(content: Any) -> dict[str, str]:
    """把 content 展平为 {路径: 字符串值}（列表带序号）。"""
    out: dict[str, str] = {}

    def walk(v: Any, path: str) -> None:
        if isinstance(v, str):
            if v.strip():
                out[path] = v
        elif isinstance(v, list):
            for i, item in enumerate(v):
                walk(item, f"{path}.{i}")
        elif isinstance(v, dict):
            for k, item in v.items():
                if k in ("rating",):  # 数值型不参与文本替换
                    continue
                walk(item, f"{path}.{k}" if path else k)

    walk(content if isinstance(content, dict) else {}, "")
    return out


def _lcs_keep(a: list[str], b: list[str]) -> tuple[set[int], set[int]]:
    """最长公共子序列，返回 (a 中保留下来的下标, b 中保留下来的下标)。"""
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            dp[i][j] = (dp[i + 1][j + 1] + 1) if a[i] == b[j] else max(dp[i + 1][j], dp[i][j + 1])
    keep_a: set[int] = set()
    keep_b: set[int] = set()
    i = j = 0
    while i < n and j < m:
        if a[i] == b[j]:
            keep_a.add(i)
            keep_b.add(j)
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return keep_a, keep_b


def diff_content(old_content: Any, new_content: Any) -> list[dict[str, Any]]:
    """逐路径比较，返回 [{path, old, new}]；new=None 表示删除，old=None 表示新增。

    列表字段按**内容**比对：等长时按位置（纯编辑场景），长度变化时按公共子序列
    识别谁被删、谁被新增。直接按索引比较会把「删掉中间一条」误判成「后面所有
    条目都改了」，原格式补丁随之错位、大片失效。

    「移动」不算改动：同一条文本只是从 descriptions 挪到 achievements（或反之），
    对原始 PDF 而言文字仍在原处，补丁应保持原样——否则拆分成果模块会把
    原格式导出搅乱。
    """
    old_map = flatten_content(old_content)
    new_map = flatten_content(new_content)
    new_by_value: dict[str, set[str]] = {}
    for p, v in new_map.items():
        new_by_value.setdefault(v, set()).add(p)
    old_by_value: dict[str, set[str]] = {}
    for p, v in old_map.items():
        old_by_value.setdefault(v, set()).add(p)

    def _moved(old_val: str | None, path: str) -> bool:
        """该文本是否只是搬到了别的路径（原位内容未变）。"""
        if not old_val:
            return False
        paths = new_by_value.get(old_val)
        return bool(paths) and path not in paths

    def _relocated(new_val: str | None, path: str) -> bool:
        """「新增」的文本是否原本就在别处（从一个字段搬到了另一个字段）。"""
        if not new_val:
            return False
        paths = old_by_value.get(new_val)
        return bool(paths) and path not in paths

    changes: list[dict[str, Any]] = []

    def _is_item(path: str) -> bool:
        return path.rsplit(".", 1)[-1].isdigit()

    def _split(path: str) -> tuple[str, int]:
        parent, idx = path.rsplit(".", 1)
        return parent, int(idx)

    old_groups: dict[str, list[tuple[int, str, str]]] = {}
    new_groups: dict[str, list[tuple[int, str, str]]] = {}
    for path, val in old_map.items():
        if _is_item(path):
            parent, idx = _split(path)
            old_groups.setdefault(parent, []).append((idx, path, val))
        else:
            nv = new_map.get(path)
            if nv is None:
                if not _moved(val, path):
                    changes.append({"path": path, "old": val, "new": None})
            elif nv != val and not _moved(val, path):
                changes.append({"path": path, "old": val, "new": nv})
    for path, val in new_map.items():
        if not _is_item(path) and path not in old_map:
            if not _relocated(val, path):
                changes.append({"path": path, "old": None, "new": val})
        elif _is_item(path):
            parent, idx = _split(path)
            new_groups.setdefault(parent, []).append((idx, path, val))

    for parent, old_items in old_groups.items():
        old_items.sort()
        new_items = sorted(new_groups.get(parent, []))
        old_vals = [v for _, _, v in old_items]
        new_vals = [v for _, _, v in new_items]
        if len(old_vals) == len(new_vals):
            # 等长：按位置比较（用户只改了文字）
            for (_, op, ov), (_, np_, nv) in zip(old_items, new_items):
                if ov != nv:
                    changes.append({"path": op, "old": ov, "new": nv})
            continue
        # 长度变化：公共子序列之外的即为增/删
        keep_a, keep_b = _lcs_keep(old_vals, new_vals)
        for i, (_, op, ov) in enumerate(old_items):
            if i not in keep_a and not _moved(ov, op):
                changes.append({"path": op, "old": ov, "new": None})
        for j, (_, np_, nv) in enumerate(new_items):
            if j not in keep_b and not _relocated(nv, np_):
                changes.append({"path": np_, "old": None, "new": nv})
    # 旧内容里没有、新内容里新增的列表
    for parent, new_items in new_groups.items():
        if parent in old_groups:
            continue
        for _, np_, nv in sorted(new_items):
            if not _relocated(nv, np_):
                changes.append({"path": np_, "old": None, "new": nv})
    return changes


# ---------------------------------------------------------------- PDF 补丁


def _page_spans(page) -> list[dict[str, Any]]:
    """收集页面全部文本 Span（含几何与样式信息）。"""
    spans: list[dict[str, Any]] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span.get("text", "").strip():
                    spans.append(span)
    return spans


def _span_y(span) -> float:
    origin = span.get("origin")
    if origin and len(origin) == 2:
        return float(origin[1])
    return float(span["bbox"][3])


def _page_lines(page) -> list[dict[str, Any]]:
    """把 Span 按基线聚成视觉行。

    部分 PDF（尤其某些导出器生成的）把整行文本拆成逐字 Span，
    公司名/要点被切成单字，整串匹配必然失败——必须按行重组后再匹配。
    """
    spans = _page_spans(page)
    if not spans:
        return []
    rows: list[tuple[float, list]] = []
    for s in sorted(spans, key=lambda s: (round(_span_y(s), 1), float(s["bbox"][0]))):
        y = _span_y(s)
        if rows and abs(y - rows[-1][0]) <= 3:
            rows[-1][1].append(s)
        else:
            rows.append((y, [s]))
    lines = []
    for _, group in rows:
        group.sort(key=lambda s: float(s["bbox"][0]))
        lines.append({"spans": group, "text": "".join(s["text"] for s in group)})
    return lines


def fitz_rect(bbox):
    import fitz

    return fitz.Rect(bbox)


def _bullet_art_rects(page, line: dict, draws: list | None = None) -> list:
    """行首左侧的矢量圆点。

    很多 PDF 的列表标记是**画出来的**小圆圈（线条画），不是文字——它的 x 往往
    比该行文字更靠左，红选矩形只覆盖文字 span，于是删了内容只剩一个孤点。
    这里把行首左侧 24pt 内、垂直与行重叠、尺寸 ≤8pt 的填充图形找出来，
    一并纳入红选。draws 可传入整页 get_drawings() 结果（批量处理时避免逐行重扫）。
    """
    import fitz

    spans = line.get("spans") or []
    if not spans:
        return []
    y0 = min(float(s["bbox"][1]) for s in spans)
    y1 = max(float(s["bbox"][3]) for s in spans)
    x0 = min(float(s["bbox"][0]) for s in spans)
    out: list = []
    if draws is None:
        try:
            draws = page.get_drawings()
        except Exception:  # noqa: BLE001
            return out
    for d in draws:
        r = d.get("rect")
        if r is None:
            continue
        if r.y1 < y0 - 1.5 or r.y0 > y1 + 1.5:
            continue                      # 垂直不与本行重叠
        if r.x1 > x0 + 1.5 or r.x0 < x0 - 26:
            continue                      # 不在行首左侧邻近范围
        if r.width > 8 or r.height > 8:
            continue                      # 不是小圆点
        out.append(fitz.Rect(r))
    return out


def _apply_redactions(page, remove_line_art: bool = False) -> None:
    """执行 redact。

    remove_line_art=True 时把红选范围内的**矢量图形**（列表前的圆点常是画出来
    的小圆圈，不是文字）一并清掉——否则删了内容只剩一个孤零零的小点。
    """
    import fitz

    kwargs = {"images": fitz.PDF_REDACT_IMAGE_NONE}
    if remove_line_art:
        try:
            kwargs["graphics"] = fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED
        except AttributeError:  # pragma: no cover - 旧版 PyMuPDF 无此参数
            pass
    try:
        page.apply_redactions(**kwargs)
    except TypeError:  # pragma: no cover - 旧版签名不兼容时退回最小参数
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)


def _span_color(span) -> tuple[float, float, float]:
    color = span.get("color", 0)
    if isinstance(color, int):
        return ((color >> 16) & 255) / 255, ((color >> 8) & 255) / 255, (color & 255) / 255
    if isinstance(color, (list, tuple)) and len(color) >= 3:
        return tuple(float(c) for c in color[:3])
    return 0.0, 0.0, 0.0


def _span_baseline(span) -> tuple[float, float]:
    origin = span.get("origin")
    if origin and len(origin) == 2:
        return float(origin[0]), float(origin[1])
    bbox = span["bbox"]
    return float(bbox[0]), float(bbox[3]) - float(bbox[3] - bbox[1]) * 0.22


_INK_CACHE: dict[tuple, float] = {}


def _ink_ratio(pix) -> float:
    """墨迹占比：先裁剪到墨迹外框，再算框内黑像素比例（跨字体可比）。"""
    w, h, samples = pix.width, pix.height, pix.samples
    if w <= 0 or h <= 0 or len(samples) < w * h:
        return 0.0
    minx, miny, maxx, maxy, dark = w, h, -1, -1, 0
    for y in range(h):
        base = y * w
        for x in range(w):
            if samples[base + x] < 128:
                dark += 1
                if x < minx:
                    minx = x
                if x > maxx:
                    maxx = x
                if y < miny:
                    miny = y
                if y > maxy:
                    maxy = y
    if maxx < minx or maxy < miny:
        return 0.0
    box = (maxx - minx + 1) * (maxy - miny + 1)
    return dark / box


def _span_ink_ratio(page, span) -> float:
    """渲染原 span 区域，返回墨迹密度（粗体显著高于常规）。"""
    import fitz

    clip = fitz.Rect(span["bbox"])
    if clip.is_empty or clip.width <= 1 or clip.height <= 1:
        return 0.0
    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(4, 4), clip=clip, colorspace=fitz.csGRAY)
    except Exception:  # noqa: BLE001 渲染失败不阻塞补丁
        return 0.0
    return _ink_ratio(pix)


def _glyph_ink_ratio(font, ch: str, size: float) -> float:
    """渲染内置字体的单个字符，返回墨迹密度（作粗细基准，按字符缓存）。"""
    import fitz

    key = (id(font), ch, round(size, 1))
    if key in _INK_CACHE:
        return _INK_CACHE[key]
    try:
        w = max(8, int(font.text_length(ch, fontsize=size)) + 8)
        h = int(size * 2.2) + 8
        d = fitz.open()
        pg = d.new_page(width=w, height=h)
        tw = fitz.TextWriter(pg.rect)
        tw.append((4, size + 3), ch, font=font, fontsize=size)
        tw.write_text(pg, color=(0, 0, 0))
        pix = pg.get_pixmap(matrix=fitz.Matrix(4, 4), colorspace=fitz.csGRAY)
        ratio = _ink_ratio(pix)
        d.close()
    except Exception:  # noqa: BLE001
        ratio = 0.0
    _INK_CACHE[key] = ratio
    return ratio


def _detect_bold(page, span) -> bool:
    """判断原 span 是否粗体。

    常规 PDF 看字体名/flags；Type3（每字一字体）两者都不可信，
    改用墨迹密度与原文字形对比内置 Regular 同字符——更重即粗体。
    """
    font_name = (span.get("font") or "").lower()
    if "bold" in font_name or "heavy" in font_name or "black" in font_name:
        return True
    if span.get("flags", 0) & 16:
        return True
    if "type3" in font_name or not font_name:
        orig = _span_ink_ratio(page, span)
        if orig <= 0.02:
            return False
        ch = next((c for c in span.get("text", "") if not c.isspace()), "")
        if not ch:
            return False
        ref_font = _load_font(False)
        if ref_font is None:
            return False
        ref = _glyph_ink_ratio(ref_font, ch, float(span.get("size") or 10.0))
        return ref > 0 and orig > ref * 1.2
    return False


def _load_font(bold: bool):
    """加载内置 Noto Sans SC（与模板排版同一套字体，视觉最接近原 PDF 的黑体）。"""
    import fitz

    key = "bold" if bold else "regular"
    if key not in _FONT_CACHE:
        name = "NotoSansSC-Bold.ttf" if bold else "NotoSansSC-Regular.ttf"
        path = config.FONTS_DIR / name
        if not path.is_file():
            _FONT_CACHE[key] = None
        else:
            _FONT_CACHE[key] = fitz.Font(fontfile=str(path))
    return _FONT_CACHE[key]


def _insert_text(page, point, text, size, color, bold: bool, font=None) -> None:
    """原位插入文本。优先用内置 Noto Sans SC（保持与原文黑体一致的观感）；
    字体缺失时退回 PyMuPDF 内置字体。"""
    import fitz

    if font is not None:
        tw = fitz.TextWriter(page.rect)
        tw.append(point, text, font=font, fontsize=size)
        tw.write_text(page, color=color)
        return
    fontname = "china-s" if re.search(r"[\u4e00-\u9fff]", text) else "helv"
    page.insert_text(point, text, fontsize=size, fontname=fontname, color=color)
    if bold:
        page.insert_text((point[0] + size * 0.03, point[1]), text,
                         fontsize=size, fontname=fontname, color=color)


def _pdf_section_titles(src_path) -> dict[str, str]:
    """识别原始 PDF 里各区块的标题文本（原格式补丁的「旧值」基准）。"""
    from .pdf_import import detect_section_titles, extract_pdf

    try:
        with open(src_path, "rb") as fh:
            extracted = extract_pdf(fh)
    except Exception:  # noqa: BLE001 识别失败就不做标题同步，不影响内容补丁
        return {}
    return detect_section_titles(extracted)


def _section_changes(src_path, old_content: Any, new_sections: list) -> list[dict[str, Any]]:
    """区块级别的改动：标题改名 / 隐藏标题 / 隐藏整个区块。

    这些信息不在 content 里（在 doc.sections），旧的补丁完全看不到——
    于是「改了区块名，原格式里还是旧名字」。
    """
    changes: list[dict[str, Any]] = []
    if not isinstance(new_sections, list) or not new_sections:
        return changes
    pdf_titles = _pdf_section_titles(src_path)
    if not pdf_titles:
        return changes
    for sec in new_sections:
        if not isinstance(sec, dict):
            continue
        key = sec.get("key")
        pdf_title = (pdf_titles.get(key) or "").strip()
        if not pdf_title:
            continue
        design = sec.get("design") or {}
        cur_title = (sec.get("title") or "").strip()
        if design.get("hideTitle"):
            changes.append({"path": f"sections.{key}.title", "old": pdf_title, "new": None})
        elif cur_title and cur_title != pdf_title:
            changes.append({"path": f"sections.{key}.title", "old": pdf_title, "new": cur_title})
        # 隐藏整个区块：内容一并移除（与模板预览「不可见」一致）
        if sec.get("visible") is False:
            for path, val in flatten_content({key: (old_content or {}).get(key)}).items():
                changes.append({"path": path, "old": val, "new": None})
    return changes


# ---------------------------------------------------------------- 列表标记样式（原格式）

# 行首圆点字符（独立 Span 才可精确红选；部分简历用文字圆点，部分是矢量画的小圆圈）
_TEXT_BULLET_CHARS = set("·•●○◦▪▫・‣∙-*–—")


def _bullet_style_of(section: dict | None, design: Any) -> tuple[str, str]:
    """生效的列表标记样式 (style, char)：区块级 > 全局 > 默认圆点。"""
    sec_d = (section or {}).get("design") if isinstance(section, dict) else None
    style = (sec_d or {}).get("bulletStyle") or (design or {}).get("bulletStyle") or "dot"
    if style not in ("dot", "dash", "arrow", "num", "none", "custom"):
        style = "dot"
    char = (sec_d or {}).get("bulletChar") or (design or {}).get("bulletChar") or "•"
    return style, str(char or "•")[:4]


def _bullet_style_requested(design: Any, new_sections: list | None) -> bool:
    """快速判定：全局或任一区块要求了非圆点样式。"""
    if _bullet_style_of(None, design)[0] != "dot":
        return True
    for s in (new_sections or []):
        if isinstance(s, dict) and _bullet_style_of(s, design)[0] != "dot":
            return True
    return False


def _line_bullet(page, line: dict, draws: list | None = None):
    """识别行首列表标记。返回 ("text", span) / ("art", [rect]) / None。

    只处理「圆点是独立 Span」或「矢量小圆点」两种干净情况；圆点与正文
    挤在同一 Span 里时红选宽度估不准，宁保持原样也不画歪。
    """
    spans = line.get("spans") or []
    if not spans:
        return None
    first_txt = (spans[0].get("text") or "").strip()
    if first_txt and len(first_txt) <= 2 and all(c in _TEXT_BULLET_CHARS for c in first_txt):
        if len(spans) < 2:
            return None          # 行里只剩标记（内容已删），交给孤立圆点清理
        return ("text", spans[0])
    arts = _bullet_art_rects(page, line, draws)
    if arts:
        return ("art", arts)
    return None


def _apply_bullet_style(doc, design: Any, new_sections: list | None) -> dict:
    """把「设计 → 列表标记」打进原始 PDF：原格式预览与原格式导出同步生效。

    只动「生效样式 ≠ 圆点(dot)」的行——dot 就是导入时的原貌，不动才是
    无扰动（返回字节与原文一致，预览 digest 不抖）。编号(num)按连续
    bullet 行分块、从 1 重新计数：每条经历的职责列表各自 1. 2. 3.；
    标题行/非 bullet 行都会重置计数。放不下编号的行（列宽不足）保持原样。
    返回 {"styled": 替换数, "skipped": 放弃数}。
    """
    import fitz

    if not _bullet_style_requested(design, new_sections):
        return {"styled": 0, "skipped": 0}

    sec_by_key: dict[str, dict] = {}
    title_list: list[tuple[str, str]] = []
    for s in (new_sections or []):
        if isinstance(s, dict) and s.get("key"):
            sec_by_key[s["key"]] = s
            t = _norm(s.get("title") or "")
            if t:
                title_list.append((t, s["key"]))

    styled = skipped = 0
    for page in doc:
        try:
            page_draws = page.get_drawings()
        except Exception:  # noqa: BLE001
            page_draws = []
        # 行归属：最近的上方标题行；标题之上（页首区）用全局样式
        cur_key = None
        counter = 0
        actions: list[tuple[str, Any, str, tuple | None]] = []
        for line in _page_lines(page):
            ln = _norm(line["text"])
            for t, k in title_list:
                if ln == t or (t in ln and len(ln) <= len(t) + 6):
                    cur_key = k
                    counter = 0
                    break
            marker = _line_bullet(page, line, page_draws)
            if marker is None:
                counter = 0
                continue
            sec = sec_by_key.get(cur_key) if cur_key else None
            style, char = _bullet_style_of(sec, design)
            if style == "dot":
                counter = 0
                continue
            if style == "num":
                counter += 1
                text = f"{counter}."
            elif style == "none":
                text = ""
            else:
                text = char
            if not text:
                actions.append(("none", marker, "", None))
                continue
            spans = line["spans"]
            kind, obj = marker
            content = spans[1] if kind == "text" else spans[0]
            x0 = float(obj["bbox"][0]) if kind == "text" else min(float(r.x0) for r in obj)
            _, base_y = _span_baseline(content)
            size = float(content.get("size") or 9)
            avail = float(content["bbox"][0]) - x0 - 1.0
            if avail < 2.5:
                skipped += 1
                continue
            bold = bool(content.get("flags", 0) & 16)
            font = _load_font(bold)
            fs, _over = _fit_size_readable(text, size, avail, font, floor=max(4.0, size * 0.6))
            color = _span_color(content)
            actions.append((style, marker, text, (x0, base_y, fs, color, font)))

        if not actions:
            continue
        for _, marker, _, _ in actions:
            kind, obj = marker
            if kind == "text":
                page.add_redact_annot(fitz_rect(obj["bbox"]))
            else:
                for r in obj:
                    page.add_redact_annot(r)
        _apply_redactions(page, remove_line_art=True)
        for _, _, text, paint in actions:
            if paint:
                _insert_text(page, (paint[0], paint[1]), text, paint[2], paint[3], False, font=paint[4])
            styled += 1
    return {"styled": styled, "skipped": skipped}


def _entry_anchor_candidates(content: Any, path: str, exclude: str = "") -> list[str]:
    """从新增路径推出「同一条目」里已有的文本候选，用于在 PDF 里定位插入点。

    例如新增 workExperiences.1.achievements.0 时，用第 1 段经历最后的
    一条 bullet、或公司名作为锚点。exclude 是新增值本身（不能拿它当锚点，
    它在 PDF 里还不存在）。返回多个候选，逐个尝试。
    """
    ex = str(exclude or "").strip()
    out: list[str] = []

    def _push(v):
        v = str(v or "").strip()
        if v and v != ex and v not in out:
            out.append(v)

    parts = str(path).split(".")
    if len(parts) >= 4 and parts[1].isdigit():
        sec, idx = parts[0], int(parts[1])
        items = (content or {}).get(sec) if isinstance(content, dict) else None
        if isinstance(items, list) and 0 <= idx < len(items) and isinstance(items[idx], dict):
            item = items[idx]
            for fk in ("descriptions", "achievements"):
                vals = [str(v).strip() for v in (item.get(fk) or []) if str(v).strip()]
                for v in reversed(vals):
                    _push(v)
            for fk in ("company", "project", "school", "name", "title"):
                _push(item.get(fk))
    if len(parts) >= 2 and isinstance(content, dict):
        val = content.get(parts[0])
        if isinstance(val, dict):
            vals = [str(v).strip() for v in (val.get("descriptions") or []) if str(v).strip()]
            for v in reversed(vals):
                _push(v)
    return out


def _append_new_line(doc, new_content: Any, path: str, new_val: str) -> tuple[bool, str, dict]:
    """把新增的一行插到对应条目块的最后一行之后。

    原格式 PDF 的版式是固定的，新内容只能见缝插针：锚点行与下一行之间
    放得下一行时才插入，否则明确告知（而不是静默丢弃）。
    """
    candidates = _entry_anchor_candidates(new_content, path, new_val)
    if not candidates:
        return False, "新增内容无法在原始版式中定位（找不到同行内容做参照）", {}

    for page in doc:
        lines = _page_lines(page)
        # 锚点可能被 PDF 换行拆开，用前缀匹配；取最后一次出现（条目末尾）
        hit_idx = -1
        for cand in candidates:
            probe = _norm(cand)[:12]
            if len(probe) < 4:
                continue
            for i, ln in enumerate(lines):
                if probe in _norm(ln["text"]):
                    hit_idx = i
            if hit_idx >= 0:
                break
        if hit_idx < 0:
            continue
        anchor = lines[hit_idx]
        spans = anchor["spans"]
        if not spans:
            continue
        first = spans[0]
        size = float(first.get("size") or 10.0)
        color = _span_color(first)
        bold = _detect_bold(page, first)
        ab = fitz_rect(first["bbox"])
        y0, y1 = ab.y0, ab.y1
        x = ab.x0
        # 下一行（同页）的顶部位置
        next_top = None
        for ln in lines[hit_idx + 1:]:
            b = fitz_rect(ln["spans"][0]["bbox"])
            if b.y0 > y1 - 1:
                next_top = b.y0
                break
        limit = float(page.rect.height) - 24
        if next_top is None:
            next_top = limit
        gap = next_top - y1
        need = size * 1.25
        baseline = y1 + size * 0.95
        pos = {
            "page": page.number,
            "x": round(x, 1),
            "y": round(baseline, 1),
            "size": round(size, 1),
            "pageW": round(float(page.rect.width), 1),
            "pageH": round(float(page.rect.height), 1),
        }
        if gap < need or baseline > limit:
            # 放不进原版式：把位置交给前端做覆盖层标注，用户仍能看到自己加的内容
            return False, "原版式没有空间，已在页面上标注", pos
        font = _load_font(bold)
        text = str(new_val or "").strip()
        if not text:
            return True, "", {}
        _insert_text(page, (x, baseline), text, size, color, bold, font)
        return True, "", {}
    return False, "新增内容无法在原始版式中定位", {}


def patch_pdf(source_rel: str, old_content: Any, new_content: Any,
              new_sections: list | None = None, design: Any = None) -> dict[str, Any]:
    """把 new_content 相对 old_content 的改动应用到原始 PDF。

    design 是当前文档的设计参数：列表标记（bulletStyle/bulletChar，全局或
    区块级）非默认圆点时，同步替换原 PDF 的行首标记（含数字编号）。
    返回 {data, applied:[{path}], failed:[{path, reason}], unchanged: bool}
    """
    import fitz

    src = config.DATA_DIR / source_rel
    if not src.is_file():
        raise FileNotFoundError(f"原始 PDF 不存在：{source_rel}")

    changes = diff_content(old_content, new_content)
    changes.extend(_section_changes(src, old_content, new_sections))
    original = src.read_bytes()
    style_requested = _bullet_style_requested(design, new_sections)
    if not changes and not style_requested:
        return {"data": original, "applied": [], "failed": [], "unchanged": True}

    doc = fitz.open(stream=original, filetype="pdf")
    applied: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    unplaced: list[dict[str, Any]] = []

    for ch in changes:
        old_val, new_val, path = ch["old"], ch["new"], ch["path"]
        if old_val is None:
            # 新增内容：尝试插到对应条目块的最后一行之后（有垂直空间时）
            ok, why, pos = _append_new_line(doc, new_content, path, new_val)
            if ok:
                applied.append({"path": path})
            else:
                failed.append({"path": path, "reason": why})
                if pos:
                    unplaced.append({"path": path, "text": str(new_val or "")[:120],
                                     "reason": why, **pos})
            continue

        target = _norm(old_val)
        if not target:
            continue
        hit = False
        for page in doc:
            for line in _page_lines(page):
                if target not in _norm(line["text"]):
                    continue
                # 在整行文本中定位原始片段（精确优先，归一化兜底）
                raw_old = old_val if old_val in line["text"] else _locate_raw(line["text"], old_val)
                if raw_old is None:
                    continue
                ok, warning = _replace_in_line(page, line, raw_old, new_val, path)
                if warning:
                    failed.append({"path": path, "reason": warning})
                if ok:
                    applied.append({"path": path})
                    hit = True
                break
            if hit:
                break
        if not hit and not any(f["path"] == path for f in failed):
            failed.append({"path": path, "reason": "未能在原始 PDF 中定位旧内容"})

    mres = _apply_bullet_style(doc, design, new_sections)
    if mres["styled"]:
        entry = {"path": "design.bulletStyle", "markers": mres["styled"]}
        if mres["skipped"]:
            entry["skipped"] = mres["skipped"]
        applied.append(entry)
    if not changes and not mres["styled"]:
        doc.close()
        return {"data": original, "applied": [], "failed": [], "unchanged": True}

    buf = doc.tobytes(deflate=True, garbage=3)
    doc.close()
    return {"data": buf, "applied": applied, "failed": failed,
            "unplaced": unplaced, "unchanged": False}


def _is_pure_cjk(s: str) -> bool:
    """整段都是中文（等宽 advance，可按字符数比例估算水平范围）。"""
    return bool(s) and all("\u4e00" <= c <= "\u9fff" or c in "（）()·、" for c in s)


# 常见标签：删除内容后行内只剩这些（含标点）就是孤立标签，应整行清除
_ORPHAN_LABEL_RE = re.compile(
    r"^[\s·•]*(?:工作内容|岗位职责|项目介绍|项目内容|主修课程|职责|内容|专业|学历|备注|描述|主要技能)"
    r"[：:]?[\s·•]*$"
)


# 行首的列表标记（· • – ▸ ◆ 等）
_BULLET_MARK_RE = re.compile(r"^[·•▪▫◦‧・⁃\-–—▸◆\s]+$")


def _only_label_left(remainder: str) -> bool:
    """删掉内容后，行里剩下的是否只是个标签（如「主修课程：」）或一个圆点。"""
    r = (remainder or "").strip()
    if not r:
        return True
    if _BULLET_MARK_RE.match(r):
        return True          # 只剩「· 」这类标记 → 等同于空，整行清除
    return bool(_ORPHAN_LABEL_RE.match(r))


def _right_clearance(page, line: dict, span_idx: int, from_x: float) -> tuple[float, bool]:
    """插入点右侧的可用宽度，以及右侧是否还有别的文字。

    返回 (可用宽度, 右侧是否有内容)。有内容时必须让路（可继续缩小）；
    没内容时是空白区，保持可读字号自然延展比缩成小字更好。
    """
    import fitz

    right = float(page.rect.width) - 30.0  # 页面右边距近似
    blocked = False
    for i, s in enumerate(line["spans"]):
        if i <= span_idx:
            continue
        x0 = float(s["bbox"][0])
        if x0 > from_x + 1.0:
            right = min(right, x0 - 4.0)
            blocked = True
            break
    return max(24.0, right - from_x), blocked


def _fit_size_readable(text: str, size: float, avail_w: float, font, floor: float) -> tuple[float, bool]:
    """在 [floor, size] 间找能容纳 text 的最大字号。

    返回 (字号, 是否仍超出可用宽度)。宁可略超宽也不无限缩小——
    缩到 5pt 这种小字比略微出界更影响观感。
    """
    if avail_w <= 0:
        return size, False
    if font is None:
        import fitz

        w = fitz.get_text_length(text, fontname="helv", fontsize=size)
        if w <= avail_w:
            return size, False
        return max(MIN_FONT_SIZE, size * avail_w / w), True
    fs = size
    while fs > floor and font.text_length(text, fontsize=fs) > avail_w:
        fs = round(fs - 0.2, 2)
    overflow = font.text_length(text, fontsize=fs) > avail_w
    return fs, overflow


def _replace_in_line(page, line: dict, raw_old: str, new_val, path: str):
    """在视觉行内替换 raw_old → new_val（跨 Span  redact + 原位重插）。

    返回 (是否成功, 警告信息或 None)。
    """
    import fitz

    spans = line["spans"]
    joined = line["text"]
    start = joined.find(raw_old)
    if start < 0:
        return False, None
    end = start + len(raw_old)

    # 每个 span 在整行文本中的字符区间
    offsets: list[tuple[int, int]] = []
    pos = 0
    for s in spans:
        offsets.append((pos, pos + len(s["text"])))
        pos += len(s["text"])
    affected = [i for i, (a, b) in enumerate(offsets) if a < end and b > start]
    if not affected:
        return False, None
    # 行首的列表标记（· • 等）是独立 Span，向左扩进去——否则删了内容只剩个圆点
    j = affected[0] - 1
    while j >= 0 and _BULLET_MARK_RE.match((spans[j].get("text") or "").strip()):
        affected.insert(0, j)
        j -= 1

    first, last = spans[affected[0]], spans[affected[-1]]
    seg_start, seg_end = offsets[affected[0]][0], offsets[affected[-1]][1]
    segment = joined[seg_start:seg_end]
    union = fitz.Rect(first["bbox"])
    for i in affected[1:]:
        union |= fitz.Rect(spans[i]["bbox"])
    color = _span_color(first)
    bold = _detect_bold(page, first)
    size = float(first.get("size") or 10.0)
    x, y = _span_baseline(first)

    if new_val is None:
        # 删除：只 redact 受影响区间；若行内只剩孤立标签（如「主修课程：」）则整行清除
        if _only_label_left(joined.replace(raw_old, "")):
            page.add_redact_annot(union)
            for s in spans:
                page.add_redact_annot(fitz.Rect(s["bbox"]))
        else:
            page.add_redact_annot(union)
        # 行首左侧的矢量圆点（不在文字 span 范围内）一并红选掉
        for r in _bullet_art_rects(page, line):
            page.add_redact_annot(r)
        _apply_redactions(page, remove_line_art=True)
        return True, None

    new_segment = segment.replace(raw_old, new_val)
    # 整行就是旧值（如公司名独占一行）→ 整段替换
    if _norm(joined) == _norm(raw_old):
        new_segment = new_val
    # 字体保真：用内置 Noto Sans SC（与原 PDF 黑体观感一致），按原 span 粗细选字重
    font = _load_font(bold)

    # 重绘范围：默认只覆盖受影响的 Span（逐字 Span 的 PDF 精确到单字）；
    # 若整行是一个 Span 且变化部分是纯中文，按字符数比例收窄，保住同行其他内容
    redact_rect = union
    insert_x = x
    if len(affected) == 1 and len(segment) > len(raw_old) and _is_pure_cjk(segment):
        sb = fitz.Rect(first["bbox"])
        prefix = segment.find(raw_old)
        if prefix >= 0:
            frac0 = prefix / len(segment)
            frac1 = (prefix + len(raw_old)) / len(segment)
            redact_rect = fitz.Rect(sb.x0 + sb.width * frac0, sb.y0,
                                    sb.x0 + sb.width * frac1, sb.y1)
            insert_x = redact_rect.x0
    # 右侧空间：有别的文字就要让路（可继续缩小），纯空白区则保持可读字号
    avail, blocked = _right_clearance(page, line, affected[-1], insert_x)
    floor = MIN_FONT_SIZE if blocked else max(7.5, size * 0.88)
    fit_size, overflow = _fit_size_readable(new_segment, size, avail, font, floor)
    page.add_redact_annot(redact_rect)
    _apply_redactions(page, remove_line_art=False)
    _insert_text(page, (insert_x, y), new_segment, fit_size, color, bold, font)
    if overflow:
        if blocked:
            return False, "新内容过长，原版式放不下"
        return True, (f"新内容比原文长，已保持 {fit_size:.1f}pt 可读字号"
                      f"（原 {size:.1f}pt），右侧为空白区故自然延展")
    if fit_size < size * 0.92:
        return True, f"字号缩至 {fit_size:.1f}pt 以适配原宽度"
    return True, None


def _locate_raw(span_text: str, old_val: str) -> str | None:
    """Span 文本中与 old_val 对应的原始片段（处理空格/全半角差异）。"""
    if old_val in span_text:
        return old_val
    # 去空格后在原文中找对应切片
    target = _norm(old_val)
    if not target:
        return None
    idx_map: list[int] = []  # 归一化索引 -> 原文索引
    norm_chars: list[str] = []
    for i, c in enumerate(span_text):
        if c.isspace():
            continue
        nc = unicodedata.normalize("NFKC", c)
        for cc in _VARIANT_MAP:
            nc = nc.replace(cc, _VARIANT_MAP[cc])
        norm_chars.append(nc)
        idx_map.append(i)
    joined = "".join(norm_chars)
    pos = joined.find(target)
    if pos < 0:
        return None
    start = idx_map[pos]
    end = idx_map[min(pos + len(target) - 1, len(idx_map) - 1)] + 1
    return span_text[start:end]
