"""PDF 渲染与分页测量（常驻 worker 进程池 + 单次子进程兜底）。

性能设计：Chromium 冷启动约 1-2s，是 PDF / 分页测量的主要延迟。
因此默认走「常驻 worker」——一个长寿的 pdf_worker.py serve 进程，
Chromium 只启动一次，请求间复用（JSON 行协议 over stdin/stdout）。
worker 异常退出时自动重启一次；仍失败则回退到单次子进程模式。
"""
from __future__ import annotations

import atexit
import json
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from ..config import BASE_DIR, OUTPUT_DIR, PDF_TIMEOUT

WORKER = BASE_DIR / "pdf_worker.py"
RENDER_DIR = OUTPUT_DIR / ".render"

WORKER_READY_TIMEOUT = 45   # worker 启动 + Chromium 就绪的等待上限（秒）
WORKER_MAX_LIFETIME = 3600 * 8  # worker 最长存活（超时主动轮换，防内存膨胀）


def _ensure_render_dir() -> Path:
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    return RENDER_DIR


def sweep_stale_renders(max_age_s: int = 3600) -> int:
    """清理渲染临时目录中的过期文件（进程被 kill 时的残留）。"""
    if not RENDER_DIR.exists():
        return 0
    now = time.time()
    removed = 0
    for p in RENDER_DIR.iterdir():
        try:
            if p.is_file() and now - p.stat().st_mtime > max_age_s:
                p.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def _write_html(html: str) -> Path:
    d = _ensure_render_dir()
    path = d / f"render_{uuid.uuid4().hex}.html"
    path.write_text(html, encoding="utf-8")
    return path


# ---------------------------------------------------------------- 单次子进程（兜底）


def _run_worker(args: list[str]) -> subprocess.CompletedProcess:
    # encoding="utf-8"：Windows 本地编码是 GBK，含中文的 worker 输出会解码失败
    return subprocess.run(
        [sys.executable, str(WORKER), *args],
        capture_output=True,
        encoding="utf-8",
        timeout=PDF_TIMEOUT,
        cwd=str(BASE_DIR),
    )


def _measure_once(html_path: Path) -> dict[str, Any]:
    result = _run_worker(["measure", str(html_path)])
    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(msg or "分页测量失败")
    lines = [ln for ln in result.stdout.strip().splitlines() if ln.strip()]
    return json.loads(lines[-1])


def _pdf_once(html_path: Path, pdf_path: Path, breaks: list | None) -> None:
    args = ["pdf", str(html_path), str(pdf_path)]
    if breaks:
        args.append(json.dumps(breaks))
    result = _run_worker(args)
    if result.returncode != 0 or not pdf_path.exists():
        msg = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(msg or "PDF 渲染失败")


# ---------------------------------------------------------------- 常驻 worker 池


class _WorkerPool:
    """管理一个常驻 pdf_worker serve 进程（线程安全，单请求串行）。"""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._lock = threading.RLock()  # 可重入：request() 持锁时会调用 close()
        self._next_id = 0
        self._started_at = 0.0
        self._broken = False  # 启动失败一次后永久走兜底，避免反复重试

    # ---- 生命周期 ----

    def _spawn(self) -> subprocess.Popen:
        # encoding="utf-8"：Windows 本地编码（GBK）读不了 worker 的中文输出
        proc = subprocess.Popen(
            [sys.executable, str(WORKER), "serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            encoding="utf-8",
            bufsize=1,  # 行缓冲
            cwd=str(BASE_DIR),
        )
        line = proc.stdout.readline() if proc.stdout else ""
        try:
            hello = json.loads(line) if line.strip() else {}
        except json.JSONDecodeError:
            hello = {}
        if not hello.get("ready"):
            self._kill(proc)
            raise RuntimeError(hello.get("error") or "PDF worker 启动失败")
        self._proc = proc
        self._started_at = time.time()
        return proc

    def _kill(self, proc: subprocess.Popen | None) -> None:
        if not proc:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _readline(self, proc: subprocess.Popen, timeout: float) -> str | None:
        """带超时的 readline（Windows 无 select，用读线程 + join）。"""
        box: dict[str, str] = {}

        def _read() -> None:
            try:
                box["line"] = proc.stdout.readline() if proc.stdout else ""
            except Exception:  # noqa: BLE001
                box["line"] = ""

        t = threading.Thread(target=_read, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            return None
        return box.get("line", "")

    def close(self) -> None:
        with self._lock:
            proc, self._proc = self._proc, None
            self._kill(proc)

    # ---- 请求 ----

    def request(self, payload: dict, timeout: float) -> dict:
        """发送请求并等待响应；worker 失效时自动重启一次，再失败走兜底。"""
        with self._lock:
            if self._broken:
                raise _Fallback()
            try:
                return self._request_once(payload, timeout)
            except _WorkerDead:
                pass
            # 重启一次再试
            try:
                self.close()
                return self._request_once(payload, timeout)
            except _WorkerDead as e:
                self._broken = True
                raise _Fallback() from e

    def _request_once(self, payload: dict, timeout: float) -> dict:
        try:
            proc = self._proc if self._alive() else self._spawn()
        except Exception as e:  # noqa: BLE001 启动失败按「worker 死」处理
            raise _WorkerDead(f"worker 启动失败：{e}") from e
        # 超长存活主动轮换，避免内存缓慢增长
        if time.time() - self._started_at > WORKER_MAX_LIFETIME:
            self.close()
            proc = self._spawn()

        self._next_id += 1
        rid = self._next_id
        req = {"id": rid, **payload}
        try:
            proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
            proc.stdin.flush()
        except Exception as e:  # noqa: BLE001 管道断裂 → worker 死
            raise _WorkerDead(str(e)) from e

        line = self._readline(proc, timeout)
        if line is None:
            self._kill(proc)
            self._proc = None
            raise _WorkerDead("worker 响应超时")
        if not line.strip():
            self._proc = None
            raise _WorkerDead("worker 进程退出")
        try:
            resp = json.loads(line)
        except json.JSONDecodeError as e:
            raise _WorkerDead(f"worker 响应解析失败：{line[:120]}") from e
        if resp.get("id") != rid:
            raise _WorkerDead(f"worker 响应 id 不匹配：{resp.get('id')} != {rid}")
        if not resp.get("ok"):
            raise RuntimeError(resp.get("error") or "worker 处理失败")
        return resp


class _WorkerDead(Exception):
    """worker 进程不可用（需要重启或兜底）。"""


class _Fallback(Exception):
    """常驻 worker 不可用，调用方应走单次子进程。"""


_pool = _WorkerPool()
atexit.register(_pool.close)


# ---------------------------------------------------------------- 对外 API


def _count_pdf_pages(data: bytes) -> int:
    import pymupdf

    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        return pdf.page_count


def measure_pages(doc: dict[str, Any]) -> dict[str, Any]:
    """测量简历页数与各区块落位，返回分页信息。

    页数以实际渲染的 PDF 为准（ground truth，与导出永远一致）；
    各区块落位来自 JS 原子模拟（供分页覆盖层）。
    """
    from .renderer import render_for_pdf

    d = _ensure_render_dir()
    html_path = _write_html(render_for_pdf(doc))
    pdf_path = d / f"measure_{uuid.uuid4().hex}.pdf"
    try:
        try:
            resp = _pool.request(
                {"mode": "pageinfo", "html_path": str(html_path), "pdf_path": str(pdf_path)},
                PDF_TIMEOUT,
            )
            result = resp["result"]
            actual = _count_pdf_pages(pdf_path.read_bytes())
            result["pageCount"] = actual
            return result
        except _Fallback:
            return _measure_once_with_pdf(html_path, pdf_path)
    finally:
        html_path.unlink(missing_ok=True)
        pdf_path.unlink(missing_ok=True)


def _measure_once_with_pdf(html_path: Path, pdf_path: Path) -> dict[str, Any]:
    """兜底路径：单次子进程做 JS 测量 + PDF 渲染，页数取 PDF 实际值。"""
    info = _measure_once(html_path)
    _pdf_once(html_path, pdf_path, None)
    info["pageCount"] = _count_pdf_pages(pdf_path.read_bytes())
    return info


def render_pdf_bytes(doc: dict[str, Any], breaks: list | None = None) -> bytes:
    """渲染简历为 PDF 字节流。"""
    from .renderer import render_for_pdf

    d = _ensure_render_dir()
    html_path = _write_html(render_for_pdf(doc))
    pdf_path = d / f"resume_{uuid.uuid4().hex}.pdf"
    try:
        try:
            _pool.request(
                {"mode": "pdf", "html_path": str(html_path),
                 "pdf_path": str(pdf_path), "breaks": breaks or []},
                PDF_TIMEOUT,
            )
        except _Fallback:
            _pdf_once(html_path, pdf_path, breaks)
        if not pdf_path.exists():
            raise RuntimeError("PDF 渲染失败：未生成文件")
        data = pdf_path.read_bytes()
        if not data.startswith(b"%PDF"):
            raise RuntimeError("PDF 输出无效")
        return data
    finally:
        html_path.unlink(missing_ok=True)
        pdf_path.unlink(missing_ok=True)


def render_pdf_to_file(doc: dict[str, Any], out_path: str | Path) -> Path:
    data = render_pdf_bytes(doc)
    out = Path(out_path)
    out.write_bytes(data)
    return out


def verify_pdf_fonts(pdf_bytes: bytes) -> dict[str, Any]:
    """校验 PDF 中的中文字体是否为 Type0 子集（而非 Type3 降级）。

    可变字体 / CFF webfont 被 Chromium 降级为 Type3 时文本不可检索，这是字体回归测试的核心。
    注意：Type3 字体的 basefont 可能是空字符串，不能按名字过滤（曾因过滤导致永远 ok=True）。
    """
    import re

    import pymupdf

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    fonts: set[str] = set()
    types: dict[str, str] = {}
    for page in doc:
        for f in page.get_fonts(full=True):
            # f = (xref, ext, type, basefont, name, encoding, ...)
            ftype = f[2] if len(f) > 2 else ""
            basefont = (f[3] if len(f) > 3 else "") or "(unnamed)"
            fonts.add(basefont)
            types[basefont] = ftype
    text = "".join(page.get_text() for page in doc)
    doc.close()
    type3 = [k for k, v in types.items() if "Type3" in v]
    # 文本层必须能提取出中文（乱码 / Type3 降级时提取不出真正的汉字）
    text_ok = bool(text.strip()) and bool(re.search(r"[\u4e00-\u9fff]", text))
    return {
        "fonts": sorted(fonts),
        "types": types,
        "type3": type3,
        "textExtractable": bool(text.strip()),
        "textSample": text[:120],
        "ok": not type3 and text_ok,
    }
