"""LLM API：配置 / 测试连接 / 润色 / 生成 / 建议 / JD 定制 / 流式。

安全约定：
- GET /config 永不返回 api_key（只返回 has_key）
- api_key 只通过 PUT /config 写入本地 data/llm_config.json（gitignored）
"""
from __future__ import annotations

import json

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


@bp.get("/models")
def list_models():
    """从服务商拉取可用模型列表（按配置的 format 走对应协议）。"""
    try:
        result = llm.list_models()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 502
    return jsonify(result)


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


@bp.post("/polish-batch")
def polish_batch():
    """批量润色：一次改写多条 bullet。body: {items: [...], context}"""
    body = _body()
    items = body.get("items")
    if not isinstance(items, list):
        return jsonify({"error": "请提供 items 数组"}), 400
    try:
        result = llm.polish_batch(items, str(body.get("context") or ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 502
    return jsonify(result)


@bp.post("/chat")
def chat_ep():
    """对话式迭代（SSE 流式）。body: {messages: [{role, content}, ...]}"""
    import queue
    import threading

    from flask import Response, stream_with_context

    body = _body()
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return jsonify({"error": "请提供 messages 数组"}), 400
    # 只保留合法角色，防 prompt 注入结构混乱
    clean = [
        {"role": m.get("role") if m.get("role") in ("user", "assistant") else "user",
         "content": str(m.get("content") or "")[:2000]}
        for m in messages[-20:] if isinstance(m, dict)
    ]
    if not clean:
        return jsonify({"error": "messages 为空"}), 400

    def generate():
        q: queue.Queue = queue.Queue()

        def worker():
            try:
                parts = []
                for chunk in llm.chat_stream(clean, temperature=0.7, max_tokens=2000):
                    parts.append(chunk)
                    q.put(("chunk", chunk))
                q.put(("done", "".join(parts)))
            except Exception as e:  # noqa: BLE001
                q.put(("error", str(e)))

        threading.Thread(target=worker, daemon=True).start()
        while True:
            kind, payload = q.get()
            if kind == "chunk":
                yield f"data: {json.dumps({'chunk': payload}, ensure_ascii=False)}\n\n"
            elif kind == "done":
                yield f"data: {json.dumps({'done': True, 'text': payload}, ensure_ascii=False)}\n\n"
                return
            else:
                yield f"data: {json.dumps({'error': payload}, ensure_ascii=False)}\n\n"
                return

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


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


@bp.post("/stream")
def llm_stream():
    """流式能力（SSE）：逐段下发模型输出，最后一条带结构化结果。

    事件格式（text/event-stream）：
        data: {"chunk": "文本增量"}
        data: {"done": true, "result": {...}}     最终结构化结果
        data: {"error": "..."}                    失败
    """
    import queue
    import threading

    from flask import Response, stream_with_context

    body = _body()
    capability = str(body.get("capability") or "")
    if capability not in ("polish", "generate"):
        return jsonify({"error": f"不支持的流式能力：{capability}（可选 polish / generate）"}), 400

    def generate():
        q: queue.Queue = queue.Queue()

        def on_chunk(text):
            q.put(("chunk", text))

        def worker():
            try:
                if capability == "polish":
                    text = str(body.get("text") or "")
                    result = llm.polish_text(text, str(body.get("context") or ""), on_chunk)
                else:
                    brief = body.get("brief")
                    if not isinstance(brief, dict):
                        raise ValueError("请提供 brief 参数")
                    result = llm.generate_resume(brief, on_chunk)
                q.put(("done", result))
            except Exception as e:  # noqa: BLE001
                q.put(("error", str(e)))

        threading.Thread(target=worker, daemon=True).start()
        while True:
            kind, payload = q.get()
            if kind == "chunk":
                yield f"data: {json.dumps({'chunk': payload}, ensure_ascii=False)}\n\n"
            elif kind == "done":
                yield f"data: {json.dumps({'done': True, 'result': payload}, ensure_ascii=False)}\n\n"
                return
            else:
                yield f"data: {json.dumps({'error': payload}, ensure_ascii=False)}\n\n"
                return

    return Response(stream_with_context(generate()), mimetype="text/event-stream")
