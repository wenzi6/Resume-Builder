"""示例简历数据。"""
from __future__ import annotations

import copy

from .schema import DEFAULT_DESIGN, empty_content, new_document

_SAMPLE_GENERAL = {
    "profile": {
        "name": "张三",
        "title": "高级前端工程师",
        "email": "zhangsan@example.com",
        "phone": "13800138000",
        "location": "广州市天河区",
        "age": "",
        "gender": "",
        "desiredSalary": "",
        "availableDate": "",
        "photo": "",
        "summary": "8 年 Web 前端开发经验，精通 React / Vue / TypeScript，主导过多个大型项目的前端架构设计与性能优化，具备团队管理与工程化建设经验。",
    },
    "workExperiences": [
        {
            "company": "某科技有限公司",
            "jobTitle": "高级前端工程师",
            "date": "2021.03 - 至今",
            "descriptions": [
                "负责公司核心产品前端架构设计与开发，支撑日均 10 万+ 用户访问",
                "带领 5 人前端团队，推动组件化与工程化建设，需求交付效率提升 40%",
                "优化首屏加载性能，LCP 从 4.2s 降至 1.8s",
            ],
        },
        {
            "company": "某互联网公司",
            "jobTitle": "前端开发工程师",
            "date": "2018.07 - 2021.02",
            "descriptions": [
                "参与电商平台前端开发，使用 React + TypeScript 技术栈",
                "开发可复用组件库 30+ 个，提升团队开发效率 30%",
            ],
        },
    ],
    "projects": [
        {
            "project": "企业级中台管理系统",
            "jobTitle": "前端负责人",
            "date": "2022.03 - 2022.12",
            "descriptions": [
                "基于 React + Ant Design Pro 搭建，实现权限管理、数据可视化、多语言等模块",
                "设计前端监控体系，线上问题定位时间从小时级降至分钟级",
                "支撑日均 10 万+ 用户访问，页面错误率低于 0.1%",
            ],
        },
    ],
    "educations": [
        {
            "school": "中山大学",
            "degree": "本科 · 计算机科学与技术",
            "date": "2014.09 - 2018.06",
            "descriptions": ["GPA 3.8/4.0，获校级奖学金"],
        },
    ],
    "skills": {
        "featuredSkills": [
            {"skill": "React / Vue", "rating": 5},
            {"skill": "TypeScript", "rating": 5},
            {"skill": "Node.js", "rating": 4},
            {"skill": "CSS / HTML", "rating": 5},
        ],
        "descriptions": ["Webpack / Vite", "Git / GitHub", "Docker", "CI/CD"],
    },
    "selfEvaluation": {"descriptions": []},
    "custom": {
        "descriptions": [
            "个人博客 blog.example.com 累计输出技术文章 50+ 篇",
            "GitHub 开源项目获 Star 2k+，长期维护 3 个开源工具库",
        ]
    },
}

_SAMPLE_TECH = {
    "profile": {
        "name": "李四",
        "title": "网络安全工程师",
        "email": "lisi@example.com",
        "phone": "13900139000",
        "location": "",
        "age": "25",
        "gender": "男",
        "desiredSalary": "面议",
        "availableDate": "一周内到岗",
        "photo": "",
        "summary": "",
    },
    "skills": {
        "featuredSkills": [],
        "descriptions": [
            "了解 OSI 七层模型、TCP/IP 五层模型的功能和工作原理。",
            "了解 SQL 注入、XSS、文件上传与下载漏洞等 OWASP Top 10 漏洞的验证和利用方法，完成漏洞复现。",
            "熟悉 Windows 和 Linux 操作系统以及 MySQL 数据库的使用和常见命令，以及常用服务部署，如 Nginx、Apache、Tomcat 等。",
            "熟练使用 WAF、IDS/IPS、堡垒机、态势感知、EDR、漏洞管理平台等设备的策略配置、日志分析及日常巡检。",
            "精通 AWVS、AppScan、Nessus、绿盟 RSAS 和安恒明鉴漏洞扫描等常用扫描工具，能进行漏洞管理与闭环跟踪。",
            "具备主机入侵排查、日志分析、溯源分析及攻击 IP 封禁经验，熟悉安全事件响应流程。",
        ],
    },
    "workExperiences": [
        {
            "company": "悦智人工智能",
            "jobTitle": "腾讯云技术支持",
            "date": "2026-04 - 2026-06",
            "descriptions": [
                "负责腾讯云客户云服务器、网络及安全类问题的排查与处理",
                "协助客户完成安全组策略配置、网络访问异常分析及系统故障定位",
                "跟进工单处理并输出解决方案",
            ],
        },
        {
            "company": "深圳市马博士网络科技有限公司",
            "jobTitle": "安全服务工程师",
            "date": "2023-07 - 2026-01",
            "descriptions": [
                "负责甲方客户相关安全服务业务实施，包括漏洞扫描、安全加固等工作",
                "管理 EDR 终端安装与维护，定期开展病毒查杀，输出防病毒周/月报，有效降低终端感染风险",
                "对安全设备进行日常巡检，分析告警日志信息并提交安全报告，协助厂商进行整改",
                "负责网页防篡改系统的部署与策略配置，保障核心网站页面完整性，任职期间未发生篡改事件",
            ],
        },
        {
            "company": "四川准达信息技术有限公司",
            "jobTitle": "安全运维工程师",
            "date": "2021-08 - 2023-06",
            "descriptions": [
                "负责对客户服务器集群的部署和监控，保证后端服务器正常稳定运行",
                "负责对客户网站服务安装和系统升级及服务器维护，保障服务稳定安全可靠",
                "针对客户网络安全产品（防火墙、WAF、IPS 等），解决安全产品使用过程中出现的问题",
                "负责操作系统、应用系统、服务器等的安全加固和基线检查，做好日志梳理",
            ],
        },
    ],
    "projects": [
        {
            "project": "某政府单位驻场安全服务项目",
            "jobTitle": "安全服务工程师",
            "date": "2023-07 - 2025-04",
            "descriptions": [
                "负责对客户系统进行安全日常漏洞扫描，并记录以及提交漏扫报告",
                "负责日常安全设备运维（态势感知/云防）等工作",
                "负责对防病毒软件 EDR 问题处理以及安装",
                "针对客户提出的安全漏洞问题进行解答以及提出修复建议",
                "每月输出安全设备日志月度报表，顺利通过年度检查，获得甲方客户高度肯定",
            ],
        },
        {
            "project": "粤盾 2024 网络安全攻防演练",
            "jobTitle": "蓝队成员",
            "date": "2024-08 - 2024-11",
            "descriptions": [
                "前期资产梳理与暴露面收敛，对 Web 及主机系统进行预扫描，减少攻击面",
                "实时监控态势感知、防火墙、蜜罐日志，分析异常流量，识别攻击行为",
                "对高危攻击 IP 进行即时封禁，协助进行攻击溯源分析",
                "全程零重大安全事故，助力防守单位获得全省第二名的好成绩",
            ],
        },
    ],
    "educations": [
        {
            "school": "四川现代职业学院",
            "degree": "电子信息工程技术（大专）",
            "date": "2018-09 - 2021-07",
            "descriptions": ["主修课程：数据通信与网络基础、C 语言程序设计基础等"],
        },
    ],
    "selfEvaluation": {
        "descriptions": [
            "工作积极认真，能够接受出差，服从公司安排，细心负责",
            "熟练运用办公自动化软件，善于在工作中提出问题、发现问题、解决问题，有较强的分析能力",
            "勤奋好学，踏实肯干，动手能力强，认真负责，有很强的社会责任感",
            "坚毅不拔，吃苦耐劳，喜欢迎接新挑战",
        ]
    },
    "custom": {"descriptions": []},
}


def _build(content: dict, template_id: str, title: str, design: dict | None = None) -> dict:
    doc = new_document(template_id=template_id, title=title)
    # 必须深拷贝：浅合并会让返回文档与模块级示例数据共享列表对象，
    # 调用方一旦 append 就会污染后续所有 sample_*() 的结果。
    full = {**empty_content(), **copy.deepcopy(content)}
    doc["content"] = full
    if design:
        doc["design"] = {**DEFAULT_DESIGN, **design}
    return doc


def sample_general() -> dict:
    """示例 1：通用前端工程师简历。"""
    return _build(_SAMPLE_GENERAL, "classic", "示例 · 前端工程师",
                  {"accent": "#0f766e"})


def sample_tech() -> dict:
    """示例 2：技术岗（网络安全）简历。"""
    return _build(_SAMPLE_TECH, "tech", "示例 · 网络安全工程师",
                  {"accent": "#1d4ed8"})


def sample_document() -> dict:
    return sample_general()
