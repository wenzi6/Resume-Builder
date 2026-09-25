"""运行日志：文件轮转 + 前端错误回传 + 尾部读取。

日志位置：data/logs/resume-studio.log（gitignored，仅本机）。
定位问题时可让用户直接「查看日志」复制末尾几行，不必翻文件系统。
"""
from __future__ import annotations

import logging
import logging.handlers
import threading
from pathlib import Path
from typing import Any

_SETUP_LOCK = threading.Lock()
_CONFIGURED = False
_RESOLVED_PATH: Path | None = None
LOG_RELATIVE = "logs/resume-studio.log"


def log_path() -> Path:
    """日志文件路径。初始化后固定（测试会把 DATA_DIR 重映射到临时目录，
    但日志位置不应随之改变，否则 tail/open 会找不到真实日志）。"""
    if _RESOLVED_PATH is not None:
        return _RESOLVED_PATH
    from . import config

    return config.DATA_DIR / LOG_RELATIVE


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """配置根日志器：控制台 + 轮转文件（5MB × 3 份）。重复调用安全。"""
    global _CONFIGURED
    with _SETUP_LOCK:
        if _CONFIGURED:
            return logging.getLogger("resume_builder")
        path = log_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        global _RESOLVED_PATH
        _RESOLVED_PATH = path
        fmt = logging.Formatter(
            "%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        root = logging.getLogger("resume_builder")
        root.setLevel(level)
        root.propagate = False
        if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
            sh = logging.StreamHandler()
            sh.setFormatter(fmt)
            root.addHandler(sh)
        try:
            fh = logging.handlers.RotatingFileHandler(
                str(path), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
            fh.setFormatter(fmt)
            root.addHandler(fh)
        except OSError:
            root.warning("日志文件不可写：%s（仅输出到控制台）", path)
        # Flask/Werkzeug 的访问与错误也进同一文件
        for name in ("werkzeug",):
            lg = logging.getLogger(name)
            lg.setLevel(logging.INFO)
            if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in lg.handlers):
                try:
                    lg.addHandler(logging.handlers.RotatingFileHandler(
                        str(path), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"))
                except OSError:
                    pass
        _CONFIGURED = True
        root.info("日志初始化：%s", path)
        return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger("resume_builder." + name)


def tail(lines: int = 200) -> dict[str, Any]:
    """读取日志末尾若干行（跨轮转文件拼接，新的在前）。"""
    path = log_path()
    files = [path] + [Path(str(path) + f".{i}") for i in range(3, 0, -1)]
    chunks: list[str] = []
    for f in files:
        try:
            if f.is_file():
                chunks.append(f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    text = "".join(chunks)
    all_lines = [l for l in text.splitlines() if l.strip()]
    return {
        "path": str(path),
        "exists": path.is_file(),
        "size": path.stat().st_size if path.is_file() else 0,
        "lines": all_lines[-max(1, min(lines, 2000)):],
        "total": len(all_lines),
    }


def open_log_dir() -> bool:
    """打开日志所在目录（Windows 资源管理器；其他平台返回 False）。"""
    import os
    import subprocess

    path = log_path().parent
    try:
        path.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(path))  # noqa: S606 仅本机工具，打开自家日志目录
            return True
        subprocess.Popen(["xdg-open", str(path)])
        return True
    except Exception:  # noqa: BLE001
        return False
