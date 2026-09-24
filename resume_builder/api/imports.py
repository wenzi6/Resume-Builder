"""导入 API：JSON 简历 / PDF 简历。"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..exporters import import_document
from ..services import pdf_import

bp = Blueprint("imports", __name__, url_prefix="/api/v1")


@bp.post("/import/json")
def import_json():
    body = request.get_json(silent=True)
    if body is None:
        raw = request.get_data(as_text=True)
        try:
            import json

            body = json.loads(raw) if raw.strip() else None
        except Exception:  # noqa: BLE001
            body = None
    if body is None:
        return jsonify({"error": "请提供 JSON 内容"}), 400
    try:
        doc = import_document(body)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    # 导入一律创建新文档（换发新 id）：避免导入同 id 的旧文件时覆盖库中现有简历
    import uuid

    doc["id"] = uuid.uuid4().hex
    return jsonify({"document": doc})


@bp.post("/import/pdf")
def import_pdf():
    if "file" not in request.files:
        return jsonify({"error": "请选择 PDF 文件"}), 400
    file = request.files["file"]
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "仅支持 .pdf 格式"}), 400
    try:
        extracted = pdf_import.extract_pdf(file)
        content = pdf_import.build_document_from_pdf(extracted)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"PDF 解析失败：{e}"}), 500

    from ..schema import new_document

    doc = new_document(title=f"导入-{file.filename[:20]}")
    doc["content"] = content
    return jsonify({"document": doc, "rawText": extracted.get("raw_text", "")[:2000]})
