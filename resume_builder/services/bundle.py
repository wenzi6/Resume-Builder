"""数据安全：自动备份 + 全量导入导出（ZIP 捆绑）。

- 备份用 SQLite 的 backup API（一致性快照，不怕写到一半），保留最近 N 份
- 导出全部：每份文档一个 JSON + 关联的原始 PDF + manifest，换机器可整体迁移
- 导入全部：ZIP 内 JSON 全部作为新文档导入（不覆盖现有），路径不落盘无穿越风险
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import sqlite3
import time
import zipfile
from pathlib import Path
from typing import Any

from .. import config
from ..schema import normalize_document
from . import documents as _store


def _db_path() -> Path:
    """运行时读取（测试会 monkeypatch store.DB_PATH）。"""
    return _store.DB_PATH


def _data_dir() -> Path:
    """运行时读取（测试会 monkeypatch config.DATA_DIR）。"""
    return config.DATA_DIR


BACKUP_DIR_NAME = "backups"
MAX_BACKUPS = 10


# ---------------------------------------------------------------- 备份


def _backup_dir() -> Path:
    d = _db_path().parent / BACKUP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _md5_file(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def _db_signature(path: Path) -> tuple:
    """数据库逻辑签名（内容变了才变；SQLite 备份文件布局不同，不能比对字节）。"""
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return ()
    try:
        docs = conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(updated_at), 0) FROM documents").fetchone()
        try:
            vers = conn.execute(
                "SELECT COUNT(*), COALESCE(MAX(saved_at), 0) FROM document_versions").fetchone()
        except sqlite3.OperationalError:
            vers = (0, 0)
        return (tuple(docs), tuple(vers))
    except sqlite3.Error:
        return ()
    finally:
        conn.close()


def backup_db(force: bool = False) -> str | None:
    """一致性备份数据库，返回备份文件名；内容无变化时跳过（除非 force）。"""
    db_path = _db_path()
    if not db_path.exists():
        return None
    if not force:
        sig = _db_signature(db_path)
        latest = sorted(_backup_dir().glob("resumes-*.db"),
                        key=lambda x: x.stat().st_mtime, reverse=True)[:1]
        if sig and latest and _db_signature(latest[0]) == sig:
            return None
    name = f"resumes-{time.strftime('%Y%m%d-%H%M%S')}.db"
    dst = _backup_dir() / name
    src = sqlite3.connect(str(db_path))
    try:
        out = sqlite3.connect(str(dst))
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()
    for p in sorted(_backup_dir().glob("resumes-*.db"),
                    key=lambda x: x.stat().st_mtime, reverse=True)[MAX_BACKUPS:]:
        try:
            p.unlink()
        except OSError:
            pass
    return name


def list_backups() -> list[dict[str, Any]]:
    """备份列表（新→旧）。"""
    out = []
    for p in sorted(_backup_dir().glob("resumes-*.db"),
                    key=lambda x: x.stat().st_mtime, reverse=True):
        st = p.stat()
        out.append({
            "name": p.name,
            "size": st.st_size,
            "createdAt": st.st_mtime,
            "createdText": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
        })
    return out


def restore_backup(name: str) -> bool:
    """用指定备份覆盖当前数据库。"""
    if not name or "/" in name or "\\" in name or ".." in name:
        return False
    src = _backup_dir() / name
    if not src.is_file():
        return False
    dst = sqlite3.connect(str(_db_path()))
    try:
        source = sqlite3.connect(str(src))
        try:
            source.backup(dst)
        finally:
            source.close()
    finally:
        dst.close()
    return True


def delete_backup(name: str) -> bool:
    """删除指定备份（防路径穿越）。"""
    if not name or "/" in name or "\\" in name or ".." in name:
        return False
    if not name.startswith("resumes-") or not name.endswith(".db"):
        return False
    p = _backup_dir() / name
    if not p.is_file():
        return False
    try:
        p.unlink()
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- 全量导出 / 导入


def export_all() -> bytes:
    """全部文档导出为 ZIP（JSON + 原始 PDF + manifest）。"""
    with _store._db() as conn:
        rows = conn.execute("SELECT id, data FROM documents").fetchall()
    buf = io.BytesIO()
    manifest: dict[str, Any] = {"format": "resume-studio-bundle", "count": 0, "documents": []}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in rows:
            try:
                doc = json.loads(r["data"])
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
            title = re.sub(r"[\\/:*?\"<>|]", "_", str(doc.get("title") or "resume"))[:40]
            fname = f"{title}-{r['id'][:8]}.json"
            zf.writestr(fname, json.dumps(
                {"format": "resume-studio", "version": 2, "document": doc},
                ensure_ascii=False, indent=2))
            entry: dict[str, Any] = {"file": fname, "id": r["id"], "title": doc.get("title")}
            rel = doc.get("sourcePdf")
            if isinstance(rel, str) and _store._safe_source_pdf(rel):
                pdf_path = _data_dir() / rel
                if pdf_path.is_file():
                    zf.write(pdf_path, f"pdfs/{pdf_path.name}")
                    entry["sourcePdf"] = rel
            manifest["documents"].append(entry)
        manifest["count"] = len(manifest["documents"])
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return buf.getvalue()


def import_all(zip_bytes: bytes) -> dict[str, Any]:
    """从 ZIP 全量导入（全部作为新文档，不覆盖现有）。"""
    from .documents import save_document

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as e:
        raise ValueError(f"不是有效的 ZIP 文件：{e}") from e

    imported, skipped = [], []
    for name in zf.namelist():
        if not name.lower().endswith(".json") or name.endswith("manifest.json"):
            continue
        if name.startswith(("pdfs/", "__MACOSX/")) or ".." in name:
            continue
        try:
            raw = json.loads(zf.read(name).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            skipped.append({"file": name, "reason": "JSON 解析失败"})
            continue
        inner = raw.get("document") if isinstance(raw, dict) else None
        candidate = inner if isinstance(inner, dict) else raw
        try:
            doc = normalize_document(candidate)
        except Exception as e:  # noqa: BLE001
            skipped.append({"file": name, "reason": str(e)[:80]})
            continue
        # 换发新 id：导入永远是新增，不覆盖
        import uuid as _uuid

        doc["id"] = _uuid.uuid4().hex
        # 原始 PDF 从包内恢复（如有）
        rel = candidate.get("sourcePdf") if isinstance(candidate, dict) else None
        if isinstance(rel, str) and _store._safe_source_pdf(rel):
            member = f"pdfs/{Path(rel).name}"
            try:
                data = zf.read(member)
                imports_dir = _data_dir() / "imports"
                imports_dir.mkdir(parents=True, exist_ok=True)
                stored = imports_dir / f"{doc['id']}.pdf"
                stored.write_bytes(data)
                doc["sourcePdf"] = f"imports/{stored.name}"
            except KeyError:
                doc.pop("sourcePdf", None)
        else:
            doc.pop("sourcePdf", None)
        saved = save_document(doc)
        imported.append({"id": saved["id"], "title": saved["title"]})
    return {"imported": imported, "skipped": skipped, "count": len(imported)}
