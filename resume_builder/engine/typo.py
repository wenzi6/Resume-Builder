"""中文排版工具：盘古之白、日期归一化、文本清洗。

对应 SPEC 5.2 的中文排版规则。渲染期由 Jinja filter 调用，
保证所有用户输入的中西文混排、日期格式在全篇一致。
"""
from __future__ import annotations

import re

# CJK 统一表意文字 + 日文假名 + 韩文音节（与中文混排最相关的范围）
_CJK = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7a3\u3005\u3006"
_ALNUM = r"A-Za-z0-9"

# 中西文之间插入空格（盘古之白）；已有空格时不重复插入
_RE_CJK_ALNUM = re.compile(rf"(?<=[{_CJK}])(?=[{_ALNUM}])")
_RE_ALNUM_CJK = re.compile(rf"(?<=[{_ALNUM}])(?=[{_CJK}])")

# 日期中的 2021.03 -> 2021-03
_RE_DATE_DOT = re.compile(r"(\d{4})[./](\d{1,2})")
# 日期区间分隔符统一为 en dash
_RE_DATE_RANGE = re.compile(r"(\d{4}-\d{1,2})\s*[-–—~～]+\s*")


def panhu(text: str) -> str:
    """中西文/中文与数字之间加一个空格。"""
    if not isinstance(text, str) or not text:
        return ""
    text = _RE_CJK_ALNUM.sub(" ", text)
    text = _RE_ALNUM_CJK.sub(" ", text)
    return text


def normalize_date(text: str) -> str:
    """日期归一化：2021.03 - 至今 -> 2021-03 – 至今。"""
    if not isinstance(text, str):
        return ""
    s = text.strip()
    if not s:
        return ""
    s = _RE_DATE_DOT.sub(r"\1-\2", s)
    s = _RE_DATE_RANGE.sub(r"\1 – ", s)
    s = re.sub(r"\s*[–—]\s*", " – ", s)
    return s.strip(" –")


def tidy(text: str) -> str:
    """通用文本清洗：压缩空白 + 盘古之白。"""
    if not isinstance(text, str):
        return ""
    s = re.sub(r"[ \t]+", " ", text).strip()
    return panhu(s)


def split_lines(text: str) -> list[str]:
    """多行文本拆分为非空行列表。"""
    if not isinstance(text, str):
        return []
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def join_contact(parts: list[str], sep: str = " · ") -> str:
    """联系方式行拼接，过滤空值并统一分隔符。"""
    cleaned = [p for p in (tidy(x) for x in parts) if p]
    return sep.join(cleaned)


def register_filters(env) -> None:
    """把排版 filter 注册到 Jinja 环境。"""
    env.filters["panhu"] = panhu
    env.filters["ndate"] = normalize_date
    env.filters["tidy"] = tidy
    env.filters["lines"] = split_lines
    env.filters["contact"] = join_contact
