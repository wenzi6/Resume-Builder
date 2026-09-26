"""API 端到端测试（从 api_e2e.py 整理为 pytest）。"""
from __future__ import annotations

import io
import zipfile

import pytest

from resume_builder.config import TEMPLATES_DIR

BUILTIN_TEMPLATES = {"ats-plain", "classic", "minimal", "modern", "professional", "tech"}


@pytest.fixture()
def sample_doc(client):
    r = client.post("/api/v1/documents/from-sample/general")
    assert r.status_code == 201
    return r.get_json()["document"]


# ---------------- 基础路由 ----------------

def test_healthz(client):
    assert client.get("/healthz").status_code == 200


def test_index_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "editor.html" in r.get_data(as_text=True) or "Resume Studio" in r.get_data(as_text=True)


def test_static_assets(client):
    assert client.get("/static/editor.css").status_code == 200
    assert client.get("/static/js/app.js").status_code == 200


def test_fonts_route(client):
    assert client.get("/fonts/NotoSansSC-Regular.ttf").status_code == 200


# ---------------- 模板与 schema ----------------

def test_templates_list(client):
    r = client.get("/api/v1/templates")
    assert r.status_code == 200
    tpls = r.get_json()
    assert len(tpls) == 6
    ids = {t["id"] for t in tpls}
    assert ids == BUILTIN_TEMPLATES
    for t in tpls:
        assert "defaultDesign" in t and "accent" in t["defaultDesign"]


def test_schema_sections(client):
    r = client.get("/api/v1/schema/sections")
    assert r.status_code == 200
    sc = r.get_json()
    assert len(sc["builtin"]) == 7
    assert "profile" in sc["builtinKeys"]
    for s in sc["builtin"]:
        assert s["key"] and s["title"] and s["type"] in (
            "object", "array", "skills", "free", "simple")


# ---------------- 文档 CRUD ----------------

def test_document_crud(client, sample_doc):
    doc_id = sample_doc["id"]
    assert client.get(f"/api/v1/documents/{doc_id}").status_code == 200

    full = dict(sample_doc)
    full["title"] = "改过的标题"
    r = client.put(f"/api/v1/documents/{doc_id}", json={"document": full})
    assert r.status_code == 200
    assert r.get_json()["document"]["title"] == "改过的标题"

    r = client.post(f"/api/v1/documents/{doc_id}/duplicate")
    assert r.status_code == 201
    copy_id = r.get_json()["document"]["id"]
    assert copy_id != doc_id

    assert client.delete(f"/api/v1/documents/{copy_id}").status_code == 200
    assert client.get(f"/api/v1/documents/{copy_id}").status_code == 404
    assert client.get("/api/v1/documents/不存在").status_code == 404


def test_from_sample_variants(client):
    for name in ("general", "tech"):
        r = client.post(f"/api/v1/documents/from-sample/{name}")
        assert r.status_code == 201
        doc = r.get_json()["document"]
        assert doc["title"].startswith("示例")
        assert len(doc["sections"]) == 7
        assert doc["content"]["profile"]["name"]
    assert client.post("/api/v1/documents/from-sample/nope").status_code == 400


# ---------------- 渲染与分页 ----------------

@pytest.mark.parametrize("tpl", ["classic", "modern", "minimal", "professional", "tech", "ats-plain"])
def test_render_all_templates(client, sample_doc, tpl):
    d = dict(sample_doc)
    d["templateId"] = tpl
    r = client.post("/api/v1/render", json={"document": d})
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "张三" in body
    assert "r-sheet" in body
    assert 'data-section="workExperiences"' in body


def test_page_info(client, sample_doc):
    r = client.post("/api/v1/page-info", json={"document": sample_doc})
    assert r.status_code == 200
    info = r.get_json()
    assert info["pageCount"] >= 1
    assert info["pageHeightPx"] > 0
    assert isinstance(info["sections"], list)
    assert isinstance(info["warnings"], list)


def test_auto_pagebreaks(client, sample_doc):
    r = client.post("/api/v1/auto-pagebreaks", json={"document": sample_doc})
    assert r.status_code == 200
    assert "pageBreaks" in r.get_json()


# ---------------- 导出 ----------------

@pytest.mark.parametrize("fmt,magic", [("pdf", b"%PDF"), ("docx", b"PK"), ("json", b"{")])
def test_export(client, sample_doc, fmt, magic):
    r = client.post(f"/api/v1/export/{fmt}", json={"document": sample_doc})
    assert r.status_code == 200
    assert r.get_data().startswith(magic)


def test_export_unknown_id_404(client):
    assert client.post("/api/v1/export/pdf", json={"id": "no-such-id"}).status_code == 404


# ---------------- 导入 ----------------

def test_import_json_v2(client, sample_doc):
    r = client.post("/api/v1/import/json", json=sample_doc)
    assert r.status_code == 200
    doc = r.get_json()["document"]
    # 导入必须换发新 id（避免覆盖库中同 id 的现有简历）
    assert doc["id"] != sample_doc["id"]
    assert doc["content"]["profile"]["name"] == "张三"


def test_import_json_v1_migration(client):
    v1 = {
        "_sections": [
            {"key": "profile", "title": "个人信息", "type": "object",
             "fields": [{"key": "name", "label": "姓名"}]},
            {"key": "workExperiences", "title": "工作经历", "type": "array",
             "fields": [{"key": "company", "label": "公司"}, {"key": "date", "label": "时间"},
                        {"key": "descriptions", "label": "职责", "isList": True}]},
        ],
        "profile": {"name": "王五", "title": "测试"},
        "workExperiences": [{"company": "A公司", "date": "2020-2021", "descriptions": ["做事"]}],
    }
    r = client.post("/api/v1/import/json", json=v1)
    assert r.status_code == 200
    doc = r.get_json()["document"]
    assert doc["content"]["profile"]["name"] == "王五"
    assert doc["content"]["workExperiences"][0]["company"] == "A公司"
    assert doc["content"]["workExperiences"][0]["descriptions"] == ["做事"]


def test_import_bad_json_400(client):
    r = client.post("/api/v1/import/json", data="{bad json", content_type="application/json")
    assert r.status_code == 400


def test_import_template_zip(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("layout.html", '<div class="r-sheet">{{profile.name}}</div>')
        zf.writestr("layout.css", "/* x */")
    buf.seek(0)
    r = client.post("/api/v1/import-template", data={"file": (buf, "mytpl.zip")},
                    content_type="multipart/form-data")
    assert r.status_code == 200


def test_import_template_zip_path_traversal(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../evil/layout.html", "<div>{{x}}</div>")
    buf.seek(0)
    r = client.post("/api/v1/import-template", data={"file": (buf, "evil.zip")},
                    content_type="multipart/form-data")
    assert r.status_code == 400


# ---------------- 旧版兼容层 ----------------

def test_legacy_endpoints(client, sample_doc):
    assert client.get("/api/templates").status_code == 200
    assert "profile" in client.get("/api/sample-data").get_json()

    d = dict(sample_doc)
    d["templateId"] = "classic"
    r = client.post("/api/preview/classic", json=d)
    assert r.status_code == 200 and "张三" in r.get_data(as_text=True)

    r = client.post("/api/export-pdf/classic", json=d)
    assert r.status_code == 200 and r.get_data()[:4] == b"%PDF"

    r = client.post("/api/export-word/classic", json=d)
    assert r.status_code == 200 and r.get_data()[:2] == b"PK"


# ---------------- 边界情况 ----------------

@pytest.mark.parametrize("body,ct", [
    ({}, "application/json"),
    ("not json", "text/plain"),
    ([1, 2, 3], "application/json"),
])
def test_render_bad_bodies(client, body, ct):
    r = client.post("/api/v1/render", json=body, content_type=ct) if ct == "application/json" \
        else client.post("/api/v1/render", data=body, content_type=ct)
    assert r.status_code in (200, 400)


def test_unknown_template_fallback(client, sample_doc):
    d = dict(sample_doc)
    d["templateId"] = "no-such-template"
    r = client.post("/api/v1/render", json={"document": d})
    assert r.status_code == 200


def test_import_pdf_no_file(client):
    r = client.post("/api/v1/import/pdf", data={}, content_type="multipart/form-data")
    assert r.status_code == 400


# ---------------- 清理 ----------------

@pytest.fixture(autouse=True)
def _cleanup_imported_templates():
    yield
    import shutil
    for p in TEMPLATES_DIR.iterdir():
        if p.is_dir() and p.name not in BUILTIN_TEMPLATES:
            shutil.rmtree(p, ignore_errors=True)


def test_template_preview_route(client):
    """模板预览图路由。"""
    r = client.get("/api/v1/templates/classic/preview.png")
    assert r.status_code == 200
    assert r.get_data()[:4] == b"\x89PNG"
    assert client.get("/api/v1/templates/nope/preview.png").status_code == 404
    assert client.get("/api/v1/templates/classic/preview.png").headers["Content-Type"].startswith("image/")


# ---------------- 运行日志 API ----------------

def test_logs_client_error_recorded(client):
    r = client.post("/api/v1/logs/client", json={
        "message": "__test_client_error__", "source": "test", "lineno": 1, "colno": 2,
    })
    assert r.status_code == 200
    r2 = client.get("/api/v1/logs/tail?lines=50")
    assert r2.status_code == 200
    body = r2.get_json()
    assert any("__test_client_error__" in l for l in body["lines"]), body["lines"][-3:]
    assert body["path"].endswith("resume-studio.log")


def test_logs_client_requires_message(client):
    assert client.post("/api/v1/logs/client", json={}).status_code == 400


def test_unhandled_exception_returns_json_500(client, monkeypatch):
    """未捕获异常：统一 JSON 500 + 落日志（不返回 HTML 错误页）。"""
    from resume_builder.services import documents as store

    def boom(*a, **k):
        raise RuntimeError("__test_boom__")

    monkeypatch.setattr(store, "list_documents", boom)
    r = client.get("/api/v1/documents")
    assert r.status_code == 500
    body = r.get_json()
    assert body and "error" in body and body.get("logged") is True
