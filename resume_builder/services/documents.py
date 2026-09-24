"""文档持久化：SQLite。

编辑器自动保存到本地数据库，保证长期使用不丢数据。
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ..config import DB_PATH
from ..schema import normalize_document

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
            "SELECT id, title, template_id, created_at, updated_at FROM documents "
            "ORDER BY updated_at DESC"
        ).fetchall()
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "templateId": r["template_id"],
            "createdAt": r["created_at"],
            "updatedAt": r["updated_at"],
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
    with _db() as conn:
        cur = conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    return cur.rowcount > 0


def duplicate_document(doc_id: str) -> dict[str, Any] | None:
    src = get_document(doc_id)
    if not src:
        return None
    src["id"] = ""
    src["title"] = f"{src['title']} 副本"
    from ..schema import new_document

    fresh = new_document(template_id=src["templateId"], title=src["title"])
    fresh.update({k: v for k, v in src.items() if k not in ("id", "title")})
    return save_document(fresh)
