#!/usr/bin/env python3
"""
LLM 摘要完成监听器

每30秒检查一次进度，当所有论文都完成 AI 摘要后：
1. 运行 build_data.py
2. 启动本地预览（python serve.py）
3. 输出完成通知
"""

import os
import sys
import time
import json
import subprocess
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent
DAILY_DIR = BASE_DIR / "data" / "daily"
BUILD_SCRIPT = BASE_DIR / "scripts" / "build_data.py"
SERVE_SCRIPT = BASE_DIR / "serve.py"
LOG_FILE = DAILY_DIR / "auto_build.log"


def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def check_progress():
    total = 0
    done = 0
    for f in DAILY_DIR.glob("*.json"):
        if f.name == "memory.json":
            continue
        try:
            data = json.load(open(f, encoding="utf-8"))
            total += len(data)
            done += sum(1 for r in data if r.get("ai_done"))
        except Exception:
            pass
    return total, done


def run_build():
    log = open(LOG_FILE, "a", encoding="utf-8")
    log.write(f"\n[{ts()}] 所有 LLM 摘要完成，开始运行 build_data.py...\n")
    log.flush()

    result = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT)],
        cwd=str(BASE_DIR),
        stdout=log,
        stderr=log,
        timeout=600,
    )

    log.write(f"[{ts()}] build_data.py 完成，返回码: {result.returncode}\n")
    log.flush()
    return result.returncode == 0


def main():
    print(f"[{ts()}] LLM 摘要完成监听器已启动")
    print(f"[{ts()}] 监控目录: {DAILY_DIR}")
    print(f"[{ts()}] 日志文件: {LOG_FILE}")
    print(f"[{ts()}] 每30秒检查一次进度...\n")

    while True:
        total, done = check_progress()
        remaining = total - done
        pct = done / total * 100 if total > 0 else 0

        print(f"[{ts()}] 进度: {done}/{total} ({pct:.1f}%)  剩余: {remaining} 篇")

        if remaining == 0:
            print(f"\n[{ts()}] ✓ 所有 LLM 摘要已完成!")
            break

        time.sleep(30)

    # 运行 build_data.py
    print(f"\n[{ts()}] 开始运行 build_data.py...")
    ok = run_build()

    if ok:
        print(f"[{ts()}] ✓ build_data.py 完成!")
        print(f"[{ts()}] 现在可以运行: python serve.py (端口 8089)")
    else:
        print(f"[{ts()}] ✗ build_data.py 失败，请检查日志: {LOG_FILE}")

    print(f"\n[{ts()}] 监听器结束")


if __name__ == "__main__":
    main()
