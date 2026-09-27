"""对照导入回归：原始 PDF 原格式保留 + 模块化编辑的数据契约。"""
from __future__ import annotations

import io

import pytest

from resume_builder import config


def _data_dir():
    """运行时读取（fixture 会把它指向临时目录）。"""
    return config.DATA_DIR
from resume_builder.engine import pdf as pdf_engine
from resume_builder.sample import sample_general
from resume_builder.schema import normalize_document


@pytest.fixture()
def sample_pdf_bytes():
    return pdf_engine.render_pdf_bytes(sample_general())


def _import_pdf(client, data, name="resume.pdf"):
    return client.post(
        "/api/v1/import/pdf",
        data={"file": (io.BytesIO(data), name)},
        content_type="multipart/form-data",
    )


def _import_and_save(client, data, name="resume.pdf"):
    """模拟前端流程：导入 → PUT 落库（导入接口本身不写库）。"""
    r = _import_pdf(client, data, name)
    assert r.status_code == 200
    doc = r.get_json()["document"]
    r2 = client.put(f"/api/v1/documents/{doc['id']}", json={"document": doc})
    assert r2.status_code == 200, r2.get_data(as_text=True)[:200]
    return r2.get_json()["document"]


def test_import_pdf_keeps_original_file(client, sample_pdf_bytes):
    """导入后原始 PDF 必须落盘并可经 /data/ 访问（原格式保留的基础）。"""
    r = _import_pdf(client, sample_pdf_bytes)
    assert r.status_code == 200
    body = r.get_json()
    assert "pdf" in body
    pdf_info = body["pdf"]
    assert pdf_info["url"].startswith("/data/imports/")
    assert pdf_info["pages"] >= 1
    assert pdf_info["name"] == "resume.pdf"

    doc = body["document"]
    assert doc.get("sourcePdf", "").startswith("imports/")
    stored = _data_dir() / doc["sourcePdf"]
    assert stored.is_file()
    assert stored.read_bytes()[:4] == b"%PDF"   # 原样保留，未被改动
    assert stored.read_bytes() == sample_pdf_bytes  # 字节级一致

    # 通过 /data/ 路由能拿到原文
    r2 = client.get(pdf_info["url"])
    assert r2.status_code == 200
    assert r2.get_data()[:4] == b"%PDF"


def test_import_pdf_doc_has_modules(client, sample_pdf_bytes):
    """解析出的内容以模块（sections/content）形式存在，与原始 PDF 并存。"""
    doc = _import_and_save(client, sample_pdf_bytes)
    assert doc["sections"], "导入文档应有区块模块"
    assert doc["content"]["profile"]["name"] == "张三"
    assert doc["sourcePdf"]
    client.delete(f"/api/v1/documents/{doc['id']}")


def test_source_pdf_survives_roundtrip(client, sample_pdf_bytes):
    """sourcePdf 随文档保存 / 读取往返不丢失。"""
    doc = _import_and_save(client, sample_pdf_bytes)
    doc_id = doc["id"]

    loaded = client.get(f"/api/v1/documents/{doc_id}").get_json()["document"]
    assert loaded["sourcePdf"] == doc["sourcePdf"]

    d = dict(loaded)
    d["title"] = "改过的标题"
    client.put(f"/api/v1/documents/{doc_id}", json={"document": d})
    loaded2 = client.get(f"/api/v1/documents/{doc_id}").get_json()["document"]
    assert loaded2["sourcePdf"] == doc["sourcePdf"]

    # 列表带出 hasSourcePdf 徽标信息
    docs = client.get("/api/v1/documents").get_json()["documents"]
    me = next(x for x in docs if x["id"] == doc_id)
    assert me["hasSourcePdf"] is True

    client.delete(f"/api/v1/documents/{doc_id}")


def test_delete_removes_source_pdf(client, sample_pdf_bytes):
    """删除文档时原始 PDF 一并清理（不留垃圾文件）。"""
    doc = _import_and_save(client, sample_pdf_bytes)
    stored = _data_dir() / doc["sourcePdf"]
    assert stored.is_file()
    assert client.delete(f"/api/v1/documents/{doc['id']}").status_code == 200
    # Windows 锁文件时重试后可能仍在，孤立清扫会兜底
    if stored.exists():
        from resume_builder.services import documents as store_mod
        assert store_mod.sweep_orphan_source_pdfs(max_age_s=0) >= 1
        assert not stored.exists()
    else:
        assert True


def test_duplicate_copies_source_pdf(client, sample_pdf_bytes):
    """复制文档时原始 PDF 复制为独立文件（互不影响）。"""
    doc = _import_and_save(client, sample_pdf_bytes)
    r2 = client.post(f"/api/v1/documents/{doc['id']}/duplicate")
    copy = r2.get_json()["document"]
    assert copy["sourcePdf"] != doc["sourcePdf"]
    assert (_data_dir() / copy["sourcePdf"]).is_file()
    assert (_data_dir() / doc["sourcePdf"]).is_file()
    # 删原文档不影响副本
    client.delete(f"/api/v1/documents/{doc['id']}")
    assert (_data_dir() / copy["sourcePdf"]).is_file()
    client.delete(f"/api/v1/documents/{copy['id']}")


def test_normalize_rejects_unsafe_source_pdf():
    doc = {"id": "x", "title": "t", "version": 2, "content": {}, "sourcePdf": "../../etc/passwd.pdf"}
    out = normalize_document(doc)
    assert "sourcePdf" not in out
    for bad in ("/abs/path.pdf", "C:/x.pdf", "imports/../x.pdf", "notpdf.txt"):
        out = normalize_document({"id": "x", "version": 2, "content": {}, "sourcePdf": bad})
        assert "sourcePdf" not in out, bad
    out = normalize_document({"id": "x", "version": 2, "content": {}, "sourcePdf": "imports/abc123.pdf"})
    assert out["sourcePdf"] == "imports/abc123.pdf"


def test_source_pages_rendered(client, sample_pdf_bytes):
    """原始 PDF 渲染为逐页图片（对照视图的数据源）。"""
    doc = _import_and_save(client, sample_pdf_bytes)
    r = client.get(f"/api/v1/documents/{doc['id']}/source-pages")
    assert r.status_code == 200
    body = r.get_json()
    assert body["pages"], "应有页面"
    p1 = body["pages"][0]
    assert p1["url"].startswith("/data/imports/pages/")
    assert p1["width"] > 0 and p1["height"] > 0
    assert body["pdfUrl"].startswith("/data/")

    # 图片本身可访问且是 PNG
    r2 = client.get(p1["url"])
    assert r2.status_code == 200
    assert r2.get_data()[:4] == b"\x89PNG"

    client.delete(f"/api/v1/documents/{doc['id']}")


def test_source_pages_unknown_doc(client):
    assert client.get("/api/v1/documents/nope/source-pages").status_code == 404


def test_export_json_keeps_source_pdf(client, sample_pdf_bytes):
    """导出的 JSON 带上 sourcePdf（换机器导入时优雅降级，前端有兜底提示）。"""
    doc = _import_and_save(client, sample_pdf_bytes)
    r2 = client.post("/api/v1/export/json", json={"document": doc})
    assert r2.status_code == 200
    assert b"sourcePdf" in r2.get_data()
    client.delete(f"/api/v1/documents/{doc['id']}")


# ---------------------------------------------------------------- 列表标记打进原格式

def _write_source_pdf(data, name="marker-src.pdf") -> str:
    """把一份 PDF 落到临时 imports/，返回 patch_pdf 需要的相对路径。"""
    rel = f"imports/{name}"
    p = _data_dir() / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return rel


def _pdf_text(data: bytes) -> str:
    import pymupdf

    with pymupdf.open(stream=data, filetype="pdf") as d:
        return "\n".join(page.get_text() for page in d)


def test_patch_bullet_num_on_vector_dots(client, sample_pdf_bytes):
    """矢量圆点的原格式：标记=数字 → 行首变 1. 2. 3.，每条经历重新计数。"""
    from resume_builder.services import pdf_patch

    rel = _write_source_pdf(sample_pdf_bytes)
    doc = normalize_document(sample_general())
    design = {**doc["design"], "bulletStyle": "num"}
    result = pdf_patch.patch_pdf(rel, doc["content"], doc["content"],
                                 doc["sections"], design=design)
    assert not result["unchanged"]
    styled = [a for a in result["applied"] if a.get("path") == "design.bulletStyle"]
    assert styled and styled[0]["markers"] >= 3
    text = _pdf_text(result["data"])
    assert "1." in text and "2." in text and "3." in text


def test_patch_bullet_none_and_custom_on_text_dots(client):
    """文字圆点（独立 Span）的原格式：none 清掉圆点、custom 换成自定义字符。"""
    import fitz

    from resume_builder.services import pdf_patch

    d = fitz.open()
    page = d.new_page()
    lines = ["熟悉TCP/IP网络体系。", "熟悉Linux常用命令。", "熟悉EDR平台运维。"]
    for i, txt in enumerate(lines):
        y = 80 + i * 16
        page.insert_text((72, y), "·", fontsize=10, fontname="helv")
        page.insert_text((82, y), txt, fontsize=10, fontname="china-s")
    rel = _write_source_pdf(d.tobytes(), "textdots.pdf")

    content = {"skills": {"descriptions": lines}}
    sections = [{"key": "skills", "title": "技能特长", "type": "free", "visible": True,
                 "fields": [{"key": "descriptions", "label": "技能内容", "type": "free"}]}]

    r_none = pdf_patch.patch_pdf(rel, content, content, sections,
                                 design={"bulletStyle": "none"})
    assert not r_none["unchanged"]
    assert "·" not in _pdf_text(r_none["data"])

    r_custom = pdf_patch.patch_pdf(rel, content, content, sections,
                                   design={"bulletStyle": "custom", "bulletChar": "◆"})
    text = _pdf_text(r_custom["data"])
    assert "◆" in text and "·" not in text


def test_patch_bullet_dot_keeps_original_bytes(client, sample_pdf_bytes):
    """默认圆点 = 导入原貌：无内容改动时原样返回（unchanged，字节不动）。"""
    from resume_builder.services import pdf_patch

    rel = _write_source_pdf(sample_pdf_bytes, "dotkeep.pdf")
    doc = normalize_document(sample_general())
    result = pdf_patch.patch_pdf(rel, doc["content"], doc["content"],
                                 doc["sections"], design=doc["design"])
    assert result["unchanged"]
    assert result["data"] == (_data_dir() / rel).read_bytes()


def test_render_num_bullet_attr_and_css():
    """模板渲染：num 标记输出 data-bullet="num"，CSS 用 counter 编号。"""
    from resume_builder.engine import sections as sec

    section = {"key": "workExperiences", "type": "array", "title": "工作经历",
               "fields": [{"key": "descriptions", "type": "list"}]}
    attr = sec._bullet_attr(section, {"bulletStyle": "num"})
    assert 'data-bullet="num"' in attr
    from resume_builder.engine import base_css
    css = base_css.base_css(20.0)
    assert 'data-bullet="num"' in css
    assert "counter(rbullet)" in css


# ---------------------------------------------------------------- 标签行（短行+冒号）去点前移

def test_replace_to_label_removes_vector_dot_and_outdents(client, sample_pdf_bytes):
    """替换成短标签（如「工作成果：」）：矢量圆点清掉、文字提到圆点列。"""
    import fitz

    from resume_builder.services import pdf_patch

    d = fitz.open()
    page = d.new_page()
    # 矢量圆点（x=130）+ 正文（x=141.4），仿用户简历的工作区版式
    page.draw_circle((130, 100), 1.5, color=(0, 0, 0), fill=(0, 0, 0))
    page.insert_text((141.4, 100), "维护招聘渠道及候选人资源,提高招聘效率。",
                     fontsize=9, fontname="china-s")
    rel = _write_source_pdf(d.tobytes(), "labelvec.pdf")

    old = {"skills": {"descriptions": ["维护招聘渠道及候选人资源,提高招聘效率。"]}}
    new = {"skills": {"descriptions": ["工作成果:"]}}
    result = pdf_patch.patch_pdf(rel, old, new, [], design={"bulletStyle": "dot"})
    assert not result["unchanged"]

    with fitz.open(stream=result["data"], filetype="pdf") as out:
        p = out[0]
        text = p.get_text()
        assert "工作成果" in text
        # 矢量圆点应已清掉
        small_arts = [dr for dr in p.get_drawings()
                      if dr["rect"].width <= 8 and dr["rect"].height <= 8]
        assert not small_arts, f"残留矢量圆点：{small_arts}"
        # 文字应前移到圆点列（≈130），而不是留在正文列（141）
        words = p.get_text("words")
        label_x = min(w[0] for w in words if "工" in w[4])
        assert label_x < 138, f"标签未前移：x={label_x}"


def test_replace_to_label_removes_text_dot(client):
    """文字圆点行替换成短标签：圆点字符清掉、文字提到圆点列。"""
    import fitz

    from resume_builder.services import pdf_patch

    d = fitz.open()
    page = d.new_page()
    page.insert_text((72, 100), "·", fontsize=10, fontname="helv")
    page.insert_text((82, 100), "维护招聘渠道及候选人资源,提高招聘效率。",
                     fontsize=10, fontname="china-s")
    rel = _write_source_pdf(d.tobytes(), "labeltext.pdf")

    old = {"skills": {"descriptions": ["维护招聘渠道及候选人资源,提高招聘效率。"]}}
    new = {"skills": {"descriptions": ["主要业绩:"]}}
    result = pdf_patch.patch_pdf(rel, old, new, [], design={"bulletStyle": "dot"})
    text = _pdf_text(result["data"])
    assert "主要业绩" in text and "·" not in text


def test_append_label_line_aligns_to_dot_column(client):
    """新增短标签行：插到锚点行之后，x 对齐圆点列而非正文列。"""
    import fitz

    from resume_builder.services import pdf_patch

    d = fitz.open()
    page = d.new_page()
    page.draw_circle((130, 100), 1.5, color=(0, 0, 0), fill=(0, 0, 0))
    page.insert_text((141.4, 100), "负责甲方客户相关安全服务业务实施。",
                     fontsize=9, fontname="china-s")
    rel = _write_source_pdf(d.tobytes(), "labeladd.pdf")

    old = {"skills": {"descriptions": ["负责甲方客户相关安全服务业务实施。"]}}
    new = {"skills": {"descriptions": ["负责甲方客户相关安全服务业务实施。",
                                        "工作成果:"]}}
    result = pdf_patch.patch_pdf(rel, old, new, [], design={"bulletStyle": "dot"})
    assert not result["unchanged"]
    with fitz.open(stream=result["data"], filetype="pdf") as out:
        words = out[0].get_text("words")
        label_x = min(w[0] for w in words if "工" in w[4] and "作" in w[4])
        assert label_x <= 132, f"新增标签未对齐圆点列：x={label_x}"


def test_is_label_line_boundaries():
    """标签行判定：短+冒号结尾；长句/无冒号/含句读的不算。"""
    from resume_builder.services.pdf_patch import _is_label_line

    assert _is_label_line("工作成果:")
    assert _is_label_line("主要业绩：")
    assert _is_label_line("E-mail:")
    assert not _is_label_line("负责甲方客户相关安全服务业务实施,漏洞扫描、安全加固等工作:")
    assert not _is_label_line("工作成果")           # 无冒号
    assert not _is_label_line("输出防病毒周/月报:")   # 含句读斜杠视为正文行
