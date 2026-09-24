"""旧版 API 兼容层（/api/* -> /api/v1/*）。

保证 v1 时代的书签、脚本、外部调用继续可用。
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..engine.renderer import render_preview
from ..schema import new_document, normalize_document
from ..services import documents as store

bp = Blueprint("legacy", __name__, url_prefix="/api")


@bp.get("/templates")
def templates():
    from ..engine.renderer import list_templates

    return jsonify(list_templates())


@bp.get("/sample-data")
def sample_data():
    """返回示例文档内容（v2 结构）。"""
    from ..sample import sample_document

    return jsonify(sample_document()["content"])


def _doc_from_request() -> dict:
    data = request.args.get("data", "")
    if not data and request.method == "POST":
        body = request.get_json(silent=True)
        if isinstance(body, dict):
            return normalize_document(body)
        data = request.get_data(as_text=True) or ""
    import json

    try:
        parsed = json.loads(data) if data else {}
    except (json.JSONDecodeError, TypeError):
        parsed = {}
    return normalize_document(parsed if isinstance(parsed, dict) else {})


@bp.route("/preview/<template_id>", methods=["GET", "POST"])
@bp.route("/render/<template_id>", methods=["GET", "POST"])
def preview(template_id: str):
    doc = _doc_from_request()
    doc["templateId"] = template_id
    return render_preview(doc), 200, {"Content-Type": "text/html; charset=utf-8"}


@bp.route("/export-pdf/<template_id>", methods=["GET", "POST"])
def export_pdf(template_id: str):
    import io

    from flask import send_file

    from ..engine import pdf as pdf_engine

    doc = _doc_from_request()
    doc["templateId"] = template_id
    try:
        data = pdf_engine.render_pdf_bytes(doc)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"PDF 生成失败：{e}"}), 500
    return send_file(io.BytesIO(data), as_attachment=True,
                     download_name="resume.pdf", mimetype="application/pdf")


@bp.route("/export-word/<template_id>", methods=["GET", "POST"])
def export_word(template_id: str):
    from flask import send_file

    from ..exporters import build_docx

    doc = _doc_from_request()
    doc["templateId"] = template_id
    try:
        buf = build_docx(doc)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"Word 生成失败：{e}"}), 500
    return send_file(buf, as_attachment=True, download_name="resume.docx",
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
