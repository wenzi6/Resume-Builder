"""导入 API：JSON 简历 / PDF 简历。"""
from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, request

from ..config import DATA_DIR
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
        # 先落盘原始 PDF（对照导入：原格式原样保留，供编辑器并排展示）
        imports_dir = DATA_DIR / "imports"
        imports_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex}.pdf"
        stored_path = imports_dir / stored_name
        file.save(str(stored_path))

        try:
            pages = pdf_import.count_pages(stored_path)
        except Exception:  # noqa: BLE001 页数探测失败不阻塞导入
            pages = 0

        with stored_path.open("rb") as fh:
            extracted = pdf_import.extract_pdf(fh)
        content = pdf_import.build_document_from_pdf(extracted)
    except Exception as e:  # noqa: BLE001
        stored_path.unlink(missing_ok=True)
        return jsonify({"error": f"PDF 解析失败：{e}"}), 500

    from ..schema import new_document

    doc = new_document(title=f"导入-{file.filename[:20]}")
    doc["content"] = content
    doc["sourcePdf"] = f"imports/{stored_name}"
    return jsonify({
        "document": doc,
        "rawText": extracted.get("raw_text", "")[:2000],
        "pdf": {
            "url": f"/data/imports/{stored_name}",
            "pages": pages,
            "name": file.filename,
        },
    })
