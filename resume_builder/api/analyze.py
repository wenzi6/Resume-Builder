"""JD 匹配 API：纯本地关键词分析（不依赖 LLM）。"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..schema import normalize_document
from ..services import analyze

bp = Blueprint("analyze", __name__, url_prefix="/api/v1")


@bp.post("/analyze")
def analyze_jd():
    """JD 与简历的关键词匹配分析。body: {document, jd}"""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "请提供 JSON 参数"}), 400
    doc = body.get("document")
    if not isinstance(doc, dict):
        return jsonify({"error": "请提供 document"}), 400
    try:
        result = analyze.analyze(normalize_document(doc), str(body.get("jd") or ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"分析失败：{e}"}), 502
    return jsonify(result)
