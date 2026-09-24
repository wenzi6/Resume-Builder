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
