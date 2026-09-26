"""内置区块注册表。

定义简历的内置区块结构（字段、类型、标签），是表单渲染、数据校验、
区块渲染三方的唯一事实来源。用户自定义区块复用同样的结构。
"""
from __future__ import annotations

from typing import Any

# 字段控件类型 -> 前端渲染方式
#   text     单行输入
#   date     日期输入（归一化为 YYYY-MM 展示）
#   textarea 多行输入
#   list     多行列表（每行一条，如职责描述）
#   rating   技能星级

BUILTIN_SECTIONS: list[dict[str, Any]] = [
    {
        "key": "profile",
        "title": "个人信息",
        "type": "object",
        "icon": "user",
        "fields": [
            {"key": "name", "label": "姓名", "type": "text", "required": True},
            {"key": "title", "label": "求职意向", "type": "text"},
            {"key": "email", "label": "邮箱", "type": "text"},
            {"key": "phone", "label": "电话", "type": "text"},
            {"key": "location", "label": "所在地", "type": "text"},
            {"key": "age", "label": "年龄", "type": "text"},
            {"key": "gender", "label": "性别", "type": "text"},
            {"key": "desiredSalary", "label": "期望薪资", "type": "text"},
            {"key": "availableDate", "label": "到岗时间", "type": "text"},
            {"key": "photo", "label": "照片地址", "type": "text", "hint": "http(s) 链接或 /data/ 下本地路径"},
            {"key": "summary", "label": "个人简介", "type": "textarea"},
        ],
    },
    {
        "key": "workExperiences",
        "title": "工作经历",
        "type": "array",
        "icon": "briefcase",
        "itemLabel": "经历",
        "titleField": "company",
        "fields": [
            {"key": "company", "label": "公司", "type": "text"},
            {"key": "jobTitle", "label": "职位", "type": "text"},
            {"key": "date", "label": "时间", "type": "text", "hint": "如 2021-03 – 至今"},
            {"key": "descriptions", "label": "职责描述", "type": "list"},
            {"key": "achievements", "label": "工作成果", "type": "list",
             "hint": "能量化的业绩/结果，如「月均到岗 15 人，试用期留存率 92%」"},
        ],
    },
    {
        "key": "projects",
        "title": "项目经历",
        "type": "array",
        "icon": "folder",
        "itemLabel": "项目",
        "titleField": "project",
        "fields": [
            {"key": "project", "label": "项目名称", "type": "text"},
            {"key": "jobTitle", "label": "担任角色", "type": "text"},
            {"key": "date", "label": "时间", "type": "text"},
            {"key": "descriptions", "label": "项目描述", "type": "list"},
            {"key": "achievements", "label": "项目成果", "type": "list"},
        ],
    },
    {
        "key": "educations",
        "title": "教育经历",
        "type": "array",
        "icon": "school",
        "itemLabel": "经历",
        "titleField": "school",
        "fields": [
            {"key": "school", "label": "学校", "type": "text"},
            {"key": "degree", "label": "学历 / 专业", "type": "text"},
            {"key": "date", "label": "时间", "type": "text"},
            {"key": "descriptions", "label": "备注 / 主修课程", "type": "list"},
        ],
    },
    {
        "key": "skills",
        "title": "专业技能",
        "type": "skills",
        "icon": "star",
        "fields": [
            {"key": "featuredSkills", "label": "主要技能", "type": "rating"},
            {"key": "descriptions", "label": "其他技能", "type": "list", "hint": "每行一个，如 Webpack / Vite"},
        ],
    },
    {
        "key": "selfEvaluation",
        "title": "自我评价",
        "type": "simple",
        "icon": "quote",
        "fields": [
            {"key": "descriptions", "label": "内容", "type": "list"},
        ],
    },
    {
        "key": "custom",
        "title": "其他信息",
        "type": "simple",
        "icon": "dots",
        "fields": [
            {"key": "descriptions", "label": "内容", "type": "list", "hint": "博客、开源、证书、语言等"},
        ],
    },
]

BUILTIN_KEYS = [s["key"] for s in BUILTIN_SECTIONS]
BUILTIN_SECTION_MAP = {s["key"]: s for s in BUILTIN_SECTIONS}

# 自定义区块默认字段
CUSTOM_ARRAY_FIELDS = [
    {"key": "name", "label": "名称", "type": "text"},
    {"key": "date", "label": "时间", "type": "text"},
    {"key": "descriptions", "label": "说明", "type": "list"},
]
CUSTOM_SIMPLE_FIELDS = [
    {"key": "descriptions", "label": "内容", "type": "list"},
]


def builtin_section_defs() -> list[dict[str, Any]]:
    """返回内置区块定义的深拷贝（避免调用方篡改注册表）。"""
    import copy

    return copy.deepcopy(BUILTIN_SECTIONS)


def section_def(key: str) -> dict[str, Any] | None:
    return BUILTIN_SECTION_MAP.get(key)


def default_field_for(custom_type: str) -> list[dict[str, Any]]:
    import copy

    return copy.deepcopy(
        CUSTOM_ARRAY_FIELDS if custom_type == "array" else CUSTOM_SIMPLE_FIELDS
    )
