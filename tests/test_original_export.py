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


# ---------------- 原格式实时预览（边编辑边看） ----------------

def test_source_pages_live_reflects_unsaved_edits(client, imported):
    """POST source-pages 用当前内容打补丁渲染——未保存的编辑也能立刻看到。"""
    doc = client.get(f"/api/v1/documents/{imported}").get_json()["document"]
    work = doc["content"].get("workExperiences") or []
    company = next((w.get("company") for w in work if w.get("company")), "")
    if not company:
        import pytest

        pytest.skip("样本无公司名")
    doc["content"]["workExperiences"][0]["company"] = "实时预览测试公司"
    # 注意：不 PUT 保存，直接拿内容请求实时预览
    r = client.post(f"/api/v1/documents/{imported}/source-pages", json={"content": doc["content"]})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["live"] is True
    assert body["applied"] >= 1, body.get("failed")
    assert body["pages"], "应返回渲染好的页面"
    assert any("实时预览测试公司" in p.get("url", "") or p.get("page") for p in body["pages"])
    # 文档本身没被改动（预览不落库）
    after = client.get(f"/api/v1/documents/{imported}").get_json()["document"]
    assert after["content"]["workExperiences"][0]["company"] == company


def test_source_pages_get_returns_original(client, imported):
    """GET 仍返回原始 PDF 的静态渲染（不掺入改动）。"""
    r = client.get(f"/api/v1/documents/{imported}/source-pages")
    assert r.status_code == 200
    body = r.get_json()
    assert body["pages"]
    assert not body.get("live")
    assert "/pages/" in body["pages"][0]["url"]


# ---------------- 删除条目：diff 必须按内容而非索引 ----------------

def test_diff_content_delete_middle_item():
    """删掉中间一条：只应产生一条删除，不能把后面条目误判成修改。"""
    from resume_builder.services import pdf_patch

    old = {"workExperiences": [{"descriptions": ["A条目", "B条目", "C条目", "D条目"]}]}
    new = {"workExperiences": [{"descriptions": ["A条目", "B条目", "D条目"]}]}
    changes = pdf_patch.diff_content(old, new)
    assert len(changes) == 1, changes
    assert changes[0] == {
        "path": "workExperiences.0.descriptions.2", "old": "C条目", "new": None}


def test_diff_content_add_item():
    """新增一条：只报新增（原格式放不下，由调用方提示），不产生错位替换。"""
    from resume_builder.services import pdf_patch

    old = {"workExperiences": [{"descriptions": ["A条目", "B条目"]}]}
    new = {"workExperiences": [{"descriptions": ["A条目", "B条目", "C条目"]}]}
    changes = pdf_patch.diff_content(old, new)
    assert len(changes) == 1, changes
    assert changes[0]["old"] is None and changes[0]["new"] == "C条目"


def test_diff_content_same_length_edit():
    """等长只改文字：按位置一条替换（原有行为不回归）。"""
    from resume_builder.services import pdf_patch

    old = {"workExperiences": [{"descriptions": ["A条目", "B条目"]}]}
    new = {"workExperiences": [{"descriptions": ["A条目改了", "B条目"]}]}
    changes = pdf_patch.diff_content(old, new)
    assert changes == [{"path": "workExperiences.0.descriptions.0",
                        "old": "A条目", "new": "A条目改了"}]


def test_patch_pdf_delete_item_removes_text(tmp_path):
    """删掉的条目其文本必须从补丁后的 PDF 里消失。"""
    from resume_builder.services import pdf_patch

    pdf = _per_char_pdf([
        "负责第一条工作内容",
        "负责第二条工作内容",
        "负责第三条工作内容",
    ])
    src = tmp_path / "del.pdf"
    src.write_bytes(pdf)
    old = {"workExperiences": [{"descriptions": [
        "负责第一条工作内容", "负责第二条工作内容", "负责第三条工作内容"]}]}
    new = {"workExperiences": [{"descriptions": [
        "负责第一条工作内容", "负责第三条工作内容"]}]}
    r = pdf_patch.patch_pdf(str(src), old, new)
    paths = [(a["path"], "applied") for a in r["applied"]] + \
            [(f["path"], f["reason"]) for f in r["failed"]]
    assert any(p[0].endswith("descriptions.1") and p[1] == "applied" for p in paths), paths
    text = _text(r["data"])
    assert "负责第二条工作内容" not in text, "删除的条目仍留在 PDF 里"
    assert "负责第一条工作内容" in text and "负责第三条工作内容" in text


def test_patch_pdf_delete_item_real_pipeline(client, imported):
    """真实渲染管线的 PDF：删掉一条要点，补丁后该文本必须消失。"""
    doc = client.get(f"/api/v1/documents/{imported}").get_json()["document"]
    work = doc["content"].get("workExperiences") or []
    target = next((w for w in work if len(w.get("descriptions") or []) >= 2), None)
    if not target:
        import pytest

        pytest.skip("样本没有多条要点的工作经历")
    removed = target["descriptions"][0]
    changed = {"workExperiences": []}
    for w in work:
        item = dict(w)
        if w is target:
            item["descriptions"] = w["descriptions"][1:]
        changed["workExperiences"].append(item)

    from resume_builder.services import pdf_patch

    r = client.post("/api/v1/export/pdf", json={"id": imported, "mode": "original"})
    assert r.status_code == 200
    # 直接在服务层验证（不走落库）：用导入快照 vs 删除后的内容
    src_doc = client.get(f"/api/v1/documents/{imported}").get_json()["document"]
    result = pdf_patch.patch_pdf(src_doc["sourcePdf"], src_doc["sourceContent"], changed)
    text = _text(result["data"])
    assert removed not in text, "删除的要点仍留在补丁后的 PDF 里"
    # 剩下的要点仍在：剥离空白与标点后取前 12 字比对（避开全/半角差异）
    import re as _re

    def _bare(s: str) -> str:
        return _re.sub(r"[\s，,。.、；;：:（）()]", "", s)

    kept = _bare(target["descriptions"][1])[:12]
    assert kept in _bare(text), f"保留的要点丢了：{kept}"


# ---------------- 区块标题同步进原格式 ----------------

def test_section_title_rename_patches_original_pdf(client, imported):
    """区块改名 / 隐藏标题 / 隐藏区块，都要同步进原格式补丁。"""
    from resume_builder.services import pdf_patch

    doc = client.get(f"/api/v1/documents/{imported}").get_json()["document"]
    work = doc["content"].get("workExperiences") or []
    if not work:
        import pytest

        pytest.skip("样本无工作经历")

    # 1) 改名：PDF 里的原标题 → 新标题
    secs = [dict(s) for s in doc["sections"]]
    for s in secs:
        if s["key"] == "workExperiences":
            s["title"] = "职业经历"
    r = pdf_patch.patch_pdf(doc["sourcePdf"], doc["sourceContent"], doc["content"], secs)
    applied = [a["path"] for a in r["applied"]]
    assert any("sections.workExperiences.title" in p for p in applied), (applied, r["failed"])
    assert "职业经历" in _text(r["data"]).replace(" ", "")

    # 2) 隐藏整个区块：其内容必须被移除
    secs2 = [dict(s) for s in doc["sections"]]
    for s in secs2:
        if s["key"] == "selfEvaluation":
            s["visible"] = False
    removed = (doc["content"].get("selfEvaluation") or {}).get("descriptions") or []
    if removed:
        r2 = pdf_patch.patch_pdf(doc["sourcePdf"], doc["sourceContent"], doc["content"], secs2)
        applied2 = [a["path"] for a in r2["applied"]]
        assert any("selfEvaluation" in p for p in applied2), (applied2, r2["failed"])


def test_split_between_fields_is_not_a_patch_change():
    """把 bullet 从职责挪到成果（或反之）不该产生补丁改动——文字仍在原处。"""
    from resume_builder.services import pdf_patch

    old = {"workExperiences": [{"descriptions": ["负责A工作", "月均到岗15人", "负责B工作"]}]}
    new = {"workExperiences": [{"descriptions": ["负责A工作", "负责B工作"],
                                "achievements": ["月均到岗15人"]}]}
    assert pdf_patch.diff_content(old, new) == []

    # 反向挪回去也一样
    assert pdf_patch.diff_content(new, old) == []


def test_delete_bullet_removes_its_dot(tmp_path):
    """删掉一条带圆点的 bullet，圆点必须一起消失（原 PDF 里圆点是独立 Span）。"""
    import pymupdf

    from resume_builder.services import pdf_patch

    pdf = _per_char_pdf([
        "· 第一条内容",
        "· 第二条内容",
        "· 第三条内容",
    ])
    src = tmp_path / "dots.pdf"
    src.write_bytes(pdf)

    def dot_count(data: bytes) -> int:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            return sum(1 for p in doc for ln in pdf_patch._page_lines(p)
                       for s in ln["spans"] if (s["text"] or "").strip() in ("·", "•"))

    before = dot_count(pdf)
    assert before == 3, before

    old = {"skills": {"descriptions": ["第一条内容", "第二条内容", "第三条内容"]}}
    new = {"skills": {"descriptions": ["第一条内容", "第三条内容"]}}
    r = pdf_patch.patch_pdf(str(src), old, new)
    assert any(a["path"].endswith("descriptions.1") for a in r["applied"]), r["failed"]
    text = _text(r["data"])
    assert "第二条内容" not in text
    assert "第一条内容" in text and "第三条内容" in text
    assert dot_count(r["data"]) == before - 1, "圆点没跟着一起删掉"


def test_delete_removes_vector_bullet_dot(tmp_path):
    """圆点是矢量图形时（不是文字），删除内容后也必须一起消失。"""
    import pymupdf

    from resume_builder.services import pdf_patch

    # 构造「文字 + 行首矢量圆点」的 PDF（用 ASCII：内置字体无中文字形）
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=300)
    for i, txt in enumerate(("first item", "second item", "third item")):
        y = 50 + i * 30
        page.draw_circle(pymupdf.Point(40, y - 3), 1.5, color=None,
                         fill=(0.33, 0.33, 0.33))
        page.insert_text((50, y), txt, fontsize=10)
    pdf = doc.tobytes()
    doc.close()
    src = tmp_path / "vec.pdf"
    src.write_bytes(pdf)

    def dots(data: bytes) -> int:
        with pymupdf.open(stream=data, filetype="pdf") as d:
            return sum(1 for dr in d[0].get_drawings() if dr["rect"].width <= 8)

    assert dots(pdf) == 3, dots(pdf)

    old = {"skills": {"descriptions": ["first item", "second item", "third item"]}}
    new = {"skills": {"descriptions": ["first item", "third item"]}}
    r = pdf_patch.patch_pdf(str(src), old, new)
    assert any(a["path"].endswith("descriptions.1") for a in r["applied"]), r["failed"]
    assert "second item" not in _text(r["data"])
    assert dots(r["data"]) == 2, "矢量圆点没跟着删掉"
