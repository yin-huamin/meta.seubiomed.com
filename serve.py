#!/usr/bin/env python3
"""
本地开发服务器：在 web/ 目录启动 HTTP 服务，方便预览
"""

import http.server
import socketserver
import os
from pathlib import Path

PORT = 8089
WEB_DIR = Path(__file__).resolve().parent / "web"

os.chdir(WEB_DIR)

Handler = http.server.SimpleHTTPRequestHandler

with socketserver.TCPServer(("", PORT), Handler) as httpd:
    print(f"[OK] 服务器已启动: http://localhost:{PORT}")
    print("     按 Ctrl+C 停止")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[INFO] 服务器已停止")
