"""pytest 共享 fixtures。

PDF 相关用例会真实启动 Chromium 子进程（较慢但必要——字体嵌入与分页
只能在真实渲染管线上验证）。
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from resume_builder import create_app
from resume_builder.sample import sample_general, sample_tech


@pytest.fixture(scope="session")
def app():
    return create_app()


@pytest.fixture()
def client(app, tmp_path, monkeypatch):
    """隔离的 test client：使用临时数据库，不碰真实数据。"""
    from resume_builder.services import documents as store

    db = tmp_path / "test_resumes.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    store.init_db()
    app.config["TESTING"] = True
    yield app.test_client()


@pytest.fixture()
def doc_general():
    return sample_general()


@pytest.fixture()
def doc_tech():
    return sample_tech()


@pytest.fixture()
def long_doc():
    """构造 3 页内容的文档（分页回归用；内容分散在多个区块以利分页）。"""
    doc = sample_general()
    doc["title"] = "三页测试简历"
    for i in range(6):
        doc["content"]["workExperiences"].append({
            "company": f"测试公司{i}",
            "jobTitle": "高级工程师",
            "date": f"20{i % 10:02d}-01 – 20{i % 10:02d}-12",
            "descriptions": [
                f"负责第 {i} 个核心业务系统的架构设计与开发，支撑日均 10 万+ 用户访问",
                "推动组件化与工程化建设，需求交付效率提升 40%，首屏 LCP 降至 1.8s",
                "建设前端监控与告警体系，线上问题定位时间从小时级降至分钟级",
            ],
        })
    for i in range(5):
        doc["content"]["projects"].append({
            "project": f"测试项目{i}",
            "jobTitle": "前端负责人",
            "date": f"20{i % 10:02d}-03 – 20{i % 10:02d}-12",
            "descriptions": [
                "基于 React + Ant Design Pro 搭建，实现权限管理、数据可视化、多语言等模块",
                "设计前端监控体系，线上问题定位时间从小时级降至分钟级",
            ],
        })
    for i in range(2):
        doc["content"]["educations"].append({
            "school": f"某某大学{i}",
            "degree": "本科 · 计算机科学与技术",
            "date": f"20{i % 10:02d}-09 – 20{i % 10:02d}-06",
            "descriptions": ["GPA 3.8/4.0，获校级奖学金"],
        })
    doc["content"]["selfEvaluation"]["descriptions"] = [
        f"第 {i} 条自我评价：做事认真负责，具备良好的团队协作与沟通能力，抗压能力强，对技术有热情。"
        for i in range(5)
    ]
    return doc


@pytest.fixture(scope="session")
def output_dir():
    from resume_builder.config import OUTPUT_DIR

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR
