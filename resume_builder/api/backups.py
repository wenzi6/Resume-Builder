"""备份管理 API：列表 / 立即备份 / 恢复。"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..services import bundle

bp = Blueprint("backups", __name__, url_prefix="/api/v1/backups")


@bp.get("")
def list_backups():
    return jsonify({"backups": bundle.list_backups(), "max": bundle.MAX_BACKUPS})


@bp.post("/now")
def backup_now():
    name = bundle.backup_db(force=True)
    return jsonify({"backup": name, "backups": bundle.list_backups()})


@bp.post("/restore")
def restore_backup():
    """恢复指定备份（覆盖当前数据库；恢复后前端会重载文档列表）。"""
    body = request.get_json(silent=True) or {}
    name = str(body.get("name") or "")
    if not bundle.restore_backup(name):
        return jsonify({"error": "备份不存在"}), 404
    return jsonify({"success": True})


@bp.delete("/<name>")
def delete_backup(name: str):
    """删除指定备份（防路径穿越）。"""
    if not bundle.delete_backup(name):
        return jsonify({"error": "备份不存在"}), 404
    return jsonify({"success": True, "backups": bundle.list_backups()})


@bp.post("/clear")
def clear_backups():
    """一键清空全部备份。"""
    removed = bundle.clear_backups()
    return jsonify({"success": True, "removed": removed, "backups": bundle.list_backups()})
