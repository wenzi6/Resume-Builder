"""Resume Studio - 应用工厂。"""
from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, send_from_directory
from flask_cors import CORS

from . import config
from .api import register_blueprints


def create_app() -> Flask:
    config.ensure_dirs()

    app = Flask(
        __name__,
        static_folder=None,  # 静态资源由显式路由提供
    )

    # 仅允许本地来源跨域（防止任意网页调用本机 API）
    CORS(app, resources={r"/api/*": {"origins": config.ALLOWED_ORIGINS}})

    register_blueprints(app)

    # ---- 数据库（先建表，后续清理才知道有哪些文档被引用） ----
    from .services import documents as store

    store.init_db()

    # 用户字体目录 + 渲染临时文件清理 + 孤立原始 PDF 清扫
    from .services import font_manager
    from .engine.pdf import sweep_stale_renders
    from .services.documents import sweep_orphan_source_pdfs

    font_manager.ensure_user_fonts_dir()
    sweep_stale_renders(max_age_s=3600)
    sweep_orphan_source_pdfs(max_age_s=3600)

    # ---- 编辑器与静态资源 ----
    @app.get("/")
    def index():
        return send_from_directory(config.STATIC_DIR, "editor.html")

    @app.get("/static/<path:filename>")
    def static_files(filename: str):
        return send_from_directory(config.STATIC_DIR, filename)

    @app.get("/fonts/<path:filename>")
    def fonts(filename: str):
        """字体文件（预览模式 @font-face 引用；PDF 模式走 file://）。"""
        return send_from_directory(config.FONTS_DIR, filename)

    @app.get("/data/<path:filename>")
    def data_files(filename: str):
        return send_from_directory(config.DATA_DIR, filename)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    # ---- 数据库 ----
    from .services import documents as store

    store.init_db()

    return app

def main() -> None:
    app = create_app()
    debug = os.environ.get("FLASK_DEBUG", "0").lower() in ("1", "true", "yes")
    print("Resume Studio starting...")
    print("Templates:", config.TEMPLATES_DIR)
    print(f"Visit: http://localhost:{config.PORT}")
    app.run(debug=debug, port=config.PORT, host="127.0.0.1")
