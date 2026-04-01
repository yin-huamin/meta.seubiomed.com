#!/usr/bin/env python3
"""
批量对 2026年1-2月 daily JSON 文件调用 DeepSeek 生成中文摘要
逐文件处理，支持断点续传（已有 ai_done=True 的记录自动跳过）
"""

import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DAILY_DIR = BASE_DIR / "data" / "daily"
SUMMARIZE_SCRIPT = BASE_DIR / "scripts" / "summarize_papers.py"

TARGET_MONTHS = ["2026-01", "2026-02"]

files = sorted([
    f for f in DAILY_DIR.glob("*.json")
    if f.name[:7] in TARGET_MONTHS
])

print(f"共 {len(files)} 个文件需要处理")

for i, f in enumerate(files, 1):
    date_str = f.stem  # e.g. 2026-01-01
    print(f"\n[{i}/{len(files)}] 处理 {f.name} ...")
    result = subprocess.run(
        [sys.executable, str(SUMMARIZE_SCRIPT), "--date", date_str],
        capture_output=False,
        text=True,
    )
    if result.returncode != 0:
        print(f"  [警告] {f.name} 处理出错，返回码 {result.returncode}")

print("\n\n[完成] 全部 1-2 月文件处理完毕！")
