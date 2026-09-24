"""API 蓝图注册。"""
from flask import Blueprint


def register_blueprints(app) -> None:
    from . import documents, export, imports, legacy, render, templates

    app.register_blueprint(templates.bp)
    app.register_blueprint(documents.bp)
    app.register_blueprint(render.bp)
    app.register_blueprint(export.bp)
    app.register_blueprint(imports.bp)
    app.register_blueprint(legacy.bp)
