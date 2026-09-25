"""PDF 导入回归：用自家管线生成样本 PDF，验证解析回结构化数据。"""
from __future__ import annotations

import io

import pytest

from resume_builder.engine import pdf as pdf_engine
from resume_builder.sample import sample_general


@pytest.fixture(scope="module")
def sample_pdfs():
    """两份文本型 PDF：ats-plain（最干净）+ classic。"""
    out = {}
    for tpl in ("ats-plain", "classic"):
        d = sample_general()
        d["templateId"] = tpl
        out[tpl] = pdf_engine.render_pdf_bytes(d)
    return out


def test_import_pdf_ats_plain(client, sample_pdfs):
    r = client.post(
        "/api/v1/import/pdf",
        data={"file": (io.BytesIO(sample_pdfs["ats-plain"]), "resume.pdf")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    doc = r.get_json()["document"]
    content = doc["content"]
    # 姓名 / 公司 / 学校应被解析出来（pdf_import 的核心断言）
    name = (content.get("profile") or {}).get("name", "")
    assert name, f"未解析出姓名：{str(content)[:200]}"


def test_import_pdf_classic(client, sample_pdfs):
    r = client.post(
        "/api/v1/import/pdf",
        data={"file": (io.BytesIO(sample_pdfs["classic"]), "resume.pdf")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200
    doc = r.get_json()["document"]
    assert doc["content"]["profile"]["name"] == "张三"


def test_import_pdf_returns_raw_text(client, sample_pdfs):
    r = client.post(
        "/api/v1/import/pdf",
        data={"file": (io.BytesIO(sample_pdfs["classic"]), "resume.pdf")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200
    raw = r.get_json().get("rawText", "")
    assert "张三" in raw


def test_import_pdf_garbage_graceful(client):
    """坏 PDF 不能 500 崩掉，至少给出错误信息。"""
    r = client.post(
        "/api/v1/import/pdf",
        data={"file": (io.BytesIO(b"not a pdf at all"), "bad.pdf")},
        content_type="multipart/form-data",
    )
    assert r.status_code in (400, 500)
    assert "error" in r.get_json()


def test_import_pdf_wrong_ext(client):
    r = client.post(
        "/api/v1/import/pdf",
        data={"file": (io.BytesIO(b"x"), "a.txt")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 400


# ---------------- 公司/职位行判别回归（用户导入 PDF 职位被当成公司） ----------------

from resume_builder.services import pdf_import


def test_parse_work_bold_company_then_plain_title():
    """加粗行=公司+日期，紧随的非加粗短行=职位（用户 PDF 的实际版式）。"""
    lines = [
        "2026-04~2026-06 长沙悦智人工智能",
        "腾讯云技术支持",
        "工作内容：",
        "负责客户云服务器排查与处理",
        "跟进工单处理并输出解决方案",
        "2023-07~2026-01 深圳市马博士网络科技有限公司",
        "安全服务工程师",
        "工作内容：",
        "负责政府、医疗行业客户网络安全产品支持",
    ]
    bolds = [True, False, True, False, False, True, False, True, False]
    items = pdf_import._parse_work(lines, bolds)
    assert len(items) == 2, items
    assert items[0]["company"] == "长沙悦智人工智能"
    assert items[0]["jobTitle"] == "腾讯云技术支持"
    assert items[0]["date"].startswith("2026-04")
    assert len(items[0]["descriptions"]) == 2
    assert items[1]["company"] == "深圳市马博士网络科技有限公司"
    assert items[1]["jobTitle"] == "安全服务工程师"


def test_parse_work_title_never_becomes_company_without_bold():
    """无加粗信息时（纯文本兜底），职位词结尾的行也不进 company。"""
    lines = [
        "2021-08~2023-06 四川准达信息技术有限公司",
        "安全运维工程师",
        "负责对客户服务器集群的部署和监控",
    ]
    items = pdf_import._parse_work(lines, None)
    assert len(items) == 1
    assert items[0]["company"] == "四川准达信息技术有限公司"
    assert items[0]["jobTitle"] == "安全运维工程师"


def test_parse_work_standalone_title_after_descriptions_starts_new_entry():
    """上一条目已完整后出现的职位行 = 新条目（公司缺失版式）。"""
    lines = [
        "2020-07~2022-07 四川准达信息技术有限公司",
        "负责华为、中兴等项目技术人员招聘",
        "IT招聘专员",
        "负责公司IT技术岗位招聘工作",
    ]
    items = pdf_import._parse_work(lines, [True, False, False, False])
    assert len(items) == 2, items
    assert items[1]["jobTitle"] == "IT招聘专员"
    assert items[1]["company"] == ""
    assert items[1]["descriptions"] == ["负责公司IT技术岗位招聘工作"]


def test_parse_projects_bold_name_then_role():
    lines = [
        "2023-07~2025-04 某政府单位驻场安全服务项目",
        "安全服务工程师",
        "负责客户安全平台日常运维",
    ]
    items = pdf_import._parse_projects(lines, [True, False, False])
    assert len(items) == 1
    assert items[0]["project"] == "某政府单位驻场安全服务项目"
    assert items[0]["jobTitle"] == "安全服务工程师"


def test_norm_text_maps_cjk_radical_supplement():
    """CJK 部首补充块（NFKC 转不了）必须显式映射，否则公司名对不上。"""
    assert pdf_import.norm_text("⻓沙悦智⼈⼯智能") == "长沙悦智人工智能"
    assert pdf_import.norm_text("⻢博士") == "马博士"
    assert pdf_import.norm_text("⻛险响应") == "风险响应"
