#!/usr/bin/env python3
"""
清空所有 daily 文件中的 DOI 字段
"""
import json
import os
from pathlib import Path

def clear_doi_from_file(filepath):
    """清空单个文件中的所有 DOI"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            papers = json.load(f)
        
        if not isinstance(papers, list):
            return 0
        
        count = 0
        for paper in papers:
            if 'doi' in paper and paper['doi']:
                paper['doi'] = None
                count += 1
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(papers, f, ensure_ascii=False, indent=2)
        
        return count
    except Exception as e:
        print(f"  错误: {e}")
        return 0

def main():
    daily_dir = Path('data/daily')
    
    if not daily_dir.exists():
        print("错误: data/daily 目录不存在")
        return
    
    json_files = sorted(daily_dir.glob('*.json'))
    print(f"找到 {len(json_files)} 个 daily 文件")
    
    total_cleared = 0
    for filepath in json_files:
        # 跳过空文件
        if filepath.stat().st_size <= 2:
            print(f"跳过空文件: {filepath.name}")
            continue
        
        count = clear_doi_from_file(filepath)
        if count > 0:
            print(f"[OK] {filepath.name}: 清空 {count} 个 DOI")
            total_cleared += count
        else:
            print(f"[--] {filepath.name}: 无需处理")
    
    print(f"\n总计清空 {total_cleared} 个 DOI")
    
    # 重新生成 web/data.json
    print("\n重新生成 web/data.json...")
    os.system('python scripts/build_data.py')
    print("完成!")

if __name__ == '__main__':
    main()
