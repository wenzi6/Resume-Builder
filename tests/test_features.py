"""Phase 2 优化功能回归：字体上传 / 自动适应 / HTML 导出 / 版本历史 / 导出自检。"""
from __future__ import annotations

import io
import json
import time

import pytest

from resume_builder.engine import pdf as pdf_engine
from resume_builder.sample import sample_general, sample_tech


# ---------------- 用户字体 ----------------

@pytest.fixture()
def uploaded_font(client):
    """上传一个内置 TTF 作为用户字体，结束后清理。"""
    from resume_builder.services import font_manager

    with open(font_manager.USER_FONTS_DIR.parent / "NotoSansSC-Bold.ttf", "rb") as f:
        data = f.read()
    r = client.post(
        "/api/v1/fonts/upload",
        data={"file": (io.BytesIO(data), "TestFont.ttf")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    info = r.get_json()["font"]
    yield info
    client.delete(f"/api/v1/fonts/{info['file']}")


def test_font_upload_and_list(client, uploaded_font):
    fonts = client.get("/api/v1/fonts").get_json()
    assert uploaded_font["family"] in fonts["families"]
    assert any(f["file"] == uploaded_font["file"] for f in fonts["user"])


def test_font_upload_rejects_non_font(client):
    r = client.post(
        "/api/v1/fonts/upload",
        data={"file": (io.BytesIO(b"garbage"), "bad.ttf")},
        content_type="multipart/form-data",
    )
    assert r.status_code in (400, 500)


def test_font_delete_traversal(client):
    r = client.delete("/api/v1/fonts/..%2F..%2Fconfig.py")
    assert r.status_code == 404


def test_render_with_user_font(client, uploaded_font):
    doc = sample_general()
    doc["design"]["fontFamily"] = uploaded_font["family"]
    r = client.post("/api/v1/render", json={"document": doc})
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert f"font-family: '{uploaded_font['family']}'" in html
    assert f"user/{uploaded_font['file']}" in html


def test_pdf_export_with_user_font_is_type0(client, uploaded_font):
    """用户字体必须可嵌入（Type0），这是字体管线的核心保证。"""
    doc = sample_general()
    doc["design"]["fontFamily"] = uploaded_font["family"]
    r = client.post("/api/v1/export/pdf", json={"document": doc})
    assert r.status_code == 200
    check = pdf_engine.verify_pdf_fonts(r.get_data())
    assert check["type3"] == []
    assert check["ok"]


def test_unregistered_font_falls_back(client):
    doc = sample_general()
    doc["design"]["fontFamily"] = "NoSuchFont"
    r = client.post("/api/v1/render", json={"document": doc})
    assert r.status_code == 200
    assert "resume-font-sans" in r.get_data(as_text=True)


# ---------------- 自动适应一页 ----------------

def test_auto_fit_compresses_to_one_page(client):
    r = client.post("/api/v1/auto-fit", json={"document": sample_tech()})
    assert r.status_code == 200
    result = r.get_json()
    assert result["fitted"] is True
    assert result["pageCount"] == 1
    assert result["steps"] >= 1
    design = result["design"]
    # 压缩后的参数必须仍合法
    assert 0.80 <= design["fontScale"] <= 1.15
    assert 1.20 <= design["lineHeight"] <= 1.80
    assert 12.7 <= design["pageMargin"] <= 25


def test_auto_fit_one_page_doc_noop(client):
    r = client.post("/api/v1/auto-fit", json={"document": sample_general()})
    assert r.status_code == 200
    result = r.get_json()
    assert result["fitted"] is True
    assert result["steps"] == 0


def test_auto_fit_respects_tighter_current_design(client):
    """当前设计已比阶梯更紧时，从当前值继续下探（不回弹）。"""
    doc = sample_tech()
    doc["design"] = {"fontScale": 0.86, "lineHeight": 1.25, "sectionGap": 9, "pageMargin": 13.5}
    r = client.post("/api/v1/auto-fit", json={"document": doc})
    assert r.status_code == 200
    design = r.get_json()["design"]
    assert design["fontScale"] <= 0.86


# ---------------- HTML 自包含导出 ----------------

def test_export_html_self_contained(client):
    doc = sample_general()
    r = client.post("/api/v1/export/html", json={"document": doc})
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "data:font/ttf;base64," in html          # 字体已内嵌
    assert "url('/fonts/" not in html                # 不再依赖服务端路由
    assert "张三" in html


def test_export_html_opens_without_server(client, tmp_path):
    """导出的 HTML 不依赖网络：file:// 打开也能渲染（用 Playwright 验证）。"""
    doc = sample_general()
    r = client.post("/api/v1/export/html", json={"document": doc})
    path = tmp_path / "resume.html"
    path.write_bytes(r.get_data())

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page()
        page.goto(path.as_uri())
        page.wait_for_timeout(1200)
        name = page.evaluate("document.querySelector('.r-name')?.textContent")
        font_loaded = page.evaluate("document.fonts.status")
        b.close()
    assert name == "张三"
    assert font_loaded == "loaded"


# ---------------- 版本历史 ----------------

def test_versions_created_and_listed(client):
    r = client.post("/api/v1/documents/from-sample/general")
    doc = r.get_json()["document"]
    doc_id = doc["id"]
    # 改两次 → 至少两份快照
    for title in ("版本A", "版本B"):
        d = dict(doc)
        d["title"] = title
        client.put(f"/api/v1/documents/{doc_id}", json={"document": d})
        doc = client.get(f"/api/v1/documents/{doc_id}").get_json()["document"]
        time.sleep(0.05)

    versions = client.get(f"/api/v1/documents/{doc_id}/versions").get_json()["versions"]
    assert len(versions) >= 2
    titles = [v["title"] for v in versions]
    assert "版本B" in titles and "版本A" in titles
    # 新→旧
    assert versions[0]["savedAt"] >= versions[-1]["savedAt"]


def test_version_restore(client):
    r = client.post("/api/v1/documents/from-sample/general")
    doc = r.get_json()["document"]
    doc_id = doc["id"]

    d = dict(doc)
    d["title"] = "要恢复的版本"
    client.put(f"/api/v1/documents/{doc_id}", json={"document": d})
    time.sleep(0.05)

    d2 = dict(doc)
    d2["title"] = "后来的修改"
    client.put(f"/api/v1/documents/{doc_id}", json={"document": d2})
    time.sleep(0.05)

    versions = client.get(f"/api/v1/documents/{doc_id}/versions").get_json()["versions"]
    target = next(v for v in versions if v["title"] == "要恢复的版本")
    r2 = client.post(f"/api/v1/documents/{doc_id}/versions/{target['id']}/restore")
    assert r2.status_code == 200
    assert r2.get_json()["document"]["title"] == "要恢复的版本"
    current = client.get(f"/api/v1/documents/{doc_id}").get_json()["document"]
    assert current["title"] == "要恢复的版本"


def test_versions_unknown_doc_404(client):
    assert client.get("/api/v1/documents/nope/versions").status_code == 404
    assert client.post("/api/v1/documents/nope/versions/1/restore").status_code == 404


def test_versions_capped(client):
    """快照数量有上限（MAX_VERSIONS），不会无限增长。"""
    from resume_builder.services import documents as store

    r = client.post("/api/v1/documents", json={"templateId": "classic", "title": "上限测试"})
    doc = r.get_json()["document"]
    doc_id = doc["id"]
    for i in range(store.MAX_VERSIONS + 6):
        d = dict(doc)
        d["title"] = f"t{i}"
        client.put(f"/api/v1/documents/{doc_id}", json={"document": d})
        doc = client.get(f"/api/v1/documents/{doc_id}").get_json()["document"]
        time.sleep(0.02)
    versions = client.get(f"/api/v1/documents/{doc_id}/versions").get_json()["versions"]
    assert len(versions) <= store.MAX_VERSIONS


# ---------------- 导出质量自检 ----------------

def test_export_pdf_no_warning_header_on_good_template(client):
    r = client.post("/api/v1/export/pdf", json={"document": sample_general()})
    assert r.status_code == 200
    assert "X-Resume-Warnings" not in r.headers


def test_export_pdf_warning_on_type3(client, monkeypatch):
    """模拟 Type3 降级时，响应必须带警告头（前端据此提示用户）。"""
    import urllib.parse

    from resume_builder.api import export as export_api

    def fake_verify(_data):
        return {"type3": ["(unnamed)"], "textExtractable": False, "ok": False, "fonts": [], "types": {}, "textSample": ""}

    monkeypatch.setattr(pdf_engine, "verify_pdf_fonts", fake_verify)
    r = client.post("/api/v1/export/pdf", json={"document": sample_general()})
    assert r.status_code == 200
    header = r.headers.get("X-Resume-Warnings")
    assert header
    warnings = json.loads(urllib.parse.unquote(header))
    assert any("Type3" in w for w in warnings)


def test_photo_scheme_validation(client):
    """photo 字段拒绝 file:// 等危险 scheme。"""
    from resume_builder.engine.renderer import render_preview

    doc = sample_general()
    doc["content"]["profile"]["photo"] = "file:///C:/Windows/win.ini"
    doc["design"]["showPhoto"] = True
    html = render_preview(doc)
    assert "win.ini" not in html

    doc["content"]["profile"]["photo"] = "https://example.com/a.jpg"
    html2 = render_preview(doc)
    assert "example.com/a.jpg" in html2
