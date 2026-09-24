"""Resume Studio 入口。

用法：
    python app.py                # 启动编辑器（http://localhost:5000）
    FLASK_DEBUG=1 python app.py  # 开发模式
"""
from resume_builder import main

if __name__ == "__main__":
    main()
