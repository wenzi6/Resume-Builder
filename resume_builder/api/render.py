"""渲染与分页测量 API。"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..engine import pdf as pdf_engine
from ..engine.renderer import render_preview
from ..schema import normalize_document

bp = Blueprint("render", __name__, url_prefix="/api/v1")


def _doc_from_request() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        body = {}
    doc = body.get("document") if isinstance(body.get("document"), dict) else body
    return normalize_document(doc)


@bp.post("/render")
def render():
    """渲染预览 HTML（编辑器实时预览调用）。"""
    doc = _doc_from_request()
    html = render_preview(doc)
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@bp.post("/page-info")
def page_info():
    """测量页数、各区块落位与分页建议。"""
    doc = _doc_from_request()
    try:
        info = pdf_engine.measure_pages(doc)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"分页测量失败：{e}"}), 500
    return jsonify(info)


@bp.post("/auto-pagebreaks")
def auto_page_breaks():
    """返回建议的分页点（由编辑器一键应用）。"""
    doc = _doc_from_request()
    try:
        info = pdf_engine.measure_pages(doc)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"分页测量失败：{e}"}), 500
    return jsonify({"pageBreaks": info.get("suggestedBreaks", []), "warnings": info.get("warnings", [])})
