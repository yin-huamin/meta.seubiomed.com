#!/usr/bin/env python3
"""检查 DOI 和论文匹配问题"""
import json

with open('web/data.json', encoding='utf-8') as f:
    data = json.load(f)

print(f"Total papers: {len(data)}\n")

# 检查 DOI 前缀是否和期刊匹配
for p in data[:10]:
    doi = p.get('doi', '')
    journal = p.get('journal', '')
    title = p.get('title', '')[:60]
    print(f"PMID: {p['pmid']}")
    print(f"  Journal: {journal}")
    print(f"  DOI: {doi}")
    print(f"  Title: {title}...")
    print()
