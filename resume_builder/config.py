"""Resume Studio - 配置与路径。"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
FONTS_DIR = BASE_DIR / "fonts"
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"
OUTPUT_DIR = BASE_DIR / "output"
DB_PATH = DATA_DIR / "resumes.db"

# 服务端口
PORT = 5000

# PDF 渲染子进程超时（秒）
PDF_TIMEOUT = 90

# 允许跨域的本地来源
ALLOWED_ORIGINS = [
    "http://localhost:5000",
    "http://127.0.0.1:5000",
]

# 页边距硬下限（mm）= 0.5in，ATS/可读性底线
MIN_PAGE_MARGIN_MM = 12.7
MAX_PAGE_MARGIN_MM = 25.0


def ensure_dirs() -> None:
    for d in (TEMPLATES_DIR, FONTS_DIR, DATA_DIR, STATIC_DIR, OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)
