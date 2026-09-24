"""导出 API：PDF / Word / JSON。"""
from __future__ import annotations

import io

from flask import Blueprint, jsonify, request, send_file

from ..engine import pdf as pdf_engine
from ..exporters import build_docx, export_document_bytes
from ..schema import normalize_document
from ..services import documents as store

bp = Blueprint("export", __name__, url_prefix="/api/v1")


def _resolve_doc() -> tuple[dict | None, tuple | None]:
    """优先按 id 取库中文档；否则用请求体中的文档。"""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        body = {}
    doc_id = body.get("id") or request.args.get("id")
    if doc_id:
        doc = store.get_document(str(doc_id))
        if doc:
            return doc, None
        return None, (jsonify({"error": "文档不存在"}), 404)
    doc = body.get("document") if isinstance(body.get("document"), dict) else body
    return normalize_document(doc), None


@bp.post("/export/pdf")
def export_pdf():
    doc, err = _resolve_doc()
    if err:
        return err
    try:
        data = pdf_engine.render_pdf_bytes(doc)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"PDF 生成失败：{e}"}), 500
    return send_file(
        io.BytesIO(data), as_attachment=True,
        download_name=f"{doc.get('title') or 'resume'}.pdf",
        mimetype="application/pdf",
    )


@bp.post("/export/docx")
def export_docx():
    doc, err = _resolve_doc()
    if err:
        return err
    try:
        buf = build_docx(doc)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"Word 生成失败：{e}"}), 500
    return send_file(
        buf, as_attachment=True,
        download_name=f"{doc.get('title') or 'resume'}.docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@bp.post("/export/json")
def export_json():
    doc, err = _resolve_doc()
    if err:
        return err
    return send_file(
        io.BytesIO(export_document_bytes(doc)), as_attachment=True,
        download_name=f"{doc.get('title') or 'resume'}.json",
        mimetype="application/json",
    )
