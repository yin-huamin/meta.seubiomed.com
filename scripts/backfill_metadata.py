#!/usr/bin/env python3
"""为历史记录回填 DOI（PMID → DOI），生成 data/pmid_doi_map.json。

不改写 200+ 个 daily 文件；build_data 在合并时按映射补齐。
"""

import argparse
import logging
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))

import common

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def _targets(force: bool, limit: int = None) -> list:
    records = common.load_json(common.WEB_DIR / "data.json", []) or []
    excluded = common.load_excluded()
    mapping = common.load_json(common.PMID_DOI_MAP_FILE, {}) or {}
    pmids = []
    seen = set()
    for rec in records:
        pmid = str(rec.get("pmid") or "").strip()
        if not pmid or pmid in seen:
            continue
        if common.is_excluded(rec, excluded):
            continue
        if not force and common.normalize_doi(mapping.get(pmid)):
            continue
        seen.add(pmid)
        pmids.append(pmid)
    return pmids[:limit] if limit else pmids


def run(limit: int = None, dry_run: bool = False, force: bool = False):
    import fetch_pubmed

    pmids = _targets(force, limit)
    log.info(f"待回填 DOI 的 PMID: {len(pmids)}")
    if not pmids:
        return 0
    if dry_run:
        log.info(f"dry-run 示例: {', '.join(pmids[:10])}")
        return 0

    mapping = common.load_json(common.PMID_DOI_MAP_FILE, {}) or {}
    found = total = 0
    chunk = 500
    for start in range(0, len(pmids), chunk):
        batch = pmids[start:start + chunk]
        log.info(f"EFetch {start + 1}-{start + len(batch)} / {len(pmids)}")
        try:
            details = fetch_pubmed.fetch_details(batch)
        except Exception as exc:
            log.error(f"本批失败: {exc}")
            continue
        for rec in details:
            pmid = str(rec.get("pmid") or "").strip()
            doi = common.normalize_doi(rec.get("doi"))
            total += 1
            if pmid and doi:
                mapping[pmid] = doi
                found += 1
        common.save_json(common.PMID_DOI_MAP_FILE, mapping, indent=None)
        log.info(f"  累计找到 {found} 个 DOI（已写入映射表）")

    log.info(f"完成：处理 {total} 条，找到 DOI {found} 个，映射表共 {len(mapping)} 条")
    return 0


def main():
    parser = argparse.ArgumentParser(description="回填历史 PMID→DOI 映射")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="重新抓取已有映射")
    args = parser.parse_args()
    sys.exit(run(limit=args.limit, dry_run=args.dry_run, force=args.force))


if __name__ == "__main__":
    main()
