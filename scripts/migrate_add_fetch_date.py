#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
迁移脚本：为现有历史数据添加 fetch_date 字段

对于没有 fetch_date 的记录，使用文件名中的日期作为 fetch_date
"""

import json
from pathlib import Path

# 配置
DAILY_DIR = Path(__file__).parent.parent / "data" / "daily"

def migrate():
    """为所有历史数据添加 fetch_date 字段"""
    json_files = sorted(DAILY_DIR.glob("*.json"))
    
    if not json_files:
        print("[ERROR] 未找到任何数据文件")
        return
    
    print(f"[INFO] 找到 {len(json_files)} 个数据文件")
    
    total_records = 0
    updated_records = 0
    
    for json_file in json_files:
        # 从文件名提取日期（例如：2026-03-30.json -> 2026-03-30）
        fetch_date = json_file.stem
        
        print(f"\n[FILE] 处理文件：{json_file.name}")
        
        # 读取数据
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 检查是否需要添加 fetch_date
        need_update = False
        file_updated_count = 0
        for record in data:
            total_records += 1
            if "fetch_date" not in record:
                record["fetch_date"] = fetch_date
                updated_records += 1
                file_updated_count += 1
                need_update = True
        
        # 如果有更新，保存文件
        if need_update:
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"  [OK] 已为 {file_updated_count} 条记录添加 fetch_date = {fetch_date}")
        else:
            print(f"  [SKIP] 所有记录已有 fetch_date，跳过")
    
    print(f"\n[SUCCESS] 迁移完成！")
    print(f"   总记录数：{total_records}")
    print(f"   更新记录数：{updated_records}")

if __name__ == "__main__":
    migrate()
