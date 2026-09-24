"""用户自有字体管理：上传 → CFF 转换 + 部首清洗 → 注册到字体清单。

上传的字体与内置 Noto 一样进入 @font-face，PDF 导出时由 Chromium 子集化嵌入。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..config import FONTS_DIR
from ..engine.font_convert import ensure_embeddable, read_font_meta

USER_FONTS_DIR = FONTS_DIR / "user"

# 单个字体文件大小上限（字节）
MAX_FONT_BYTES = 40 * 1024 * 1024
ALLOWED_EXT = {".ttf", ".otf"}


def ensure_user_fonts_dir() -> Path:
    USER_FONTS_DIR.mkdir(parents=True, exist_ok=True)
    return USER_FONTS_DIR


def _safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", s)[:40] or "font"


def list_user_fonts() -> list[dict[str, Any]]:
    """扫描用户字体目录，返回 [{file, family, weight}]。"""
    if not USER_FONTS_DIR.exists():
        return []
    out = []
    for p in sorted(USER_FONTS_DIR.glob("*.ttf")):
        try:
            meta = read_font_meta(p)
        except Exception:  # noqa: BLE001 坏文件不阻塞列表
            meta = {"family": p.stem, "weight": 400}
        out.append({"file": p.name, "family": meta["family"], "weight": meta["weight"]})
    return out


def register_font(src: str | Path) -> dict[str, Any]:
    """注册一个用户字体：转换 + 清洗 + 落盘。返回 {file, family, weight, converted}。"""
    from fontTools.ttLib import TTFont

    ensure_user_fonts_dir()
    src = Path(src)
    if src.suffix.lower() not in ALLOWED_EXT:
        raise ValueError("仅支持 .ttf / .otf 字体文件")
    if src.stat().st_size > MAX_FONT_BYTES:
        raise ValueError("字体文件过大（上限 40MB）")

    font = TTFont(str(src))
    try:
        converted = font.sfntVersion == "OTTO"
        font = ensure_embeddable(font)
        meta = read_font_meta(src)
        family = meta["family"]
        weight = meta["weight"]
        out_name = f"{_safe_name(family)}-{weight}.ttf"
        out_path = USER_FONTS_DIR / out_name
        if out_path.exists():
            # 同名不同内容：加后缀避免覆盖
            stem = out_path.stem
            n = 1
            while out_path.exists():
                out_path = USER_FONTS_DIR / f"{stem}-{n}.ttf"
                n += 1
            out_name = out_path.name
        font.save(str(out_path))
    finally:
        font.close()
    return {"file": out_name, "family": family, "weight": weight, "converted": converted}


def delete_font(filename: str) -> bool:
    """删除用户字体（防路径穿越）。"""
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        return False
    p = USER_FONTS_DIR / filename
    if not p.is_file() or p.suffix.lower() != ".ttf":
        return False
    p.unlink()
    return True


def user_font_entries() -> list[tuple[str, int, str]]:
    """以 tokens.FONT_FILES 的条目格式返回用户字体。"""
    return [(f["family"], f["weight"], f"user/{f['file']}") for f in list_user_fonts()]


def valid_families() -> set[str]:
    """当前可用的自定义家族名（不含内置 sans/serif 别名）。"""
    return {f["family"] for f in list_user_fonts()}
