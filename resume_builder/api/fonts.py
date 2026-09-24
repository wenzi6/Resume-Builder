"""用户自有字体 API：列表 / 上传（自动转换 + 清洗）/ 删除。"""
from __future__ import annotations

import tempfile

from flask import Blueprint, jsonify, request
from pathlib import Path

from ..services import font_manager

bp = Blueprint("fonts", __name__, url_prefix="/api/v1/fonts")


@bp.get("")
def list_fonts():
    return jsonify({
        "user": font_manager.list_user_fonts(),
        "families": sorted(font_manager.valid_families()),
    })


@bp.post("/upload")
def upload_font():
    if "file" not in request.files:
        return jsonify({"error": "请选择字体文件"}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "文件名为空"}), 400
    if not file.filename.lower().endswith((".ttf", ".otf")):
        return jsonify({"error": "仅支持 .ttf / .otf 字体"}), 400

    tmp_path = None
    try:
        suffix = Path(file.filename).suffix.lower()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            file.save(tmp)
            tmp_path = tmp.name
        info = font_manager.register_font(tmp_path)
        return jsonify({"font": info, "success": True})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"字体注册失败：{e}"}), 500
    finally:
        if tmp_path:
            try:
                import os

                os.unlink(tmp_path)
            except OSError:
                pass


@bp.delete("/<filename>")
def delete_font(filename: str):
    if not font_manager.delete_font(filename):
        return jsonify({"error": "字体不存在"}), 404
    return jsonify({"success": True})
