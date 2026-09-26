"""文档持久化：SQLite。

编辑器自动保存到本地数据库，保证长期使用不丢数据。
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ..config import DB_PATH, DATA_DIR
from ..schema import normalize_document
from .. import logging_setup

logger = logging_setup.get_logger("documents")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL DEFAULT '',
    template_id TEXT NOT NULL DEFAULT 'classic',
    data       TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_updated ON documents(updated_at DESC);

-- 文档历史快照（每次保存自动存档，每份文档保留最近 MAX_VERSIONS 份）
CREATE TABLE IF NOT EXISTS document_versions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id     TEXT NOT NULL,
    saved_at   REAL NOT NULL,
    title      TEXT NOT NULL DEFAULT '',
    data       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_versions_doc ON document_versions(doc_id, saved_at DESC);
"""

# 每份文档保留的历史快照数量
MAX_VERSIONS = 20


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # 并发读写不互斥
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _db() as conn:
        conn.executescript(_SCHEMA)


def list_documents() -> list[dict[str, Any]]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT id, title, template_id, created_at, updated_at, "
            "(json_extract(data, '$.sourcePdf') IS NOT NULL) AS has_source_pdf "
            "FROM documents ORDER BY updated_at DESC"
        ).fetchall()
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "templateId": r["template_id"],
            "createdAt": r["created_at"],
            "updatedAt": r["updated_at"],
            "hasSourcePdf": bool(r["has_source_pdf"]),
        }
        for r in rows
    ]


def get_document(doc_id: str) -> dict[str, Any] | None:
    with _db() as conn:
        row = conn.execute("SELECT data FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if not row:
        return None
    try:
        return normalize_document(json.loads(row["data"]))
    except (json.JSONDecodeError, ValueError):
        return None


def save_document(doc: dict[str, Any]) -> dict[str, Any]:
    d = normalize_document(doc)
    d["updatedAt"] = time.time()
    with _db() as conn:
        conn.execute(
            "INSERT INTO documents (id, title, template_id, data, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET title = excluded.title, "
            "template_id = excluded.template_id, data = excluded.data, "
            "updated_at = excluded.updated_at",
            (d["id"], d["title"], d["templateId"], json.dumps(d, ensure_ascii=False),
             d["createdAt"], d["updatedAt"]),
        )
        # 历史快照：内容有变化才存档，并裁剪到最近 MAX_VERSIONS 份
        last = conn.execute(
            "SELECT data FROM document_versions WHERE doc_id = ? ORDER BY saved_at DESC LIMIT 1",
            (d["id"],),
        ).fetchone()
        if not last or last["data"] != json.dumps(d, ensure_ascii=False):
            conn.execute(
                "INSERT INTO document_versions (doc_id, saved_at, title, data) VALUES (?, ?, ?, ?)",
                (d["id"], d["updatedAt"], d["title"], json.dumps(d, ensure_ascii=False)),
            )
            conn.execute(
                "DELETE FROM document_versions WHERE doc_id = ? AND id NOT IN ("
                "  SELECT id FROM document_versions WHERE doc_id = ? "
                "  ORDER BY saved_at DESC LIMIT ?)",
                (d["id"], d["id"], MAX_VERSIONS),
            )
    return d


def list_versions(doc_id: str) -> list[dict[str, Any]]:
    """文档历史快照列表（新→旧）。"""
    with _db() as conn:
        rows = conn.execute(
            "SELECT id, saved_at, title FROM document_versions WHERE doc_id = ? "
            "ORDER BY saved_at DESC LIMIT ?",
            (doc_id, MAX_VERSIONS),
        ).fetchall()
    return [{"id": r["id"], "savedAt": r["saved_at"], "title": r["title"]} for r in rows]


def restore_version(doc_id: str, version_id: int) -> dict[str, Any] | None:
    """把某份历史快照恢复为当前文档（重新走保存，生成新快照）。"""
    with _db() as conn:
        row = conn.execute(
            "SELECT data FROM document_versions WHERE id = ? AND doc_id = ?",
            (version_id, doc_id),
        ).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row["data"])
    except json.JSONDecodeError:
        return None
    data["id"] = doc_id
    return save_document(data)


def delete_document(doc_id: str) -> bool:
    doc = get_document(doc_id)
    if not doc:
        return False
    _remove_source_pdf(doc)
    with _db() as conn:
        cur = conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        conn.execute("DELETE FROM document_versions WHERE doc_id = ?", (doc_id,))
    return cur.rowcount > 0


def duplicate_document(doc_id: str) -> dict[str, Any] | None:
    src = get_document(doc_id)
    if not src:
        return None
    src["id"] = ""
    src["title"] = f"{src['title']} 副本"
    # 原始 PDF 参照复制一份独立文件（避免删一份简历影响另一份）
    new_pdf = _copy_source_pdf(src.get("sourcePdf"))
    if new_pdf:
        src["sourcePdf"] = new_pdf
    else:
        src.pop("sourcePdf", None)
    from ..schema import new_document

    fresh = new_document(template_id=src["templateId"], title=src["title"])
    fresh.update({k: v for k, v in src.items() if k not in ("id", "title")})
    return save_document(fresh)


# ---------------------------------------------------------------- 原始 PDF 附件


def _imports_dir() -> Path:
    d = DATA_DIR / "imports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_source_pdf(rel: str) -> bool:
    return bool(rel) and ".." not in rel.split("/") and not rel.startswith(("/", "\\")) and ":" not in rel


def _remove_source_pdf(doc: dict[str, Any]) -> None:
    rel = doc.get("sourcePdf")
    if not isinstance(rel, str) or not _safe_source_pdf(rel):
        return
    # 页面图片缓存一并清理
    from . import source_pdf

    source_pdf.delete_pages(rel)
    path = DATA_DIR / rel
    # Windows 下文件可能被读取句柄短暂锁定（如 /data/ 路由刚发完），重试几次
    for _ in range(3):
        try:
            path.unlink(missing_ok=True)
            return
        except OSError:
            time.sleep(0.15)


def sweep_orphan_source_pdfs(max_age_s: int = 3600) -> int:
    """清理没有文档引用的原始 PDF（删除失败的残留 / 异常中断的孤儿）。

    只清理修改时间超过 max_age_s 的文件，避免误删刚上传正在处理的文件。
    """
    imports = DATA_DIR / "imports"
    if not imports.is_dir():
        return 0
    try:
        with _db() as conn:
            rows = conn.execute("SELECT data FROM documents").fetchall()
    except sqlite3.OperationalError:
        return 0  # 表还未建（极早期调用）
    # 安全阀：一条文档都没有时绝不清扫。空库 + 有文件的 imports 目录只意味着\    # 异常（连错了库 / 迁移中途），此时删光文件等于数据事故。
    if not rows:
        return 0
    referenced = set()
    for r in rows:
        try:
            d = json.loads(r["data"])
        except (json.JSONDecodeError, KeyError):
            continue
        rel = d.get("sourcePdf")
        if isinstance(rel, str):
            referenced.add(rel.rsplit("/", 1)[-1])
    now = time.time()
    removed = 0
    for p in imports.glob("*.pdf"):
        if p.name in referenced:
            continue
        try:
            if now - p.stat().st_mtime > max_age_s:
                p.unlink()
                removed += 1
                logger.info("清理未引用的原始 PDF：%s", p.name)
        except OSError:
            continue
    # 页面图片缓存：目录名 = PDF stem，无引用的一并清掉
    pages_root = imports / "pages"
    if pages_root.is_dir():
        for d in pages_root.iterdir():
            if d.is_dir() and f"{d.name}.pdf" not in referenced:
                try:
                    if now - d.stat().st_mtime > max_age_s:
                        shutil.rmtree(d, ignore_errors=True)
                        removed += 1
                except OSError:
                    continue
    return removed


def _copy_source_pdf(rel: Any) -> str | None:
    if not isinstance(rel, str) or not _safe_source_pdf(rel):
        return None
    src = DATA_DIR / rel
    if not src.is_file():
        return None
    import shutil
    import uuid

    dst = _imports_dir() / f"{uuid.uuid4().hex}.pdf"
    shutil.copy2(src, dst)
    return f"imports/{dst.name}"
