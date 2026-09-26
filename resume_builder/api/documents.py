"""文档 CRUD API。"""
from __future__ import annotations

import io
import time

from flask import Blueprint, jsonify, request, send_file

from ..schema import new_document, normalize_document
from ..services import documents as store

bp = Blueprint("documents", __name__, url_prefix="/api/v1/documents")


@bp.get("")
def list_docs():
    return jsonify({"documents": store.list_documents()})


@bp.post("/clear-all")
def clear_all_docs():
    """一键清空全部文档。调用方负责先备份（前端会先调 /backups/now）。"""
    removed = store.clear_all_documents()
    return jsonify({"success": True, "removed": removed, "documents": store.list_documents()})


@bp.get("/export-all")
def export_all_docs():
    """全部文档导出为 ZIP（JSON + 原始 PDF + manifest）。"""
    from ..services import bundle

    try:
        data = bundle.export_all()
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"导出失败：{e}"}), 500
    return send_file(
        io.BytesIO(data), as_attachment=True,
        download_name=f"resume-studio-{time.strftime('%Y%m%d')}.zip",
        mimetype="application/zip",
    )


@bp.post("/import-all")
def import_all_docs():
    """从 ZIP 全量导入（全部作为新文档）。"""
    from ..services import bundle

    if "file" not in request.files:
        return jsonify({"error": "请选择 ZIP 文件"}), 400
    file = request.files["file"]
    if not file.filename.lower().endswith(".zip"):
        return jsonify({"error": "仅支持 .zip 格式"}), 400
    try:
        result = bundle.import_all(file.read())
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"导入失败：{e}"}), 500
    return jsonify(result)


@bp.post("")
def create_doc():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        body = {}
    doc = new_document(
        template_id=str(body.get("templateId") or "classic"),
        title=str(body.get("title") or "未命名简历"),
    )
    saved = store.save_document(doc)
    return jsonify({"document": saved}), 201


@bp.post("/from-sample/<sample_name>")
def create_from_sample(sample_name: str):
    """从内置示例创建文档：sample_name = general | tech"""
    from ..sample import sample_general, sample_tech

    fn = {"general": sample_general, "tech": sample_tech}.get(sample_name)
    if not fn:
        return jsonify({"error": f"未知示例：{sample_name}（可选 general / tech）"}), 400
    return jsonify({"document": store.save_document(fn())}), 201


@bp.get("/<doc_id>")
def get_doc(doc_id: str):
    doc = store.get_document(doc_id)
    if not doc:
        return jsonify({"error": "文档不存在"}), 404
    return jsonify({"document": doc})


@bp.put("/<doc_id>")
def save_doc(doc_id: str):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        body = {}
    doc = body.get("document") if isinstance(body.get("document"), dict) else body
    doc = normalize_document(doc)
    doc["id"] = doc_id
    saved = store.save_document(doc)
    return jsonify({"document": saved})


@bp.delete("/<doc_id>")
def delete_doc(doc_id: str):
    if not store.delete_document(doc_id):
        return jsonify({"error": "文档不存在"}), 404
    return jsonify({"success": True})


@bp.post("/<doc_id>/duplicate")
def duplicate_doc(doc_id: str):
    doc = store.duplicate_document(doc_id)
    if not doc:
        return jsonify({"error": "文档不存在"}), 404
    return jsonify({"document": doc}), 201


@bp.get("/<doc_id>/versions")
def versions_doc(doc_id: str):
    """文档历史快照列表。"""
    if not store.get_document(doc_id):
        return jsonify({"error": "文档不存在"}), 404
    return jsonify({"versions": store.list_versions(doc_id)})


@bp.get("/<doc_id>/source-pages")
def source_pages_doc(doc_id: str):
    """渲染文档关联的原始 PDF 为逐页图片（对照导入的「原格式」视图，静态原图）。"""
    from .. import logging_setup
    from ..services import source_pdf

    log = logging_setup.get_logger("source-pages")
    doc = store.get_document(doc_id)
    if not doc:
        return jsonify({"error": "文档不存在"}), 404
    rel = doc.get("sourcePdf")
    if not rel:
        return jsonify({"pages": []})
    try:
        pages = source_pdf.render_pages(rel)
    except Exception as e:  # noqa: BLE001
        log.exception("原始 PDF 渲染失败 %s: %s", doc_id, e)
        return jsonify({"error": f"原始 PDF 渲染失败：{e}"}), 500
    return jsonify({"pages": pages, "pdfUrl": f"/data/{rel}"})


@bp.post("/<doc_id>/source-pages")
def source_pages_live(doc_id: str):
    """原格式**实时预览**：把调用方给的当前内容补进原始 PDF 再渲染。

     Body: {content: {...}}（前端传 store.doc.content，未保存的编辑也能立刻看到）
    不落库、不改文档，纯粹为了「边编辑边看原格式效果」。
    """
    from .. import logging_setup
    from ..services import pdf_patch, source_pdf

    log = logging_setup.get_logger("source-pages")
    doc = store.get_document(doc_id)
    if not doc:
        return jsonify({"error": "文档不存在"}), 404
    rel = doc.get("sourcePdf")
    if not rel:
        return jsonify({"error": "该文档没有关联的原始 PDF"}), 400
    if not doc.get("sourceContent"):
        return jsonify({"error": "缺少导入时的解析快照，无法计算改动"}), 400

    body = request.get_json(silent=True) or {}
    content = body.get("content")
    if not isinstance(content, dict):
        content = doc.get("content")
    # 兼容两种传法：{content, sections} 或 {document: {...}}
    sections = body.get("sections")
    if not isinstance(sections, list):
        whole = body.get("document")
        if isinstance(whole, dict):
            sections = whole.get("sections")
            if isinstance(whole.get("content"), dict):
                content = whole["content"]
    if not isinstance(sections, list):
        sections = doc.get("sections")
    try:
        result = pdf_patch.patch_pdf(rel, doc.get("sourceContent"), content, sections)
    except FileNotFoundError as e:
        log.error("实时预览：原始 PDF 缺失 %s: %s", doc_id, e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:  # noqa: BLE001
        log.exception("实时预览补丁失败 %s: %s", doc_id, e)
        return jsonify({"error": f"实时预览失败：{e}"}), 500
    try:
        pages, digest = source_pdf.render_live_pages(result["data"])
    except Exception as e:  # noqa: BLE001
        log.exception("实时预览渲染失败 %s: %s", doc_id, e)
        return jsonify({"error": f"实时预览渲染失败：{e}"}), 500
    return jsonify({
        "pages": pages,
        "pdfUrl": f"/data/{rel}",
        "live": True,
        "digest": digest,
        "applied": len(result["applied"]),
        "failed": result["failed"][:5],
    })


@bp.post("/<doc_id>/versions/<int:version_id>/restore")
def restore_version_doc(doc_id: str, version_id: int):
    """恢复某份历史快照为当前文档。"""
    doc = store.restore_version(doc_id, version_id)
    if not doc:
        return jsonify({"error": "版本不存在"}), 404
    return jsonify({"document": doc})
