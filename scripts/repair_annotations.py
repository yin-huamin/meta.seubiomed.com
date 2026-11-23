#!/usr/bin/env python3
"""
修复历史“伪注释”记录（ai_done=True 但字段为“（待生成）”）。

流程：
1. 扫描 web/data.json 找出注释不完整的记录
2. 从 data/daily/*.json 复用已有摘要，缺失的按 PMID 从 PubMed 补抓
3. 汇总写入 data/daily/<date>.json（ai_done=False），交给 summarize_papers.py 重新注释

用法：
    python scripts/repair_annotations.py                 # 写入今天
    python scripts/repair_annotations.py --date 2026-11-23
    python scripts/repair_annotations.py --dry-run       # 只统计不写文件
"""

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))

import common

DAILY_DIR = BASE_DIR / "data" / "daily"
WEB_DATA = BASE_DIR / "web" / "data.json"

AI_FIELDS = ["summary_zh", "innovation", "limitation",
             "study_object", "disease", "sample_size"]
PENDING_MARK = "（待生成）"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def needs_repair(rec: dict) -> bool:
    return any(
        not str(rec.get(f) or "").strip() or PENDING_MARK in str(rec.get(f))
        for f in AI_FIELDS
    )


def load_local_abstracts() -> dict:
    """从所有 daily 文件中收集 PMID → abstract。"""
    abstracts = {}
    for f in sorted(DAILY_DIR.glob("*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                for rec in json.load(fh):
                    pmid = str(rec.get("pmid") or "")
                    if pmid and rec.get("abstract"):
                        abstracts[pmid] = rec["abstract"]
        except Exception as exc:
            log.warning(f"读取 {f.name} 失败: {exc}")
    return abstracts


def main():
    parser = argparse.ArgumentParser(description="修复“（待生成）”伪注释记录")
    parser.add_argument("--date", default=date.today().strftime("%Y-%m-%d"),
                        help="写入的 daily 日期，默认今天")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写文件")
    args = parser.parse_args()

    if not WEB_DATA.exists():
        log.error(f"找不到 {WEB_DATA}")
        return 1

    with open(WEB_DATA, encoding="utf-8") as fh:
        web_records = json.load(fh)

    excluded = common.load_excluded()
    broken = [
        r for r in web_records
        if r.get("pmid") and needs_repair(r) and not common.is_excluded(r, excluded)
    ]
    log.info(f"web/data.json 共 {len(web_records)} 篇，注释不完整 {len(broken)} 篇")
    if not broken:
        return 0

    abstracts = load_local_abstracts()
    missing = [str(r["pmid"]) for r in broken if str(r["pmid"]) not in abstracts]
    log.info(f"本地已有摘要 {len(broken) - len(missing)} 篇，需从 PubMed 补抓 {len(missing)} 篇")

    if missing:
        import fetch_pubmed
        fetched = fetch_pubmed.fetch_details(missing)
        for rec in fetched:
            pmid = str(rec.get("pmid") or "")
            if pmid:
                abstracts[pmid] = rec.get("abstract") or ""
        log.info(f"PubMed 返回 {len(fetched)} 篇，其中含摘要 "
                 f"{sum(1 for p in missing if abstracts.get(p))} 篇")

    if args.dry_run:
        no_abs = [p for p in missing if not abstracts.get(p)]
        log.info(f"[dry-run] 无摘要 PMID: {len(no_abs)}")
        if no_abs[:10]:
            log.info(f"  示例: {', '.join(no_abs[:10])}")
        return 0

    target = DAILY_DIR / f"{args.date}.json"
    if target.exists():
        with open(target, encoding="utf-8") as fh:
            existing = json.load(fh)
    else:
        existing = []

    by_pmid = {str(r.get("pmid")): r for r in existing}
    added = updated = no_abstract = 0

    for rec in broken:
        pmid = str(rec["pmid"])
        abstract = abstracts.get(pmid, "")
        if not abstract:
            no_abstract += 1

        item = dict(rec)
        item["abstract"] = abstract
        item["ai_done"] = False
        for f in AI_FIELDS:
            item[f] = PENDING_MARK

        if pmid in by_pmid:
            current = by_pmid[pmid]
            if abstract and not current.get("abstract"):
                current["abstract"] = abstract
            current["ai_done"] = False
            for f in AI_FIELDS:
                current[f] = PENDING_MARK
            updated += 1
        else:
            existing.append(item)
            by_pmid[pmid] = item
            added += 1

    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(existing, fh, ensure_ascii=False, indent=2)

    log.info(f"已写入 {target.name}：新增 {added} 篇，待重试 {updated} 篇，"
             f"无摘要 {no_abstract} 篇（共 {len(existing)} 篇）")
    log.info(f"下一步: python metaweb.py summarize --date {args.date}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
