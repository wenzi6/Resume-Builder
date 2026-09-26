"""数据安全回归：自动备份 / 全量导出 / 全量导入 / 恢复。"""
from __future__ import annotations

import io
import json
import zipfile

import pytest

from resume_builder.engine import pdf as pdf_engine
from resume_builder.sample import sample_general
from resume_builder.services import bundle, documents as store


@pytest.fixture()
def two_docs(client):
    """两份文档：一份普通、一份带原始 PDF（对照导入）。"""
    r = client.post("/api/v1/documents", json={"templateId": "classic", "title": "备份测试A"})
    a = r.get_json()["document"]
    r = client.post("/api/v1/documents", json={"templateId": "modern", "title": "备份测试B"})
    b = r.get_json()["document"]
    yield [a["id"], b["id"]]
    for d in (a["id"], b["id"]):
        client.delete(f"/api/v1/documents/{d}")


# ---------------- 自动备份 ----------------


def test_backup_creates_file(client, two_docs):
    name = bundle.backup_db(force=True)
    assert name and name.startswith("resumes-")
    assert (store.DB_PATH.parent / "backups" / name).is_file()


def test_backup_skips_unchanged(client, two_docs):
    assert bundle.backup_db(force=True)
    assert bundle.backup_db() is None  # 无变化 → 跳过


def test_backup_retention(client, two_docs):
    import time

    for i in range(bundle.MAX_BACKUPS + 3):
        bundle.backup_db(force=True)
        time.sleep(0.02)  # 保证文件名（秒级）不撞
    backups = bundle.list_backups()
    assert len(backups) <= bundle.MAX_BACKUPS
    assert backups[0]["createdAt"] >= backups[-1]["createdAt"]


def test_backup_list_fields(client, two_docs):
    bundle.backup_db(force=True)
    items = bundle.list_backups()
    assert items and "createdText" in items[0] and items[0]["size"] > 0


def test_restore_backup(client, two_docs):
    """恢复备份：数据回到备份时点。"""
    ids = two_docs
    bundle.backup_db(force=True)
    # 删掉一份再恢复
    client.delete(f"/api/v1/documents/{ids[0]}")
    docs = client.get("/api/v1/documents").get_json()["documents"]
    assert all(d["id"] != ids[0] for d in docs)
    name = bundle.list_backups()[0]["name"]
    assert bundle.restore_backup(name)
    docs2 = client.get("/api/v1/documents").get_json()["documents"]
    assert any(d["id"] == ids[0] for d in docs2), "恢复后文档应回来"


def test_restore_backup_traversal(client):
    assert bundle.restore_backup("../../etc/passwd") is False
    assert bundle.restore_backup("nonexistent.db") is False


# ---------------- 全量导出 / 导入 ----------------


def test_export_all_zip(client, two_docs):
    r = client.get("/api/v1/documents/export-all")
    assert r.status_code == 200
    data = r.get_data()
    assert data[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["count"] == 2
        assert any(n.endswith(".json") and n != "manifest.json" for n in names)


def test_export_import_roundtrip(client, two_docs):
    """导出 → 清库 → 导入 → 文档回来（含内容）。"""
    data = client.get("/api/v1/documents/export-all").get_data()
    for d in two_docs:
        client.delete(f"/api/v1/documents/{d}")
    assert client.get("/api/v1/documents").get_json()["documents"] == []

    r = client.post("/api/v1/documents/import-all",
                    data={"file": (io.BytesIO(data), "bundle.zip")},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    result = r.get_json()
    assert result["count"] == 2
    titles = {d["title"] for d in result["imported"]}
    assert titles == {"备份测试A", "备份测试B"}
    # 新 id（不覆盖语义）
    docs = client.get("/api/v1/documents").get_json()["documents"]
    assert {d["id"] for d in docs} != set(two_docs)


def test_import_all_with_source_pdf(client):
    """带原始 PDF 的文档：导出包含 PDF，导入后 PDF 恢复且可用。"""
    pdf_bytes = pdf_engine.render_pdf_bytes(sample_general())
    r = client.post("/api/v1/import/pdf",
                    data={"file": (io.BytesIO(pdf_bytes), "r.pdf")},
                    content_type="multipart/form-data")
    doc = r.get_json()["document"]
    client.put(f"/api/v1/documents/{doc['id']}", json={"document": doc})
    doc_id = doc["id"]

    data = client.get("/api/v1/documents/export-all").get_data()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        pdf_members = [n for n in zf.namelist() if n.startswith("pdfs/")]
    assert pdf_members, "导出应包含原始 PDF"

    client.delete(f"/api/v1/documents/{doc_id}")
    r2 = client.post("/api/v1/documents/import-all",
                     data={"file": (io.BytesIO(data), "bundle.zip")},
                     content_type="multipart/form-data")
    assert r2.status_code == 200
    new_id = r2.get_json()["imported"][0]["id"]
    loaded = client.get(f"/api/v1/documents/{new_id}").get_json()["document"]
    assert loaded.get("sourcePdf")
    assert (store.DATA_DIR / loaded["sourcePdf"]).is_file()
    client.delete(f"/api/v1/documents/{new_id}")


def test_import_all_bad_zip(client):
    r = client.post("/api/v1/documents/import-all",
                    data={"file": (io.BytesIO(b"not a zip"), "x.zip")},
                    content_type="multipart/form-data")
    assert r.status_code == 400


def test_import_all_wrong_ext(client):
    r = client.post("/api/v1/documents/import-all",
                    data={"file": (io.BytesIO(b"x"), "x.txt")},
                    content_type="multipart/form-data")
    assert r.status_code == 400


def test_import_all_empty_zip(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "nothing")
    r = client.post("/api/v1/documents/import-all",
                    data={"file": (io.BytesIO(buf.getvalue()), "empty.zip")},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    assert r.get_json()["count"] == 0


# ---------------- API：备份管理 ----------------


def test_api_backups_endpoints(client, two_docs):
    r = client.get("/api/v1/backups")
    assert r.status_code == 200
    assert r.get_json()["max"] == bundle.MAX_BACKUPS

    r = client.post("/api/v1/backups/now")
    assert r.status_code == 200
    assert r.get_json()["backup"]

    r = client.post("/api/v1/backups/restore", json={"name": "nope.db"})
    assert r.status_code == 404


# ---------------- 备份删除 ----------------


def test_delete_backup(client, two_docs):
    bundle.backup_db(force=True)
    name = bundle.list_backups()[0]["name"]
    r = client.delete(f"/api/v1/backups/{name}")
    assert r.status_code == 200
    assert all(b["name"] != name for b in client.get("/api/v1/backups").get_json()["backups"])


def test_delete_backup_traversal(client):
    assert client.delete("/api/v1/backups/..%2F..%2Fconfig.py").status_code == 404
    assert client.delete("/api/v1/backups/nonexistent.db").status_code == 404


def test_delete_backup_keeps_others(client, two_docs):
    import time

    bundle.backup_db(force=True)
    time.sleep(1.1)
    bundle.backup_db(force=True)
    backups = bundle.list_backups()
    assert len(backups) >= 2
    victim = backups[-1]["name"]
    keeper = backups[0]["name"]
    client.delete(f"/api/v1/backups/{victim}")
    names = [b["name"] for b in client.get("/api/v1/backups").get_json()["backups"]]
    assert victim not in names and keeper in names


# ---------------- 一键清空 ----------------

def test_clear_backups(client, two_docs):
    """一键清空全部备份。"""
    bundle.backup_db(force=True)
    # 同一秒内 backup_db 会因文件名相同而覆盖，手动补一份不同名的
    extra = bundle._backup_dir() / "resumes-20200101-000000.db"
    extra.write_bytes(b"%SQLite-x")
    before = bundle.list_backups()
    assert len(before) >= 2
    r = client.post("/api/v1/backups/clear")
    assert r.status_code == 200
    body = r.get_json()
    assert body["removed"] >= 2
    assert body["backups"] == []
    assert not extra.exists()


def test_clear_all_documents(client, tmp_path, monkeypatch):
    """一键清空全部简历（含版本与原始 PDF）。

    护栏：clear-all 是批量删除，隔离一旦失效就会毁掉真实数据——
    这里显式验证真实数据库的文档数不变（曾因漏 patch 模块级绑定出过事故）。
    """
    from resume_builder import config
    from resume_builder.services import documents as store

    real_db = store.DB_PATH
    real_count = None
    try:
        import sqlite3

        with sqlite3.connect(str(real_db)) as conn:
            real_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    except Exception:  # noqa: BLE001
        real_count = None

    ids = []
    for i in range(3):
        r = client.post("/api/v1/documents", json={"title": f"清空测试{i}"})
        ids.append(r.get_json()["document"]["id"])
    assert len(store.list_documents()) >= 3
    r = client.post("/api/v1/documents/clear-all")
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["removed"] >= 3
    assert client.get("/api/v1/documents").get_json()["documents"] == []

    if real_count is not None:
        import sqlite3

        with sqlite3.connect(str(real_db)) as conn:
            after = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        assert after == real_count, "clear-all 碰到了真实数据库！"
