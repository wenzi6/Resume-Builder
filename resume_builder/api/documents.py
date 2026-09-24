"""文档 CRUD API。"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..schema import new_document, normalize_document
from ..services import documents as store

bp = Blueprint("documents", __name__, url_prefix="/api/v1/documents")


@bp.get("")
def list_docs():
    return jsonify({"documents": store.list_documents()})


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


@bp.post("/<doc_id>/versions/<int:version_id>/restore")
def restore_version_doc(doc_id: str, version_id: int):
    """恢复某份历史快照为当前文档。"""
    doc = store.restore_version(doc_id, version_id)
    if not doc:
        return jsonify({"error": "版本不存在"}), 404
    return jsonify({"document": doc})
