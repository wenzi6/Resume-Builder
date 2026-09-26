"""导入 API：JSON 简历 / PDF 简历。"""
from __future__ import annotations

import copy
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


@bp.post("/import/reparse")
def reparse_pdf():
    """用当前解析器重新解析已导入文档的原始 PDF。

    解析规则升级后，旧文档仍是旧数据——此接口让它们一键刷新，
    不必删了重导（重导会丢掉当时的其他编辑）。
    """
    import copy

    from ..services import bundle, documents as docs_svc

    body = request.get_json(silent=True) or {}
    doc_id = str(body.get("id") or "")
    doc = docs_svc.get_document(doc_id)
    if doc is None:
        return jsonify({"error": "文档不存在"}), 404
    rel = doc.get("sourcePdf")
    if not rel or not _safe_rel(rel):
        return jsonify({"error": "该文档不是 PDF 对照导入，没有可重新解析的原始文件"}), 400
    src = DATA_DIR / rel
    if not src.is_file():
        return jsonify({"error": "原始 PDF 文件已被清理，无法重新解析"}), 404
    try:
        with src.open("rb") as fh:
            extracted = pdf_import.extract_pdf(fh)
        content = pdf_import.build_document_from_pdf(extracted)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"重新解析失败：{e}"}), 500

    # 先备份（用户可能已手工修过一些字段，重新解析会覆盖）
    bundle.backup_db(force=True)
    doc["content"] = content
    _apply_pdf_section_titles(doc, extracted)
    doc["sourceContent"] = copy.deepcopy(content)
    saved = docs_svc.save_document(doc)
    return jsonify({
        "document": saved,
        "rawText": extracted.get("raw_text", "")[:2000],
        "reparsed": True,
    })


def _apply_pdf_section_titles(doc: dict, extracted: dict) -> None:
    """用 PDF 里识别出的区块标题覆盖默认名（如 PDF 写「技能特长」就不要叫「专业技能」）。"""
    titles = pdf_import.detect_section_titles(extracted)
    if not titles:
        return
    for sec in doc.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        pdf_title = titles.get(sec.get("key"))
        if pdf_title:
            sec["title"] = pdf_title


def _safe_rel(rel: str) -> bool:
    """防目录穿越：只允许 imports/ 下的相对路径。"""
    return bool(rel) and rel.startswith("imports/") and ".." not in rel


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
    _apply_pdf_section_titles(doc, extracted)
    doc["sourcePdf"] = f"imports/{stored_name}"
    # 存档导入时的解析结果：原格式导出据此计算「用户改了什么」
    doc["sourceContent"] = copy.deepcopy(content)
    return jsonify({
        "document": doc,
        "rawText": extracted.get("raw_text", "")[:2000],
        "pdf": {
            "url": f"/data/imports/{stored_name}",
            "pages": pages,
            "name": file.filename,
        },
    })
