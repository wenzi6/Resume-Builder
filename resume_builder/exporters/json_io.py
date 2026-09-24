"""文档 JSON 导入导出（含 v1 迁移）。"""
from __future__ import annotations

import json
from typing import Any

from ..schema import DOCUMENT_VERSION, migrate_legacy, normalize_document

EXPORT_ENVELOPE = {
    "format": "resume-studio",
}


def export_document(doc: dict[str, Any]) -> dict[str, Any]:
    """导出为可分享的 JSON 结构。"""
    d = normalize_document(doc)
    return {
        **EXPORT_ENVELOPE,
        "version": DOCUMENT_VERSION,
        "document": d,
    }


def export_document_bytes(doc: dict[str, Any]) -> bytes:
    return json.dumps(export_document(doc), ensure_ascii=False, indent=2).encode("utf-8")


def import_document(raw: Any) -> dict[str, Any]:
    """导入任意来源的 JSON：新版信封 / 裸文档 / v1 旧格式。"""
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON 解析失败：{e}") from e
    if not isinstance(raw, dict):
        raise ValueError("导入的数据必须是 JSON 对象")

    inner = raw.get("document")
    if isinstance(inner, dict):
        candidate = inner
    else:
        candidate = raw
    if candidate.get("version") != DOCUMENT_VERSION:
        candidate = migrate_legacy(candidate)
    return normalize_document(candidate)
