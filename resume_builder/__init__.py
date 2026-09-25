"""Resume Studio - 应用工厂。"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from . import config
from .api import register_blueprints


def create_app() -> Flask:
    config.ensure_dirs()

    # ---- 运行日志（文件轮转，问题定位用）----
    from . import logging_setup

    logging_setup.setup_logging()
    logger = logging_setup.get_logger("app")

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

    # 数据安全：启动即备份 + 每 30 分钟定期备份（守护线程，内容无变化则跳过）
    from .services import bundle

    try:
        bundle.backup_db()
    except Exception:  # noqa: BLE001 备份失败不阻塞启动
        pass

    def _backup_loop():
        while True:
            time.sleep(1800)
            try:
                bundle.backup_db()
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=_backup_loop, daemon=True).start()

    # 优雅退出时再备份一次
    import atexit

    atexit.register(lambda: bundle.backup_db())

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

    # ---- 全局错误处理：未捕获异常落日志 + 统一 JSON 500 ----
    @app.errorhandler(Exception)
    def _unhandled(exc):  # noqa: ANN001
        from werkzeug.exceptions import HTTPException

        if isinstance(exc, HTTPException):
            if exc.code and exc.code >= 500:
                logger.error("HTTP %s: %s %s", exc.code, request.method, request.path,
                             exc_info=exc)
            return exc
        logger.exception("未处理异常 %s %s: %s", request.method, request.path, exc)
        return jsonify({"error": f"服务器内部错误：{exc}", "logged": True}), 500

    @app.after_request
    def _log_slow(resp):
        try:
            import time as _t

            started = getattr(request, "_started_at", None)
            if started and resp.status_code >= 500:
                logger.error("%s %s -> %s", request.method, request.path, resp.status_code)
        except Exception:  # noqa: BLE001 日志本身绝不阻塞响应
            pass
        return resp

    return app

def main() -> None:
    app = create_app()
    debug = os.environ.get("FLASK_DEBUG", "0").lower() in ("1", "true", "yes")
    print("Resume Studio starting...")
    print("Templates:", config.TEMPLATES_DIR)
    print(f"Visit: http://localhost:{config.PORT}")
    if debug:
        app.run(debug=True, port=config.PORT, host="127.0.0.1")
        return
    # 生产模式：waitress（多线程、无 dev server 警告）；未安装则回退 Flask dev server
    try:
        from waitress import serve

        serve(app, host="127.0.0.1", port=config.PORT, threads=8, ident="Resume Studio")
    except ImportError:
        app.run(debug=False, port=config.PORT, host="127.0.0.1")
