"""日志 API：前端错误回传、尾部读取、打开目录。

定位用户报的 bug 时，让用户点「查看日志」即可拿到末尾几行，
不必去文件系统里翻；浏览器里的 JS 错误也会落到同一个文件。
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from .. import logging_setup

bp = Blueprint("logs", __name__, url_prefix="/api/v1/logs")
log = logging_setup.get_logger("client")


@bp.post("/client")
def client_error():
    """接收前端 window.onerror / unhandledrejection。

    body: {message, source, lineno, colno, stack?, url?}
    """
    body = request.get_json(silent=True) or {}
    message = str(body.get("message") or "")[:500]
    if not message:
        return jsonify({"error": "message 不能为空"}), 400
    stack = str(body.get("stack") or "")[:1500]
    source = str(body.get("source") or "")[:200]
    line = body.get("lineno")
    col = body.get("colno")
    url = str(body.get("url") or "")[:200]
    log.error("前端错误: %s | %s:%s:%s | %s | %s",
              message, source, line, col, url, stack.replace("\n", " ← ") if stack else "")
    return jsonify({"ok": True})


@bp.get("/tail")
def tail():
    """日志末尾若干行（?lines=200，上限 2000）。"""
    try:
        lines = int(request.args.get("lines", 200))
    except (TypeError, ValueError):
        lines = 200
    return jsonify(logging_setup.tail(lines))


@bp.post("/open")
def open_dir():
    """打开日志所在目录（Windows 资源管理器）。"""
    ok = logging_setup.open_log_dir()
    return jsonify({"ok": ok, "path": str(logging_setup.log_path().parent)})
