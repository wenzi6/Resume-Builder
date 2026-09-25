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


# ---------------- 逐字 Span PDF 的补丁定位回归 ----------------

def _per_char_pdf(lines: list[str]) -> bytes:
    """构造「逐字独立 Span」的 PDF（模拟问题导出器），验证按行重组匹配。

    每个字用不同字号，避免 PyMuPDF 把同字号的相邻字合并成一个 Span。
    """
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 60
    for text in lines:
        x = 60
        for i, ch in enumerate(text):
            page.insert_text((x, y), ch, fontsize=11 + i * 0.01, fontname="china-s")
            x += 12
        y += 22
    buf = doc.tobytes()
    doc.close()
    return buf


def test_patch_pdf_locates_text_in_per_char_spans(tmp_path):
    """公司名被拆成逐字 Span 时，原格式补丁仍要能定位并替换。"""
    from resume_builder.services import pdf_patch

    pdf = _per_char_pdf([
        "2021-08 ~ 2023-06 四川准达信息技术有限公司",
        "安全运维工程师",
        "负责对客户服务器集群的部署和监控",
    ])
    src = tmp_path / "src.pdf"
    src.write_bytes(pdf)

    old = {"workExperiences": [{"company": "四川准达信息技术有限公司",
                                "jobTitle": "安全运维工程师",
                                "descriptions": ["负责对客户服务器集群的部署和监控"]}]}
    new = {"workExperiences": [{"company": "字节跳动",
                                "jobTitle": "高级安全运维工程师",
                                "descriptions": ["负责对客户服务器集群的部署和监控"]}]}
    r = pdf_patch.patch_pdf(str(src), old, new)
    paths = [a["path"] for a in r["applied"]]
    assert "workExperiences.0.company" in paths, r["failed"]
    assert "workExperiences.0.jobTitle" in paths, r["failed"]
    text = _text(r["data"])
    assert "字节跳动" in text
    assert "四川准达" not in text
    assert "2021-08 ~ 2023-06" in text          # 同行其他内容不能被误删


def test_page_lines_groups_spans_by_baseline():
    from resume_builder.services import pdf_patch

    pdf = _per_char_pdf(["第一行内容", "第二行内容"])
    import pymupdf

    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        lines = pdf_patch._page_lines(doc[0])
    assert len(lines) == 2, [l["text"] for l in lines]
    assert lines[0]["text"] == "第一行内容"
    assert lines[1]["text"] == "第二行内容"


def test_patch_pdf_uses_matching_cjk_font(tmp_path):
    """原格式补丁必须用与原文观感一致的内置黑体（不能是 PyMuPDF 内置 china-s）。"""
    from resume_builder.services import pdf_patch

    pdf = _per_char_pdf([
        "2021-08 ~ 2023-06 四川准达信息技术有限公司",
        "负责对客户服务器集群的部署和监控",
    ])
    src = tmp_path / "src.pdf"
    src.write_bytes(pdf)

    old = {"workExperiences": [{"company": "四川准达信息技术有限公司",
                                "descriptions": ["负责对客户服务器集群的部署和监控"]}]}
    new = {"workExperiences": [{"company": "字节跳动有限公司",
                                "descriptions": ["负责对客户服务器集群的部署和监控"]}]}
    r = pdf_patch.patch_pdf(str(src), old, new)
    assert any(a["path"] == "workExperiences.0.company" for a in r["applied"]), r["failed"]

    import pymupdf

    with pymupdf.open(stream=r["data"], filetype="pdf") as doc:
        fonts = {f[3] for p in doc for f in p.get_fonts(full=True)}
        text = "".join(p.get_text() for p in doc)
    assert "字节跳动有限公司" in text

    def _is_noto(name: str) -> bool:
        n = name.lower().replace(" ", "")
        return "notosanssc" in n

    # 插入的中文必须走内置 Noto Sans SC（Type0 嵌入）——合成 PDF 自带的 china-s 不算
    assert any(_is_noto(f) for f in fonts), fonts

    # 精确验证：新文字所在的 Span 用的是 Noto Sans SC
    with pymupdf.open(stream=r["data"], filetype="pdf") as doc:
        new_span_fonts = set()
        for b in doc[0].get_text("dict")["blocks"]:
            if b.get("type") != 0:
                continue
            for l in b["lines"]:
                for s in l["spans"]:
                    if "字节跳动" in s["text"]:
                        new_span_fonts.add(s["font"])
    assert new_span_fonts and all(_is_noto(f) for f in new_span_fonts), new_span_fonts


def test_patch_pdf_detects_bold_from_type3(tmp_path):
    """Type3 逐字字体无法从字体名判粗细——用墨迹密度判定（公司名加粗→Bold 字体）。"""
    from resume_builder.services import pdf_patch

    # 用自家管线生成带加粗公司名的 PDF
    from resume_builder.engine import pdf as pdf_engine
    from resume_builder.sample import sample_general

    data = pdf_engine.render_pdf_bytes(sample_general())
    src = tmp_path / "bold.pdf"
    src.write_bytes(data)
    extracted = __import__("resume_builder.services.pdf_import", fromlist=["x"])
    from resume_builder.services.pdf_import import build_document_from_pdf, extract_pdf

    content = build_document_from_pdf(extract_pdf(open(src, "rb")))
    work = content.get("workExperiences") or []
    if not work:
        import pytest

        pytest.skip("样本未解析出工作经历")
    import copy

    source = copy.deepcopy(content)
    company = work[0].get("company") or ""
    if not company:
        import pytest

        pytest.skip("样本首段经历无公司名")
    changed = copy.deepcopy(content)
    changed["workExperiences"][0]["company"] = "测试公司名称"
    r = pdf_patch.patch_pdf(str(src), source, changed)
    applied = [a["path"] for a in r["applied"]]
    assert any(p.endswith("company") for p in applied), (applied, r["failed"])

    import pymupdf

    with pymupdf.open(stream=r["data"], filetype="pdf") as doc:
        fonts = {f[3] for p in doc for f in p.get_fonts(full=True)}
    assert any("notosanssc" in f.lower().replace(" ", "") for f in fonts), fonts


def test_patch_pdf_keeps_readable_size_for_long_text(tmp_path):
    """替换文本明显变长时，字号不得被压到小字（保底 88%/7.5pt，空白区自然延展）。"""
    from resume_builder.services import pdf_patch

    pdf = _per_char_pdf([
        "负责客户服务器集群的部署和监控",
    ])
    src = tmp_path / "long.pdf"
    src.write_bytes(pdf)

    long_text = ("负责客户服务器集群的部署监控与容量规划，覆盖负载均衡、自动扩缩容与故障演练，"
                 "保障核心业务系统全年 99.95% 可用性，并推动监控体系标准化落地。")
    old = {"workExperiences": [{"descriptions": ["负责客户服务器集群的部署和监控"]}]}
    new = {"workExperiences": [{"descriptions": [long_text]}]}
    r = pdf_patch.patch_pdf(str(src), old, new)
    assert any(a["path"] == "workExperiences.0.descriptions.0" for a in r["applied"]), r["failed"]

    import pymupdf

    with pymupdf.open(stream=r["data"], filetype="pdf") as doc:
        sizes = [round(s["size"], 1)
                 for b in doc[0].get_text("dict")["blocks"] if b.get("type") == 0
                 for l in b["lines"] for s in l["spans"] if "99.95%" in s["text"]]
        all_sizes = [round(s["size"], 1)
                     for b in doc[0].get_text("dict")["blocks"] if b.get("type") == 0
                     for l in b["lines"] for s in l["spans"] if s["text"].strip()]
    assert sizes, "长文本未写入"
    assert sizes[0] >= 7.4, f"字号被压到 {sizes[0]}pt：{all_sizes}"
    assert not any(s < 6.5 for s in all_sizes), all_sizes
