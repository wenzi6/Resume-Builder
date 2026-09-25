"""JD 关键词匹配 / ATS 检查（纯本地，不依赖 LLM）。

与 AI 的「JD 定制」互补：零成本、离线可用、结果确定。
流程：从 JD 提取分类关键词（硬技能 / 教育 / 职位 / 软技能）→ 按权重
与简历全文比对 → 匹配率 + 缺失关键词 + 针对性建议。
"""
from __future__ import annotations

import re
from typing import Any

# ---- 关键词词典（中文简历高频项，按类别）----
HARD_SKILLS = [
    # 编程语言
    "Java", "Python", "C++", "C语言", "Go", "Golang", "JavaScript", "TypeScript", "PHP", "Ruby", "Swift", "Kotlin", "Rust", "Scala", "MATLAB", "R语言",
    # 前端
    "React", "Vue", "Angular", "jQuery", "Webpack", "Vite", "Node.js", "Next.js", "Nuxt", "小程序", "Flutter", "React Native", "Electron", "HTML", "CSS", "Sass", "Less", "Tailwind",
    # 后端 / 架构
    "Spring", "SpringBoot", "Spring Cloud", "SpringBoot", "Django", "Flask", "FastAPI", "Express", "NestJS", "微服务", "分布式", "高并发", "高可用", "负载均衡", "缓存", "Redis", "消息队列", "Kafka", "RabbitMQ", "RocketMQ", "gRPC", "Dubbo",
    # 数据 / AI
    "MySQL", "PostgreSQL", "Oracle", "SQLServer", "MongoDB", "Elasticsearch", "ES", "ClickHouse", "Hive", "Spark", "Flink", "Hadoop", "数据仓库", "ETL", "数据建模", "机器学习", "深度学习", "TensorFlow", "PyTorch", "Keras", "NLP", "CV", "计算机视觉", "推荐算法", "大模型", "LLM", "AIGC", "Prompt",
    # 运维 / 云
    "Linux", "Docker", "Kubernetes", "K8s", "DevOps", "CI/CD", "Jenkins", "GitLab CI", "Git", "SVN", "Nginx", "Apache", "Tomcat", "AWS", "Azure", "GCP", "阿里云", "腾讯云", "华为云", "KVM", "OpenStack", "Shell", "Ansible", "Prometheus", "Grafana", "监控", "告警",
    # 安全
    "网络安全", "信息安全", "渗透测试", "漏洞挖掘", "逆向", "安全审计", "等保", "WAF", "IDS", "IPS", "SOC", "安全运营", "应急响应", "SDL",
    # 测试 / 产品 / 运营 / 设计
    "自动化测试", "测试开发", "Selenium", "Appium", "JMeter", "LoadRunner", "Pytest", "JUnit", "单元测试", "性能测试", "接口测试",
    "Axure", "Sketch", "Figma", "Photoshop", "PS", "Illustrator", "AI制图", "UI设计", "交互设计", "用户体验", "需求分析", "原型设计", "PRD", "MRD",
    "SEO", "SEM", "新媒体运营", "内容运营", "用户运营", "活动运营", "数据分析", "增长", "投放", "ROI", "GMV", "DAU", "MAU",
    # 办公 / 通用技能
    "Excel", "Word", "PPT", "PowerPoint", "SPSS", "SAS", "Tableau", "PowerBI", "CRM", "ERP", "SAP", "用友", "金蝶",
    "PMP", "ACP", "软考", "CPA", "CFA", "法律职业资格", "教师资格证", "英语六级", "CET-6", "CET-4", "雅思", "托福",
]

EDUCATION_TERMS = ["本科", "硕士", "博士", "大专", "专科", "学历", "学位", "全日制", "统招", "211", "985", "双一流", "计算机科学与技术", "软件工程", "信息安全", "通信工程", "电子工程", "自动化", "数学", "统计学", "人工智能"]

POSITION_TERMS = [
    "前端", "后端", "全栈", "客户端", "移动端", "测试", "运维", "算法", "数据", "数据分析", "数据挖掘",
    "产品", "产品经理", "运营", "设计", "UI", "交互", "项目经理", "架构师", "总监", "主管", "工程师",
    "开发", "研发", "安全", "渗透", "销售", "市场", "人事", "行政", "财务", "会计", "法务", "客服",
]

SOFT_SKILLS = [
    "沟通", "表达能力", "团队协作", "协作", "团队合作", "学习能力", "抗压", "责任心", "主动性", "创新",
    "逻辑思维", "分析能力", "解决问题", "执行力", "领导力", "管理能力", "英语", "中文", "文档能力",
]

# 权重：硬技能 > 教育/职位 > 软技能
WEIGHTS = {"skill": 3, "education": 2, "position": 2, "soft": 1}


def _normalize(text: str) -> str:
    """归一化：小写 + 去空白（英文大小写/空格不敏感匹配）。"""
    return re.sub(r"\s+", "", (text or "").lower())


def extract_keywords(jd: str) -> dict[str, list[str]]:
    """从 JD 提取分类关键词（去重、保持出现顺序）。"""
    jd_norm = _normalize(jd)
    if not jd_norm:
        return {"skill": [], "education": [], "position": [], "soft": []}

    def pick(terms):
        found = []
        for t in terms:
            if _normalize(t) in jd_norm and t not in found:
                found.append(t)
        return found

    return {
        "skill": pick(HARD_SKILLS),
        "education": pick(EDUCATION_TERMS),
        "position": pick(POSITION_TERMS),
        "soft": pick(SOFT_SKILLS),
    }


def _flatten_document(doc: dict) -> str:
    """把文档所有文本拍平成一个字符串（用于包含匹配）。"""
    parts = []

    def walk(v):
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)

    walk(doc.get("content") or {})
    walk(doc.get("title") or "")
    return "\n".join(parts)


def analyze(document: dict, jd: str) -> dict[str, Any]:
    """JD 与简历的匹配分析，返回匹配率 / 缺失 / 建议。"""
    jd = (jd or "").strip()
    if not jd:
        raise ValueError("请粘贴 JD（职位描述）文本")
    if len(jd) > 8000:
        raise ValueError("JD 过长（上限 8000 字）")

    keywords = extract_keywords(jd)
    resume_text = _normalize(_flatten_document(document))

    matched, missing = [], []
    by_category: dict[str, dict] = {}
    total_w = 0
    got_w = 0

    for cat, terms in keywords.items():
        w = WEIGHTS[cat]
        cat_matched, cat_missing = [], []
        for t in terms:
            total_w += w
            if _normalize(t) in resume_text:
                got_w += w
                cat_matched.append(t)
                matched.append({"keyword": t, "category": cat, "weight": w})
            else:
                cat_missing.append(t)
                missing.append({"keyword": t, "category": cat, "weight": w})
        by_category[cat] = {"matched": cat_matched, "missing": cat_missing}

    score = round(got_w / total_w * 100) if total_w else 0
    missing.sort(key=lambda x: -x["weight"])

    suggestions = []
    if not keywords["skill"]:
        suggestions.append("未能从 JD 识别出硬技能关键词——请确认粘贴的是完整职位描述")
    skill_missing = [m["keyword"] for m in missing if m["category"] == "skill"]
    if skill_missing:
        suggestions.append(
            f"简历中未体现 {len(skill_missing)} 个 JD 硬技能要求：{'、'.join(skill_missing[:8])}"
            + (" 等" if len(skill_missing) > 8 else "")
            + "。如确实掌握，请补入「专业技能」；如完全不熟，可针对性了解后再投。")
    edu_missing = [m["keyword"] for m in missing if m["category"] == "education"]
    if edu_missing:
        suggestions.append(f"JD 提到的学历/专业要求未在简历中出现：{'、'.join(edu_missing[:6])}")
    if score < 60:
        suggestions.append("整体匹配率偏低，建议按 JD 关键词重写 bullet（可用 AI 的「JD 定制」）")
    elif score < 75:
        suggestions.append("匹配率中等，补充缺失的硬技能关键词后可显著提升")
    if not suggestions:
        suggestions.append("匹配率良好，简历与 JD 的关键词覆盖较充分")

    return {
        "score": score,
        "matchedCount": len(matched),
        "missingCount": len(missing),
        "matched": matched,
        "missing": missing,
        "byCategory": by_category,
        "suggestions": suggestions,
        "keywordCounts": {cat: len(terms) for cat, terms in keywords.items()},
    }
