"""导出 API：PDF（模板 / 原格式）/ Word / JSON / HTML。"""
from __future__ import annotations

import io
import json
import urllib.parse

from flask import Blueprint, jsonify, request, send_file

from ..engine import pdf as pdf_engine
from ..exporters import build_docx, export_document_bytes
from ..schema import normalize_document
from ..services import documents as store

bp = Blueprint("export", __name__, url_prefix="/api/v1")


def _resolve_doc() -> tuple[dict | None, tuple | None]:
    """优先按 id 取库中文档；否则用请求体中的文档。"""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        body = {}
    doc_id = body.get("id") or request.args.get("id")
    if doc_id:
        doc = store.get_document(str(doc_id))
        if doc:
            return doc, None
        return None, (jsonify({"error": "文档不存在"}), 404)
    doc = body.get("document") if isinstance(body.get("document"), dict) else body
    return normalize_document(doc), None


def _pdf_quality_warnings(doc: dict, data: bytes) -> list[str]:
    """导出 PDF 后的质量自检。

    用户导入的模板可能自带 @font-face 引用 CFF/woff 字体，Chromium 会静默
    降级为 Type3（文本层损坏、ATS 无法解析）——必须在导出时检查并告知用户。
    """
    warnings: list[str] = []
    try:
        check = pdf_engine.verify_pdf_fonts(data)
        if check["type3"]:
            warnings.append(
                f"PDF 内含无法嵌入的字体（Type3 降级：{', '.join(check['type3'][:3])}），"
                "文本可能无法被 ATS / 招聘系统检索。请检查当前模板是否引用了外部字体。"
            )
        elif not check["textExtractable"]:
            warnings.append("PDF 文本层不可提取，可能影响 ATS 解析。")
        elif not check["ok"]:
            warnings.append("PDF 文本层中文提取异常，请人工检查。")
    except Exception as e:  # noqa: BLE001 自检失败不阻塞导出
        warnings.append(f"PDF 字体自检未完成：{e}")
    return warnings


def _with_warnings(resp, warnings: list[str]):
    if warnings:
        resp.headers["X-Resume-Warnings"] = urllib.parse.quote(
            json.dumps(warnings, ensure_ascii=False))
    return resp


@bp.post("/export/pdf")
def export_pdf():
    doc, err = _resolve_doc()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    if body.get("mode") == "original":
        return _export_pdf_original(doc)
    try:
        data = pdf_engine.render_pdf_bytes(doc)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"PDF 生成失败：{e}"}), 500
    resp = send_file(
        io.BytesIO(data), as_attachment=True,
        download_name=f"{doc.get('title') or 'resume'}.pdf",
        mimetype="application/pdf",
    )
    return _with_warnings(resp, _pdf_quality_warnings(doc, data))


def _export_pdf_original(doc: dict):
    """原格式导出：把模块修改打进原始 PDF，未改动部分保持原版式。"""
    from ..services import pdf_patch

    rel = doc.get("sourcePdf")
    if not rel:
        return jsonify({"error": "该文档没有关联的原始 PDF（非对照导入），请用模板导出"}), 400
    try:
        result = pdf_patch.patch_pdf(rel, doc.get("sourceContent"), doc.get("content"),
                                     doc.get("sections"))
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"原格式导出失败：{e}"}), 500

    resp = send_file(
        io.BytesIO(result["data"]), as_attachment=True,
        download_name=f"{doc.get('title') or 'resume'}.pdf",
        mimetype="application/pdf",
    )
    notices: list[str] = []
    if result["unchanged"]:
        notices.append("内容无修改，已导出原始 PDF")
    else:
        notices.append(f"已按原格式应用 {len(result['applied'])} 处修改")
        for f in result["failed"][:5]:
            notices.append(f"未能应用：{f['path']}（{f['reason']}）")
        if len(result["failed"]) > 5:
            notices.append(f"…等共 {len(result['failed'])} 处未应用")
    return _with_warnings(resp, notices)


@bp.post("/export/docx")
def export_docx():
    doc, err = _resolve_doc()
    if err:
        return err
    try:
        buf = build_docx(doc)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"Word 生成失败：{e}"}), 500
    return send_file(
        buf, as_attachment=True,
        download_name=f"{doc.get('title') or 'resume'}.docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@bp.post("/export/json")
def export_json():
    doc, err = _resolve_doc()
    if err:
        return err
    return send_file(
        io.BytesIO(export_document_bytes(doc)), as_attachment=True,
        download_name=f"{doc.get('title') or 'resume'}.json",
        mimetype="application/json",
    )


@bp.post("/export/html")
def export_html():
    """自包含 HTML（字体 base64 内嵌，可离线打开 / 分享）。"""
    from ..exporters.html_export import export_html as build_html

    doc, err = _resolve_doc()
    if err:
        return err
    try:
        data = build_html(doc)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"HTML 生成失败：{e}"}), 500
    return send_file(
        io.BytesIO(data), as_attachment=True,
        download_name=f"{doc.get('title') or 'resume'}.html",
        mimetype="text/html",
    )
