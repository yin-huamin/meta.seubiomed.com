#!/usr/bin/env python3
"""检查AI摘要进度"""
import json
from pathlib import Path

DAILY_DIR = Path(__file__).resolve().parent.parent / "data" / "daily"

total = 0
done = 0

for f in sorted(DAILY_DIR.glob("*.json")):
    with open(f, encoding="utf-8") as fh:
        data = json.load(fh)
    for rec in data:
        total += 1
        if rec.get("ai_done"):
            done += 1

print(f"AI摘要进度: {done}/{total} ({done*100//total}%)")
print(f"待处理: {total-done} 篇")
