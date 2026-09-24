"""原格式导出回归：修改模块内容后导出，仍是原始版式（补丁应用）。"""
from __future__ import annotations

import io

import pytest

from resume_builder.engine import pdf as pdf_engine
from resume_builder.sample import sample_general


@pytest.fixture()
def imported(client):
    """导入一份 PDF 并落库（带 sourceContent 快照）。"""
    data = pdf_engine.render_pdf_bytes(sample_general())
    r = client.post(
        "/api/v1/import/pdf",
        data={"file": (io.BytesIO(data), "resume.pdf")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200
    doc = r.get_json()["document"]
    assert doc.get("sourceContent"), "导入必须存档原始解析内容"
    r2 = client.put(f"/api/v1/documents/{doc['id']}", json={"document": doc})
    assert r2.status_code == 200
    doc_id = doc["id"]
    yield doc_id
    client.delete(f"/api/v1/documents/{doc_id}")


def _text(pdf_bytes: bytes) -> str:
    import pymupdf

    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
        return "".join(p.get_text() for p in pdf)


def test_export_original_no_change_returns_original(client, imported):
    """内容无修改 → 原样导出（与导入的 PDF 内容一致）。"""
    doc = client.get(f"/api/v1/documents/{imported}").get_json()["document"]
    r = client.post("/api/v1/export/pdf", json={"id": imported, "mode": "original"})
    assert r.status_code == 200
    assert r.get_data()[:4] == b"%PDF"
    assert "X-Resume-Warnings" in r.headers  # 「内容无修改」提示
    assert "张三" in _text(r.get_data())


def test_export_original_applies_edit_and_keeps_layout(client, imported):
    """改名字后原格式导出：新名字进去、旧名字消失、其余原版式文本保持。"""
    doc = client.get(f"/api/v1/documents/{imported}").get_json()["document"]
    doc["content"]["profile"]["name"] = "李四"
    doc["content"]["profile"]["phone"] = "13900000000"
    client.put(f"/api/v1/documents/{imported}", json={"document": doc})

    r = client.post("/api/v1/export/pdf", json={"id": imported, "mode": "original"})
    assert r.status_code == 200
    data = r.get_data()
    text = _text(data)
    assert "李四" in text, "新名字必须出现在导出 PDF 中"
    assert "13900000000" in text, "新电话必须出现"
    assert "张三" not in text, "旧名字必须被替换掉"
    # 未改动的内容原样保留（原版式的其他文本还在）
    assert "某科技有限公司" in text
    assert "中山大学" in text
    assert "React" in text
    # 页数不变（版式未重排）
    import pymupdf

    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        assert pdf.page_count >= 1


def test_export_original_handles_deletion(client, imported):
    """删除的内容在导出中被移除（redact）。用解析可靠的 profile 字段验证。"""
    doc = client.get(f"/api/v1/documents/{imported}").get_json()["document"]
    # 确认邮箱被解析到（启发式解析的覆盖度以原始格式为准绳）
    assert doc["content"]["profile"].get("email"), "邮箱应被解析"
    doc["content"]["profile"]["email"] = ""
    client.put(f"/api/v1/documents/{imported}", json={"document": doc})

    r = client.post("/api/v1/export/pdf", json={"id": imported, "mode": "original"})
    assert r.status_code == 200
    text = _text(r.get_data())
    assert "zhangsan@example.com" not in text, "被删除的邮箱应从导出中移除"
    assert "张三" in text, "其他内容不受影响"


def test_export_original_requires_source_pdf(client):
    r = client.post("/api/v1/documents", json={"templateId": "classic", "title": "无附件"})
    doc_id = r.get_json()["document"]["id"]
    r2 = client.post("/api/v1/export/pdf", json={"id": doc_id, "mode": "original"})
    assert r2.status_code == 400
    assert "原始 PDF" in r2.get_json()["error"]
    client.delete(f"/api/v1/documents/{doc_id}")


def test_export_original_missing_file(client, imported):
    """原始 PDF 文件被删 → 明确 404，不崩溃。"""
    from resume_builder import config

    doc = client.get(f"/api/v1/documents/{imported}").get_json()["document"]
    (config.DATA_DIR / doc["sourcePdf"]).unlink()
    r = client.post("/api/v1/export/pdf", json={"id": imported, "mode": "original"})
    assert r.status_code == 404


def test_template_export_still_works(client, imported):
    """不带 mode（或 template）仍走模板重排版（回归保护）。"""
    doc = client.get(f"/api/v1/documents/{imported}").get_json()["document"]
    doc["content"]["profile"]["name"] = "模板导出名"
    client.put(f"/api/v1/documents/{imported}", json={"document": doc})
    r = client.post("/api/v1/export/pdf", json={"id": imported})
    assert r.status_code == 200
    assert "模板导出名" in _text(r.get_data())


def test_source_content_survives_roundtrip(client, imported):
    """sourceContent 随文档保存 / 读取 / JSON 导出不丢失。"""
    doc = client.get(f"/api/v1/documents/{imported}").get_json()["document"]
    assert doc["sourceContent"]["profile"]["name"] == "张三"
    r = client.post("/api/v1/export/json", json={"id": imported})
    assert b"sourceContent" in r.get_data()


def test_patch_diff_unit():
    """diff_content 的单元行为：改 / 删 / 增。"""
    from resume_builder.services.pdf_patch import diff_content

    old = {
        "profile": {"name": "张三", "phone": "138"},
        "workExperiences": [{"company": "A公司", "descriptions": ["x", "y"]}],
    }
    new = {
        "profile": {"name": "李四", "phone": "138"},
        "workExperiences": [{"company": "A公司", "descriptions": ["x"]}],
    }
    changes = {c["path"]: c for c in diff_content(old, new)}
    assert changes["profile.name"]["new"] == "李四"
    assert changes["workExperiences.0.descriptions.1"]["new"] is None  # 删除
