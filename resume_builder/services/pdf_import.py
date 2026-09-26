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
    # CJK 部首补充块（U+2E80–U+2EF3）：部分 PDF 字体 ToUnicode 损坏，
    # 提取出部首码位而非汉字；NFKC 转不了这些，必须显式映射
    "⻓": "长", "⻅": "见", "⻢": "马", "⻛": "风", "⻔": "门", "⻋": "车",
    "⻙": "韦", "⻜": "飞", "⻝": "食", "⻘": "青", "⻥": "鱼", "⻦": "鸟",
    "⻧": "卤", "⻨": "麦", "⻩": "黄", "⻬": "齐", "⻣": "骨", "⻤": "鬼",
    "⻮": "齿", "⻶": "聿", "⻳": "龟", "⻷": "音", "⻺": "革", "⻻": "韋",
    "⻼": "韭", "⻽": "音", "⻾": "頁", "⻿": "風", "⼁": "丨",
}


def norm_text(s: str) -> str:
    """NFKC + 异体字/部首映射，保证中文正则可靠匹配。"""
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
                    "x1": round(w.get("x1", 0), 1),
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
        # 词间水平间距 > 4px 视为有间隔（还原「公司 职位」「电话 邮箱」的视觉分段）
        text = ""
        prev_x1 = None
        for w in line:
            if prev_x1 is not None and w["x0"] - prev_x1 > 4:
                text += " "
            text += w["text"]
            prev_x1 = w.get("x1", w["x0"])
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


def _join_wrapped(lines: list[str]) -> list[str]:
    """合并被 PDF 换行切碎的同一段话。

    判据：上一行没有结束标点、且下一行较短、不带条目符号——典型的中途换行。
    只用于自我评价/其他信息这类「段落」内容，列表型区块不适用。
    """
    out: list[str] = []
    for line in lines:
        if (out and len(out[-1]) >= 20 and len(line) <= 24
                and not re.match(r"^[·•\-\d（(]", line)
                and not re.search(r"[。！？；.!?;]$", out[-1])):
            out[-1] = out[-1] + line
        else:
            out.append(line)
    return out


def _match_section_title(line: str, bold: bool) -> str | None:
    """判断一行是否是区块标题，返回区块 key 或 None。

    光看关键词会误判：自我评价正文「具备IT招聘和技术岗位工作经验…」含「工作经验」，
    会被当成工作经历标题，把后面内容全切走。因此要求同时满足标题特征：
    整行短（≤16 字）、关键词在行首、或该行加粗/标题级——三者至少其一。
    """
    stripped = line.strip()
    if not stripped:
        return None
    for key, titles in SECTION_KEYWORDS:
        for t in titles:
            if t not in stripped:
                continue
            if len(stripped) <= 16 or stripped.startswith(t) or bold:
                return key
    return None


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
    # 邮箱必须用 ASCII 字符类且以字母开头：\w 会匹配汉字、数字开头会粘上前面的电话
    if m := re.search(r"[A-Za-z][A-Za-z0-9._%+-]*@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text):
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
    elif not resume["profile"]["location"]:
        # 无标签兜底：页眉区域找「××市××区」形态（限制在开头，避免误匹配正文）
        if m := re.search(r"([\u4e00-\u9fa5]{2,6}市[\u4e00-\u9fa5]{1,8}[区县]|[\u4e00-\u9fa5]{2,6}省[\u4e00-\u9fa5]{1,8}市)", text[:300]):
            resume["profile"]["location"] = m.group(1)

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

    # 4) 按区块关键词分块（同时保留每行的加粗标记，供「公司行/职位行」判别）
    if sections:
        raw = [
            (DECOR_RE.sub("", norm_text((s.get("text") or "").strip())),
             bool(s.get("bold") or s.get("is_title")))
            for s in sections
        ]
    else:
        raw = [(DECOR_RE.sub("", norm_text(l.strip())), False) for l in text.split("\n")]
    raw = [(t, b) for t, b in raw if t.strip()]
    buckets: dict[str, list[str]] = {k: [] for k, _ in SECTION_KEYWORDS}
    bucket_bold: dict[str, list[bool]] = {k: [] for k, _ in SECTION_KEYWORDS}
    buckets["other"] = []
    bucket_bold["other"] = []
    current = None
    for line, bold in raw:
        matched = _match_section_title(line, bold)
        if matched:
            current = matched
            continue
        if current:
            buckets[current].append(line)
            bucket_bold[current].append(bold)
        else:
            buckets["other"].append(line)
            bucket_bold["other"].append(bold)

    resume["workExperiences"] = _parse_work(buckets["workExperiences"], bucket_bold["workExperiences"])
    resume["projects"] = _parse_projects(buckets["projects"], bucket_bold["projects"])
    resume["educations"] = _parse_educations(buckets["educations"])

    skill_sentences = [s for s in buckets["skills"] if len(s) >= 2]
    resume["skills"]["featuredSkills"] = [
        {"skill": s, "rating": 3} for s in skill_sentences[:10]
    ]
    resume["skills"]["descriptions"] = skill_sentences[10:30]
    resume["selfEvaluation"]["descriptions"] = _join_wrapped(buckets["selfEvaluation"][:12])

    # 5) 兜底：未能归类的行放入「其他信息」
    leftovers = _join_wrapped([l for l in buckets["other"] if len(l) >= 4][:10])
    resume["custom"]["descriptions"] = leftovers

    return resume


JOB_TITLE_TAIL_RE = re.compile(
    r"((?:高级|资深|初级|初中级|实习)?[\u4e00-\u9fa5A-Za-z/+]{1,8}"
    r"(?:工程师|开发|专员|经理|主管|总监|设计师|架构师|分析师|顾问|助理|运营|测试|负责人|支持|专家|实习))$"
)

# 中文机构名后缀（公司拆分的最强信号）
ORG_SUFFIX_RE = re.compile(
    r"^(.*?(?:有限责任公司|公司|集团|中心|研究院|研究所|银行|大学|学院|学校|"
    r"事务所|工作室|事业部|部门|厂|店|医院|政府|协会))(.*)$"
)


def _split_company_title(rest: str) -> tuple[str, str]:
    """把「公司 职位」连行拆开。优先：空格 > 机构后缀 > 职位词后缀。"""
    # 去掉首尾残留的破折号 / 间隔号 / 空白（日期区间被拆掉后的残渣）
    rest = re.sub(r"^[\u2010-\u2015\-~–•·\s]+", "", rest)
    rest = re.sub(r"[\u2010-\u2015\-~–•·\s]+$", "", rest)
    parts = [p.strip() for p in re.split(r"[\s·•]+|(?<=[\u4e00-\u9fa5])(?=[A-Za-z])", rest) if p.strip()]
    # 只保留含中日韩文字或字母数字的片段（过滤纯标点残渣）
    parts = [p for p in parts if re.search(r"[\u4e00-\u9fa5A-Za-z0-9]", p)]
    if len(parts) >= 2 and all(len(p) <= 16 for p in parts[:2]):
        return parts[0], parts[1]
    if m := ORG_SUFFIX_RE.match(rest):
        org, title = m.group(1), m.group(2).strip()
        if title and len(org) >= 2:
            return org, title
    if tm := JOB_TITLE_TAIL_RE.search(rest):
        if tm.start() >= 2:
            return rest[:tm.start()], tm.group(1)
    return rest, ""


def _looks_like_job_title(s: str) -> bool:
    """像职位名（工程师/专员/经理…）。机构后缀优先判公司，避免「××支持中心」误判。"""
    s = (s or "").strip()
    if not s:
        return False
    if ORG_SUFFIX_RE.match(s):
        return False
    return bool(JOB_TITLE_TAIL_RE.search(s))


def _is_header_label(s: str) -> bool:
    """「工作内容：」「项目介绍：」这类标签行（加粗但不是条目头）。"""
    return bool(re.search(r"[：:]\s*$", s or ""))


def _parse_work(work_lines: list[str], bolds: list[bool] | None = None) -> list[dict]:
    """解析工作经历。

    版式规律（绝大多数简历）：**加粗行 = 公司+日期**，紧随的**非加粗短行 = 职位**，
    再往下是要点。早期版本把职位行误判成新公司，导致「职位跑到 company 字段」。
    bolds 与 work_lines 等长，标记每行是否加粗/标题级。
    """
    items, cur = [], None
    for idx, line in enumerate(work_lines):
        bold = bolds[idx] if bolds and idx < len(bolds) else None
        # 先把行内所有日期片段剔掉，避免「公司 职位 日期」连行时干扰拆分
        date_stripped = DATE_RE.sub(" ", line)
        date_stripped = re.sub(
            r"[\s]*[\u2010-\u2015\-~–]+[\s]*(?:20\d{2}[-~.]\d{2,4}|至今|今)", " ", date_stripped)
        rest = date_stripped.strip()
        title_like = _looks_like_job_title(rest)
        is_company_like = (
            re.fullmatch(r"[\u4e00-\u9fa5A-Za-z（）()&·]{2,16}", rest)
            and not VERB_START_RE.match(rest)
            and not title_like          # 职位行绝不当公司
            and len(work_lines) > 3
        )
        # 加粗的非标签、非职位短行：公司名独占一行且加粗的版式
        is_bold_header = (
            bold is True and rest and not title_like and not _is_header_label(rest)
            and len(rest) <= 30 and not VERB_START_RE.match(rest)
        )
        if DATE_RE.search(line) or is_company_like or is_bold_header:
            if cur:
                items.append(cur)
            cur = {"company": "", "jobTitle": "", "date": "", "descriptions": []}
            if dm := DATE_RE.search(line):
                cur["date"] = dm.group(0)
                # 日期区间尾巴（– 至今 / – 2021-02）拼回去
                tail = re.search(
                    r"[\u2010-\u2015\-~–]\s*(20\d{2}[-~.]\d{2,4}|至今|今)", line[dm.end():])
                if tail:
                    cur["date"] = f"{dm.group(0)} – {tail.group(1)}"
            company, title = _split_company_title(rest)
            cur["company"] = company
            cur["jobTitle"] = title
        elif cur:
            clean = LABEL_PREFIX_RE.sub("", line).strip()
            if clean:
                if (not cur["jobTitle"] and not cur["descriptions"]
                        and not DATE_RE.search(clean)
                        and re.fullmatch(r"[\u4e00-\u9fa5A-Za-z（）()·]{2,12}", clean)
                        and not VERB_START_RE.match(clean)):
                    # 头部区（公司/日期之后、要点之前）的短行 = 职位
                    cur["jobTitle"] = clean
                elif title_like and cur["descriptions"]:
                    # 上一条目已完整，这是新条目的职位行（公司缺失的版式）
                    items.append(cur)
                    cur = {"company": "", "jobTitle": clean, "date": "", "descriptions": []}
                else:
                    cur["descriptions"].append(clean)
        else:
            cur = {"company": "", "jobTitle": "", "date": "", "descriptions": [line]}
    if cur:
        items.append(cur)
    return [w for w in items if w["descriptions"] or w["company"] or w["jobTitle"]]


def _strip_dates(line: str) -> str:
    """去掉行内全部日期片段（含区间尾巴与孤立破折号），返回剩余文本。"""
    out = DATE_RE.sub(" ", line)
    out = re.sub(
        r"[\s]*[\u2010-\u2015\-~–]+[\s]*(?:20\d{2}[-~.]\d{2,4}|至今|今)", " ", out)
    # 丢掉纯破折号令牌（日期区间被拆掉后的残渣）
    out = " ".join(t for t in out.split() if not re.fullmatch(r"[\u2010-\u2015\-~–]+", t))
    return out.strip()


def _full_date(line: str) -> str:
    """取行内第一个完整日期（含区间尾巴）。"""
    if dm := DATE_RE.search(line):
        tail = re.search(
            r"[\u2010-\u2015\-~–]\s*(20\d{2}[-~.]\d{2,4}|至今|今)", line[dm.end():])
        if tail:
            return f"{dm.group(0)} – {tail.group(1)}"
        return dm.group(0)
    return ""


def _parse_projects(proj_lines: list[str], bolds: list[bool] | None = None) -> list[dict]:
    """解析项目经验。规律同工作经历：加粗行 = 项目名+日期，非加粗短行 = 角色。"""
    items, cur = [], None
    for idx, line in enumerate(proj_lines):
        bold = bolds[idx] if bolds and idx < len(bolds) else None
        rest = _strip_dates(line)
        title_like = _looks_like_job_title(rest)
        is_proj_name = (
            re.fullmatch(r"[\u4e00-\u9fa5A-Za-z0-9（）()&·\-]{2,30}", rest)
            and not ROLE_WORDS.match(rest)
            and not title_like           # 职位行不当项目名
            and not re.match(r"^(项目介绍|项目内容|岗位职责|工作内容|职责|成果|1\.|2\.|3\.)", rest)
            and not VERB_START_RE.match(rest)
        )
        is_bold_header = (
            bold is True and rest and not title_like and not _is_header_label(rest)
            and len(rest) <= 30 and not VERB_START_RE.match(rest)
            and not re.match(r"^(项目介绍|项目内容|岗位职责|工作内容|职责|成果)", rest)
        )
        if DATE_RE.search(line) or is_proj_name or is_bold_header:
            if cur:
                items.append(cur)
            cur = {"project": "", "jobTitle": "", "date": _full_date(line), "descriptions": []}
            if rest and len(rest) <= 24:
                cur["project"] = rest
                # 「项目名 角色」连行：按职位词拆出角色
                if tm := JOB_TITLE_TAIL_RE.search(rest):
                    if tm.start() >= 2:
                        cur["project"] = rest[:tm.start()]
                        cur["jobTitle"] = tm.group(1)
        elif cur:
            clean = LABEL_PREFIX_RE.sub("", line).strip()
            if clean:
                if (not cur["jobTitle"] and not cur["descriptions"]
                        and not DATE_RE.search(clean)
                        and (ROLE_WORDS.match(clean) or title_like
                             or re.fullmatch(r"[\u4e00-\u9fa5A-Za-z（）()·]{2,10}", clean))
                        and not VERB_START_RE.match(clean)):
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
            cur = {"school": "", "degree": "", "date": _full_date(line), "descriptions": []}
            rest = _strip_dates(line)
            # 「学校 学历·专业」连行：学校名通常以 大学/学院/学校/大学 结尾
            if m := re.match(r"^(.*?(?:大学|学院|学校|中学|高中|职校|职业技术学院))(.*)$", rest):
                cur["school"] = m.group(1)
                degree = m.group(2).strip(" ··、,，|-")
                if degree:
                    cur["degree"] = degree
            elif rest:
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
