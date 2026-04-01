#!/usr/bin/env python3
"""检查 daily 文件中的 DOI 问题"""
import json
from pathlib import Path

# 检查几个 daily 文件
files_to_check = [
    'data/daily/2026-01-01.json',
    'data/daily/2026-03-30.json',
    'data/daily/2026-03-01.json',
]

for file_path in files_to_check:
    path = Path(file_path)
    if not path.exists():
        print(f"File not found: {file_path}")
        continue
    
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    
    print(f"\n{'='*60}")
    print(f"File: {file_path} ({len(data)} papers)")
    print('='*60)
    
    for p in data[:3]:
        print(f"\nPMID: {p.get('pmid')}")
        print(f"  Title: {p.get('title', '')[:50]}...")
        print(f"  Journal: {p.get('journal', 'N/A')}")
        print(f"  DOI: {p.get('doi', 'N/A')}")
