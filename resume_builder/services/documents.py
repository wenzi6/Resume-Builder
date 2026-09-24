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
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
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
    return d


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
