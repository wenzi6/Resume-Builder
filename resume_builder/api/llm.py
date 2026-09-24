"""LLM API：配置 / 测试连接 / 润色 / 生成 / 建议 / JD 定制。

安全约定：
- GET /config 永不返回 api_key（只返回 has_key）
- api_key 只通过 PUT /config 写入本地 data/llm_config.json（gitignored）
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..schema import normalize_document
from ..services import llm

bp = Blueprint("llm", __name__, url_prefix="/api/v1/llm")


def _body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


@bp.get("/config")
def get_config():
    return jsonify(llm.public_config())


@bp.put("/config")
def put_config():
    body = _body()
    base_url = str(body.get("base_url") or "").strip()
    model = str(body.get("model") or "").strip()
    if not base_url or not model:
        return jsonify({"error": "Base URL 和模型名称不能为空"}), 400
    if not base_url.startswith(("http://", "https://")):
        return jsonify({"error": "Base URL 必须以 http:// 或 https:// 开头"}), 400
    try:
        llm.save_config(body)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"配置保存失败：{e}"}), 500
    return jsonify(llm.public_config())


@bp.post("/test")
def test_conn():
    return jsonify(llm.test_connection())


@bp.post("/polish")
def polish():
    body = _body()
    try:
        result = llm.polish_text(str(body.get("text") or ""), str(body.get("context") or ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 502
    return jsonify(result)


@bp.post("/generate")
def generate():
    body = _body()
    brief = body.get("brief")
    if not isinstance(brief, dict):
        return jsonify({"error": "请提供 brief 参数"}), 400
    try:
        result = llm.generate_resume(brief)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 502
    return jsonify(result)


@bp.post("/suggest")
def suggest():
    body = _body()
    doc = body.get("document")
    if not isinstance(doc, dict):
        return jsonify({"error": "请提供 document"}), 400
    try:
        result = llm.suggest_improvements(doc)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 502
    return jsonify(result)


@bp.post("/tailor")
def tailor():
    body = _body()
    doc = body.get("document")
    if not isinstance(doc, dict):
        return jsonify({"error": "请提供 document"}), 400
    try:
        result = llm.tailor_to_jd(doc, str(body.get("jd") or ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 502
    return jsonify(result)
