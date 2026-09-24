"""PDF 简历导入：pdfplumber 提取 + 启发式结构化解析。

移植自 v1 前端 buildResumeFromPDF（legacy/editor_v1.js），改为服务端实现：
前端只上传文件，解析结果直接变成可编辑的 v2 文档。
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

# ---------------------------------------------------------------- 文本归一化

VARIANT_MAP = {
    "戶": "户", "戸": "户", "兒": "儿", "裏": "里", "喫": "吃", "傘": "伞",
    "畫": "画", "與": "与", "閱": "阅", "敵": "敌", "響": "响", "願": "愿",
    "顧": "顾", "體": "体", "實": "实", "寶": "宝", "術": "术", "網": "网",
    "統": "统", "錯": "错", "門": "门", "問": "问", "隊": "队", "際": "际",
    "驗": "验", "戰": "战", "稱": "称", "種": "种", "節": "节", "風": "风",
    "讀": "读", "變": "变", "萬": "万", "衆": "众",
}


def norm_text(s: str) -> str:
    """NFKC + 异体字映射，保证中文正则可靠匹配。"""
    if not isinstance(s, str):
        return s
    out = unicodedata.normalize("NFKC", s)
    for frm, to in VARIANT_MAP.items():
        if frm in out:
            out = out.replace(frm, to)
    return out


# ---------------------------------------------------------------- pdfplumber 提取


def extract_pdf(file_storage) -> dict[str, Any]:
    """从上传的 PDF 提取文本与字体结构。"""
    import pdfplumber

    result: dict[str, Any] = {"pages": [], "raw_text": "", "fonts": {}}
    font_map: dict[str, dict] = {}
    counter = 0

    with pdfplumber.open(file_storage) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            page_text = page.extract_text() or ""
            result["raw_text"] += page_text + "\n"
            words = page.extract_words(extra_attrs=["fontname", "size", "non_stroking_color"])
            page_words = []
            for w in words:
                font_key = w.get("fontname", "default")
                size = round(w.get("size", 0), 1)
                color = w.get("non_stroking_color")
                if isinstance(color, (list, tuple)) and len(color) >= 3:
                    color_hex = "#{:02x}{:02x}{:02x}".format(
                        *[int(c * 255) if c <= 1 else min(int(c), 255) for c in color[:3]]
                    )
                else:
                    color_hex = "#000000"
                font_parts = font_key.split("+")[-1] if "+" in font_key else font_key
                is_bold = "bold" in font_parts.lower()
                style_id = f"f{counter}"
                if style_id not in font_map:
                    counter += 1
                    font_map[style_id] = {
                        "name": font_key, "size": size,
                        "weight": "bold" if is_bold else "normal", "color": color_hex,
                    }
                page_words.append({
                    "text": w.get("text", ""),
                    "x0": round(w.get("x0", 0), 1),
                    "y0": round(w.get("top", 0), 1),
                    "size": size, "bold": is_bold,
                })
            result["pages"].append({"page": page_num, "words": page_words})

    result["fonts"] = font_map
    result["structure"] = _parse_structure(result)
    if result["structure"].get("sections"):
        result["raw_text"] = "\n".join(
            s["text"] for s in result["structure"]["sections"] if s.get("text")
        )
    return result


def _parse_structure(result: dict) -> dict:
    """按页分组、按 Y 坐标聚成行，识别标题行。"""
    lines = []
    for page in result.get("pages", []):
        words = page.get("words", [])
        if not words:
            continue
        current, last_y = [], None
        for w in sorted(words, key=lambda w: (w["y0"], w["x0"])):
            if last_y is None or abs(w["y0"] - last_y) < 6:
                current.append(w)
            else:
                if current:
                    lines.append(sorted(current, key=lambda x: x["x0"]))
                current = [w]
            last_y = w["y0"]
        if current:
            lines.append(sorted(current, key=lambda x: x["x0"]))

    sections = []
    for line in lines:
        text = "".join(w["text"] for w in line)
        max_size = max(w["size"] for w in line)
        is_bold = any(w["bold"] for w in line)
        sections.append({
            "text": text.strip(),
            "font_size": max_size,
            "bold": is_bold,
            "is_title": max_size >= 13 or is_bold,
        })
    return {"total_lines": len(sections), "sections": sections}


def count_pages(path) -> int:
    """探测 PDF 页数（pymupdf，轻量）。"""
    import pymupdf

    with pymupdf.open(str(path)) as pdf:
        return pdf.page_count


# ---------------------------------------------------------------- 结构化解析

JOB_RE = re.compile(r"(工程师|开发|设计|运营|专员|经理|助理|分析师|架构师|顾问|运维|总监|主管|讲师|编辑|会计|出纳|销售|客服|行政|人事|财务|法务|测试|算法|数据)")
HEADER_RE = re.compile(r"(技能|特长|工作经验|工作经历|项目经验|项目经历|教育背景|教育经历|自我评价|个人评价|自我评估|专业技能|RESUME)", re.I)
DATE_RE = re.compile(r"20\d{2}[-~.]\d{2,4}(?:\s*[-~]\s*(?:20\d{2}[-~.]\d{2,4}|至今|今))?")
DECOR_RE = re.compile(r"^[\s·•▪◦●○■□▶◆\-—]+")

SECTION_KEYWORDS = [
    ("workExperiences", ["工作经验", "工作经历", "工作内容"]),
    ("projects", ["项目经验", "项目经历"]),
    ("educations", ["教育背景", "教育经历", "教育"]),
    ("skills", ["技能特长", "专业技能", "技能"]),
    ("selfEvaluation", ["自我评价", "个人评价", "自我评估"]),
]

ROLE_WORDS = re.compile(
    r"^(安全服务工程师|安全运维工程师|网络安全工程师|技术支持|开发工程师|测试工程师|"
    r"产品经理|项目经理|蓝队|红队|队长|成员|前端工程师|后端工程师|全栈工程师)$"
)
VERB_START_RE = re.compile(r"^(跟进|负责|协助|参与|支持|配合|编写|针对|成果|岗位|工作内容|项目|对高|实时|前期)")
LABEL_PREFIX_RE = re.compile(r"^(工作内容|岗位职责|项目介绍|项目内容|职责|内容|主修课程|专业|学历)[：:]?")


def build_document_from_pdf(extracted: dict) -> dict:
    """把 pdfplumber 提取结果转换为 v2 简历文档。"""
    sections = extracted.get("structure", {}).get("sections", [])
    full_text = extracted.get("raw_text", "")
    text = norm_text(full_text)

    resume = {
        "profile": {k: "" for k in (
            "name", "title", "email", "phone", "location", "age", "gender",
            "desiredSalary", "availableDate", "photo", "summary")},
        "skills": {"featuredSkills": [], "descriptions": []},
        "workExperiences": [], "projects": [], "educations": [],
        "selfEvaluation": {"descriptions": []},
        "custom": {"descriptions": []},
    }

    # 1) 姓名：优先大字号 2-4 字纯汉字行
    big_lines = [
        s["text"].strip() for s in sections
        if s.get("font_size", 0) >= 14 and s.get("text")
        and 2 <= len(s["text"].strip()) <= 4
    ]
    name_candidates = [t for t in big_lines if re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", norm_text(t))]
    lines = [l for l in text.split("\n") if l.strip()]
    fallback_name = ""
    if lines:
        m = re.match(r"^[\u4e00-\u9fa5]{2,4}$", lines[0].strip())
        if m:
            fallback_name = m.group(0)
    resume["profile"]["name"] = norm_text(name_candidates[0]) if name_candidates else fallback_name

    # 2) 联系信息
    if m := re.search(r"1[3-9]\d{9}", text):
        resume["profile"]["phone"] = m.group(0)
    if m := re.search(r"[\w.-]+@[\w.-]+\.\w+", text):
        resume["profile"]["email"] = m.group(0)
    if m := re.search(r"年龄[：:]\s*(\d{1,2})\s*岁", text) or re.search(r"(\d{1,2})\s*岁", text):
        resume["profile"]["age"] = m.group(1)
    if m := re.search(r"性别[：:]\s*([男女])", text):
        resume["profile"]["gender"] = m.group(1)
    elif m := re.search(r"\d{1,2}\s*岁[：:]*\s*([男女])", text):
        resume["profile"]["gender"] = m.group(1)
    if m := re.search(r"(?:期望薪资|薪资|薪酬)[：:]\s*([^\s，,。；;]+)", text):
        resume["profile"]["desiredSalary"] = m.group(1).strip()
    if m := re.search(r"(?:到岗时间|可到岗|入职时间)[：:]\s*([^\s，,。；;]+)", text):
        resume["profile"]["availableDate"] = m.group(1).strip()
    if m := re.search(r"(?:现居|所在地|地址|城市)[：:]\s*([^\s，,。；;|]+)", text):
        resume["profile"]["location"] = m.group(1).strip()

    # 3) 求职意向
    title_line = ""
    for s in sections:
        t = norm_text(s.get("text") or "").strip()
        if not t or len(t) > 30 or HEADER_RE.search(t):
            continue
        if JOB_RE.search(t):
            title_line = t
            break
    if title_line:
        m = re.match(r"^(.*?)(?=面议|到岗|入职|薪资|薪酬|一周|随时|立即|尽快|$)", title_line)
        resume["profile"]["title"] = (m.group(1) if m else title_line).strip()
        if not resume["profile"]["desiredSalary"] and "面议" in title_line:
            resume["profile"]["desiredSalary"] = "面议"
        if not resume["profile"]["availableDate"]:
            if av := re.search(r"(一周内到岗|随时到岗|立即到岗|尽快到岗)", title_line):
                resume["profile"]["availableDate"] = av.group(1)

    # 4) 按区块关键词分块
    raw_lines = [DECOR_RE.sub("", norm_text(l.strip())) for l in text.split("\n") if l.strip()]
    buckets: dict[str, list[str]] = {k: [] for k, _ in SECTION_KEYWORDS}
    buckets["other"] = []
    current = None
    for line in raw_lines:
        matched = None
        for key, titles in SECTION_KEYWORDS:
            if any(t in line for t in titles):
                matched = key
                break
        if matched:
            current = matched
            continue
        if current:
            buckets[current].append(line)
        else:
            buckets["other"].append(line)

    resume["workExperiences"] = _parse_work(buckets["workExperiences"])
    resume["projects"] = _parse_projects(buckets["projects"])
    resume["educations"] = _parse_educations(buckets["educations"])

    skill_sentences = [s for s in buckets["skills"] if len(s) >= 2]
    resume["skills"]["featuredSkills"] = [
        {"skill": s, "rating": 3} for s in skill_sentences[:10]
    ]
    resume["skills"]["descriptions"] = skill_sentences[10:30]
    resume["selfEvaluation"]["descriptions"] = buckets["selfEvaluation"][:12]

    # 5) 兜底：未能归类的行放入「其他信息」
    leftovers = [l for l in buckets["other"] if len(l) >= 4][:10]
    resume["custom"]["descriptions"] = leftovers

    return resume


def _parse_work(work_lines: list[str]) -> list[dict]:
    items, cur = [], None
    for line in work_lines:
        is_company_like = (
            re.fullmatch(r"[\u4e00-\u9fa5A-Za-z（）()&·]{2,16}", line)
            and not VERB_START_RE.match(line)
            and len(work_lines) > 3
        )
        if DATE_RE.search(line) or is_company_like:
            if cur:
                items.append(cur)
            cur = {"company": "", "jobTitle": "", "date": "", "descriptions": []}
            if dm := DATE_RE.search(line):
                cur["date"] = dm.group(0)
            rest = line.replace(dm.group(0) if dm else "", "").strip()
            if rest and len(rest) <= 20:
                cur["company"] = rest
        elif cur:
            clean = LABEL_PREFIX_RE.sub("", line).strip()
            if clean:
                if (not cur["jobTitle"] and not DATE_RE.search(clean)
                        and re.fullmatch(r"[\u4e00-\u9fa5A-Za-z（）()·]{2,12}", clean)
                        and not VERB_START_RE.match(clean)):
                    cur["jobTitle"] = clean
                else:
                    cur["descriptions"].append(clean)
        else:
            cur = {"company": "", "jobTitle": "", "date": "", "descriptions": [line]}
    if cur:
        items.append(cur)
    return [w for w in items if w["descriptions"] or w["company"] or w["jobTitle"]]


def _parse_projects(proj_lines: list[str]) -> list[dict]:
    items, cur = [], None
    for line in proj_lines:
        is_proj_name = (
            re.fullmatch(r"[\u4e00-\u9fa5A-Za-z0-9（）()&·\-]{2,30}", line)
            and not ROLE_WORDS.match(line)
            and not re.match(r"^(项目介绍|项目内容|岗位职责|工作内容|职责|成果|1\.|2\.|3\.)", line)
            and not VERB_START_RE.match(line)
        )
        if DATE_RE.search(line) or is_proj_name:
            if cur:
                items.append(cur)
            cur = {"project": "", "jobTitle": "", "date": "", "descriptions": []}
            if dm := DATE_RE.search(line):
                cur["date"] = dm.group(0)
            rest = line.replace(dm.group(0) if dm else "", "").strip()
            if rest and len(rest) <= 24:
                cur["project"] = rest
        elif cur:
            clean = LABEL_PREFIX_RE.sub("", line).strip()
            if clean:
                if not cur["jobTitle"] and not DATE_RE.search(clean) and ROLE_WORDS.match(clean):
                    cur["jobTitle"] = clean
                else:
                    cur["descriptions"].append(clean)
        else:
            cur = {"project": line, "jobTitle": "", "date": "", "descriptions": []}
    if cur:
        items.append(cur)
    return [p for p in items if p["descriptions"] or p["project"] or p["jobTitle"]]


def _parse_educations(edu_lines: list[str]) -> list[dict]:
    items, cur = [], None
    for line in edu_lines:
        if re.search(r"20\d{2}[-~.]", line):
            if cur:
                items.append(cur)
            cur = {"school": "", "degree": "", "date": "", "descriptions": []}
            if dm := re.search(r"20\d{2}[-~.]\d{2,4}(?:\s*[-~]\s*(?:20\d{2}[-~.]\d{2,4}|至今))?", line):
                cur["date"] = dm.group(0)
            rest = line.replace(dm.group(0) if dm else "", "").strip()
            if rest:
                cur["school"] = rest
        elif cur:
            d = LABEL_PREFIX_RE.sub("", line).strip()
            if d and not cur["degree"]:
                cur["degree"] = d
            elif d:
                cur["descriptions"].append(d)
        else:
            cur = {"school": line, "degree": "", "date": "", "descriptions": []}
    if cur:
        items.append(cur)
    return items
