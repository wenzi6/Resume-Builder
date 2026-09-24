"""模板与区块定义 API。"""
from __future__ import annotations

import json
import re
import shutil
import uuid
import zipfile
from pathlib import Path

from flask import Blueprint, jsonify, request

from ..config import TEMPLATES_DIR
from ..engine.renderer import list_templates
from .. import registry

bp = Blueprint("templates", __name__, url_prefix="/api/v1")


@bp.get("/templates")
def get_templates():
    return jsonify(list_templates())


@bp.get("/schema/sections")
def get_section_schema():
    """区块定义：驱动前端表单渲染的唯一事实来源。"""
    return jsonify({
        "builtin": registry.builtin_section_defs(),
        "builtinKeys": registry.BUILTIN_KEYS,
        "customArrayFields": registry.CUSTOM_ARRAY_FIELDS,
        "customSimpleFields": registry.CUSTOM_SIMPLE_FIELDS,
    })


def _validate_html_template(html_text: str) -> None:
    if not re.search(r"\{\{.+?\}\}", html_text):
        raise ValueError("模板中未检测到任何 {{占位符}}，请使用 {{name}} 等标记数据位置")


@bp.post("/import-template")
def import_template():
    """导入模板：.html 单文件 或 .zip 包（layout.html + layout.css + template.json）。"""
    if "file" not in request.files:
        return jsonify({"error": "请选择文件"}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "文件名为空"}), 400

    ext = Path(file.filename).suffix.lower()
    if ext not in (".html", ".zip"):
        return jsonify({"error": "仅支持 .html 或 .zip 格式"}), 400

    base_name = Path(file.filename).stem
    template_id = re.sub(r"[^a-z0-9_-]", "", base_name.lower()) or f"imported-{uuid.uuid4().hex[:6]}"

    dest_dir = TEMPLATES_DIR / template_id
    counter = 1
    while dest_dir.exists():
        dest_dir = TEMPLATES_DIR / f"{template_id}-{counter}"
        counter += 1
    dest_dir.mkdir(parents=True, exist_ok=True)

    try:
        if ext == ".html":
            content = file.read().decode("utf-8", errors="replace")
            _validate_html_template(content)
            (dest_dir / "layout.html").write_text(content, encoding="utf-8")
            (dest_dir / "layout.css").write_text("/* imported */\n", encoding="utf-8")
            (dest_dir / "template.json").write_text(
                json.dumps({
                    "name": base_name, "description": "导入的模板",
                    "author": "User", "version": "1.0", "layout": "single",
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            with zipfile.ZipFile(file) as zf:
                for name in zf.namelist():
                    norm = name.replace("\\", "/")
                    if norm.startswith("/") or ".." in norm.split("/") or ":" in norm:
                        shutil.rmtree(dest_dir, ignore_errors=True)
                        return jsonify({"error": f"ZIP 包含非法路径: {name}"}), 400
                zf.extractall(dest_dir)

            layout = dest_dir / "layout.html"
            if not layout.exists():
                found = list(dest_dir.rglob("layout.html")) or list(dest_dir.rglob("index.html"))
                if not found:
                    return jsonify({"error": "ZIP 中未找到 layout.html"}), 400
                src = found[0].parent
                for f in src.iterdir():
                    shutil.move(str(f), str(dest_dir / f.name))
                for d in sorted(dest_dir.rglob("*"), reverse=True):
                    if d.is_dir() and not any(d.iterdir()):
                        d.rmdir()
                layout = dest_dir / "layout.html"

            _validate_html_template(layout.read_text(encoding="utf-8", errors="replace"))

            if not (dest_dir / "template.json").exists():
                (dest_dir / "template.json").write_text(
                    json.dumps({
                        "name": base_name, "description": "导入的模板",
                        "author": "User", "version": "1.0", "layout": "single",
                    }, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            if not (dest_dir / "layout.css").exists():
                (dest_dir / "layout.css").write_text("/* imported */\n", encoding="utf-8")

        meta = json.loads((dest_dir / "template.json").read_text(encoding="utf-8"))
        return jsonify({"success": True, "template": {"id": dest_dir.name, **meta}})

    except ValueError as e:
        shutil.rmtree(dest_dir, ignore_errors=True)
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(dest_dir, ignore_errors=True)
        return jsonify({"error": f"导入失败: {e}"}), 500
