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


# ---------------- 重新解析（解析规则升级后刷新旧文档） ----------------

def test_reparse_refreshes_old_import(client, sample_pdfs):
    """旧文档（旧解析规则产物）可一键用当前解析器刷新。"""
    r = client.post(
        "/api/v1/import/pdf",
        data={"file": (io.BytesIO(sample_pdfs["classic"]), "old.pdf")},
        content_type="multipart/form-data",
    )
    doc = r.get_json()["document"]
    doc_id = doc["id"]
    try:
        # 模拟「旧数据」：把内容改坏
        doc["content"]["workExperiences"] = [{"company": "错的数据", "jobTitle": "",
                                              "date": "", "descriptions": ["x"]}]
        client.put(f"/api/v1/documents/{doc_id}", json={"document": doc})

        r2 = client.post("/api/v1/import/reparse", json={"id": doc_id})
        assert r2.status_code == 200, r2.get_json()
        fresh = r2.get_json()["document"]
        comps = [w.get("company") for w in fresh["content"]["workExperiences"]]
        assert "错的数据" not in comps
        assert any(comps), comps
        # sourceContent 基线同步刷新（原格式导出的 diff 从新基线算）
        assert fresh["sourceContent"]["workExperiences"] == fresh["content"]["workExperiences"]
        # 原始 PDF 仍在
        assert fresh.get("sourcePdf")
    finally:
        client.delete(f"/api/v1/documents/{doc_id}")


def test_reparse_rejects_non_pdf_doc(client):
    """非 PDF 导入文档没有可重新解析的原始文件。"""
    from resume_builder.sample import sample_general

    r = client.post("/api/v1/documents", json={"document": sample_general()})
    assert r.status_code in (200, 201), r.get_json()
    doc_id = r.get_json()["document"]["id"]
    try:
        r2 = client.post("/api/v1/import/reparse", json={"id": doc_id})
        assert r2.status_code == 400
        assert "不是 PDF" in r2.get_json()["error"]
    finally:
        client.delete(f"/api/v1/documents/{doc_id}")


def test_reparse_unknown_doc(client):
    r = client.post("/api/v1/import/reparse", json={"id": "nope"})
    assert r.status_code == 404


# ---------------- 区块标题误判回归（正文含关键词被当成标题） ----------------

def test_body_line_containing_keyword_is_not_section_title():
    """自我评价正文「具备IT招聘和技术岗位工作经验…」含「工作经验」，
    不能被当成工作经历标题（否则自我评价全被切进工作经历）。"""
    assert pdf_import._match_section_title("💼 工作经验", True) == "workExperiences"
    assert pdf_import._match_section_title("工作经验", False) == "workExperiences"
    # 长句、不加粗、关键词不在行首 → 不是标题
    assert pdf_import._match_section_title(
        "具备IT招聘和技术岗位工作经验,前期主要负责华为、中兴相关IT技术岗位招聘", False) is None
    assert pdf_import._match_section_title(
        "负责教育行业客户的安全产品支持与日常维护", False) is None


def test_join_wrapped_merges_broken_paragraph():
    """PDF 中途换行的同一段话要合并，但不相干的两行不能粘一起。"""
    assert pdf_import._join_wrapped(
        ["具备IT招聘和技术岗位工作经验,前期主要负责华为中兴相关招聘,积累了安全服务", "和云计算相关经验。"]
    ) == ["具备IT招聘和技术岗位工作经验,前期主要负责华为中兴相关招聘,积累了安全服务和云计算相关经验。"]
    # 短行开头（如 RESUME）不与后文合并；条目符号不合并
    assert pdf_import._join_wrapped(["RESUME", "IT招聘专员 面议"]) == ["RESUME", "IT招聘专员 面议"]
    assert pdf_import._join_wrapped(["第一段完整句子。", "· 这是条目"]) == ["第一段完整句子。", "· 这是条目"]


# ---------------- 导入采用 PDF 里的区块标题 ----------------

def test_import_adopts_pdf_section_titles(client):
    """PDF 里写「技能特长」，导入后区块标题就叫「技能特长」（不沿用默认的「专业技能」）。"""
    from resume_builder.engine import pdf as pdf_engine
    from resume_builder.sample import sample_general

    doc = sample_general()
    doc["templateId"] = "classic"
    for s in doc["sections"]:
        if s["key"] == "skills":
            s["title"] = "技能特长"
    data = pdf_engine.render_pdf_bytes(doc)
    r = client.post("/api/v1/import/pdf",
                    data={"file": (io.BytesIO(data), "t.pdf")},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    imported = r.get_json()["document"]
    titles = {s["key"]: s["title"] for s in imported["sections"]}
    assert titles.get("skills") == "技能特长", titles
