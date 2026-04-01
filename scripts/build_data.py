#!/usr/bin/env python3
"""
数据整合脚本
将 data/daily/*.json 合并为 web/data.json，供前端展示使用。
同时生成统计摘要 web/stats.json。
"""

import json
import logging
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent.parent
DAILY_DIR = BASE_DIR / "data" / "daily"
WEB_DIR   = BASE_DIR / "web"
OUT_FILE  = WEB_DIR / "data.json"
STATS_FILE = WEB_DIR / "stats.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def merge_all() -> list:
    """合并所有 daily JSON，去重（以 pmid 为唯一键），按发布日期倒序"""
    seen   = {}   # pmid -> record
    for f in sorted(DAILY_DIR.glob("*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                records = json.load(fh)
            for rec in records:
                pmid = str(rec.get("pmid", ""))
                if pmid and pmid not in seen:
                    seen[pmid] = rec
                elif pmid in seen:
                    # 如果已有记录 ai_done=False 而新记录 ai_done=True，则更新
                    if rec.get("ai_done") and not seen[pmid].get("ai_done"):
                        seen[pmid] = rec
        except Exception as exc:
            log.warning(f"读取 {f} 失败: {exc}")

    all_records = list(seen.values())
    # 排序：pub_date 倒序，无日期放最后
    all_records.sort(key=lambda r: r.get("pub_date", "") or "", reverse=True)
    log.info(f"共整合 {len(all_records)} 篇不重复文献")
    return all_records


def build_stats(records: list) -> dict:
    """生成统计摘要"""
    type_counts = defaultdict(int)
    year_counts = defaultdict(int)
    journal_counts = defaultdict(int)
    disease_counts = defaultdict(int)

    for rec in records:
        art_type = rec.get("article_type") or "其他"
        type_counts[art_type] += 1

        pub_date = rec.get("pub_date", "") or ""
        year = pub_date[:4] if len(pub_date) >= 4 else "未知"
        year_counts[year] += 1

        journal = rec.get("journal", "") or "未知"
        if journal:
            journal_counts[journal] += 1

        disease = (rec.get("disease", "") or "").strip()
        if disease and disease not in ("无", "（待生成）", "未描述"):
            disease_counts[disease] += 1

    return {
        "total":          len(records),
        "by_type":        dict(sorted(type_counts.items(), key=lambda x: -x[1])),
        "by_year":        dict(sorted(year_counts.items(), key=lambda x: x[0], reverse=True)),
        "top_journals":   dict(sorted(journal_counts.items(), key=lambda x: -x[1])[:20]),
        "top_diseases":   dict(sorted(disease_counts.items(), key=lambda x: -x[1])[:20]),
    }


def run():
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    all_records = merge_all()

    # 写 data.json（仅保留前端需要的字段，缩减体积）
    frontend_fields = [
        "pmid", "title", "doi", "journal", "pub_date", "fetch_date",
        "authors", "article_type", "summary_zh",
        "innovation", "limitation", "study_object",
        "disease", "sample_size", "ai_done",
    ]
    frontend_data = [
        {k: rec.get(k, "") for k in frontend_fields}
        for rec in all_records
    ]

    with open(OUT_FILE, "w", encoding="utf-8") as fh:
        json.dump(frontend_data, fh, ensure_ascii=False, separators=(",", ":"))
    log.info(f"已写入 {OUT_FILE}  ({OUT_FILE.stat().st_size // 1024} KB)")

    stats = build_stats(all_records)
    with open(STATS_FILE, "w", encoding="utf-8") as fh:
        json.dump(stats, fh, ensure_ascii=False, indent=2)
    log.info(f"已写入 {STATS_FILE}")

    return stats


if __name__ == "__main__":
    run()
