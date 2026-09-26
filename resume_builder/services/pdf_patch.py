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
    """
    old_map = flatten_content(old_content)
    new_map = flatten_content(new_content)
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
                changes.append({"path": path, "old": val, "new": None})
            elif nv != val:
                changes.append({"path": path, "old": val, "new": nv})
    for path, val in new_map.items():
        if not _is_item(path) and path not in old_map:
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
            if i not in keep_a:
                changes.append({"path": op, "old": ov, "new": None})
        for j, (_, np_, nv) in enumerate(new_items):
            if j not in keep_b:
                changes.append({"path": np_, "old": None, "new": nv})
    # 旧内容里没有、新内容里新增的列表
    for parent, new_items in new_groups.items():
        if parent in old_groups:
            continue
        for _, np_, nv in sorted(new_items):
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


def patch_pdf(source_rel: str, old_content: Any, new_content: Any,
              new_sections: list | None = None) -> dict[str, Any]:
    """把 new_content 相对 old_content 的改动应用到原始 PDF。

    返回 {data, applied:[{path}], failed:[{path, reason}], unchanged: bool}
    """
    import fitz

    src = config.DATA_DIR / source_rel
    if not src.is_file():
        raise FileNotFoundError(f"原始 PDF 不存在：{source_rel}")

    changes = diff_content(old_content, new_content)
    changes.extend(_section_changes(src, old_content, new_sections))
    original = src.read_bytes()
    if not changes:
        return {"data": original, "applied": [], "failed": [], "unchanged": True}

    doc = fitz.open(stream=original, filetype="pdf")
    applied: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for ch in changes:
        old_val, new_val, path = ch["old"], ch["new"], ch["path"]
        if old_val is None:
            failed.append({"path": path, "reason": "新增内容无法在原始版式中定位"})
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

    buf = doc.tobytes(deflate=True, garbage=3)
    doc.close()
    return {"data": buf, "applied": applied, "failed": failed, "unchanged": False}


def _is_pure_cjk(s: str) -> bool:
    """整段都是中文（等宽 advance，可按字符数比例估算水平范围）。"""
    return bool(s) and all("\u4e00" <= c <= "\u9fff" or c in "（）()·、" for c in s)


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
        # 删除：只 redact 受影响区间
        page.add_redact_annot(union)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
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
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
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
