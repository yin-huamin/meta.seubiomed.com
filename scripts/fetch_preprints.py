#!/usr/bin/env python3
"""抓取 bioRxiv / medRxiv 最新预印本，按主题过滤后写入 daily JSON。"""

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))

import common
import topic_keywords

common.load_env()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

API = "https://api.biorxiv.org/details"
DEFAULT_SERVERS = ("biorxiv", "medrxiv")
# 置空表示拉取全部类别，再由主题关键词过滤（服务端已不支持 category 路径）
DEFAULT_CATEGORIES = ()


def _get_json(url: str, tries: int = 4):
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "meta-seubiomed/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())
        except Exception as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"请求失败 {url}: {last}")


def iter_server(server: str, start: str, end: str):
    """按日期范围翻页拉取；服务端不支持 category 路径，分类在本地过滤。"""
    cursor = 0
    while True:
        url = f"{API}/{server}/{start}/{end}/{cursor}"
        data = _get_json(url)
        messages = data.get("messages") or []
        status = (messages[0].get("status") if messages else "") or ""
        collection = data.get("collection") or []
        if "no posts" in status.lower() or not collection:
            break
        for item in collection:
            yield item
        total = messages[0].get("total") if messages else None
        if total is not None and cursor + len(collection) >= int(total):
            break
        cursor += len(collection)
        time.sleep(1.0)


def parse_item(item: dict, server: str):
    doi = common.normalize_doi(item.get("doi"))
    title = str(item.get("title") or "").strip().rstrip(".")
    if not doi or not title:
        return None
    authors = [a.strip() for a in str(item.get("authors") or "").split(",") if a.strip()]
    author_str = "; ".join(authors[:5]) + (" et al." if len(authors) > 5 else "")
    published = common.normalize_doi(item.get("published"))

    rec = {
        "uid": f"doi:{doi}",
        "source": server,
        "pmid": "",
        "doi": doi,
        "title": title,
        "journal": "bioRxiv" if server == "biorxiv" else "medRxiv",
        "issn": "",
        "journal_issn": "",
        "pub_date": str(item.get("date") or ""),
        "authors": author_str,
        "abstract": str(item.get("abstract") or "").strip(),
        "pub_types": ["Preprint"],
        "article_type": "研究论文",
        "keywords": [str(item.get("category") or "")],
        "is_preprint": True,
        "trusted_source": True,
        "published_doi": published or None,
        "summary_zh": "", "innovation": "", "limitation": "",
        "study_object": "", "disease": "", "sample_size": "",
        "ai_done": False,
    }
    rec["url"] = common.record_url(rec)
    return rec


def _date_window(days: int, start=None, end=None) -> tuple:
    end_date = end or date.today().strftime("%Y-%m-%d")
    if start:
        start_date = start
    else:
        start_date = (datetime.strptime(end_date, "%Y-%m-%d").date()
                      - timedelta(days=max(1, days) - 1)).strftime("%Y-%m-%d")
    return start_date, end_date


def run(start_date=None, end_date=None, days=7, servers=None, categories=None,
        dry_run=False, limit=None):
    start, end = _date_window(days, start_date, end_date)
    servers = servers or [s.strip() for s in
                          os.environ.get("PREPRINT_SERVERS", ",".join(DEFAULT_SERVERS)).split(",")
                          if s.strip()]
    categories = categories or [c.strip() for c in
                                os.environ.get("PREPRINT_CATEGORIES",
                                               ",".join(DEFAULT_CATEGORIES)).split(",")
                                if c.strip()]

    excluded = common.load_excluded()
    existing = common.load_existing_keys(include_excluded=False)

    found = {}
    stats = {"seen": 0, "topic_skip": 0, "existing": 0, "excluded": 0,
             "published_dup": 0}
    log.info(f"预印本窗口 {start} ~ {end}，servers={servers}，categories={categories}")

    allowed = {c.lower() for c in categories} if categories else set()
    for server in servers:
        log.info(f"  {server}")
        try:
            for item in iter_server(server, start, end):
                cat = str(item.get("category") or "").lower()
                if allowed and cat not in allowed:
                    continue
                rec = parse_item(item, server)
                if not rec:
                    continue
                stats["seen"] += 1
                if rec["uid"] in found:
                    continue
                if common.is_excluded(rec, excluded):
                    stats["excluded"] += 1
                    continue
                if common.alias_keys(rec) & existing:
                    stats["existing"] += 1
                    continue
                pub_doi = common.normalize_doi(rec.get("published_doi"))
                if pub_doi and f"doi:{pub_doi}" in existing:
                    stats["published_dup"] += 1
                    continue
                ok, hits = topic_keywords.matches(topic_keywords.record_text(rec))
                if not ok:
                    stats["topic_skip"] += 1
                    continue
                rec["topic_hits"] = hits
                found[rec["uid"]] = rec
                if limit and len(found) >= limit:
                    break
        except Exception as exc:
            log.warning(f"  {server} 失败: {exc}")
        if limit and len(found) >= limit:
            break

    log.info(f"统计: {stats} | 主题命中 {len(found)} 篇")
    if dry_run:
        for rec in list(found.values())[:15]:
            log.info(f"  [{rec['source']}] {rec.get('pub_date')} | "
                     f"{str(rec.get('title') or '')[:90]}")
        log.info("dry-run：未写入 daily 文件")
        return len(found)

    if found:
        target = common.DAILY_DIR / f"{end}.json"
        added = common.merge_into_daily(target, list(found.values()))
        log.info(f"写入 {target.name}: 新增 {added} 篇（本地去重后）")
    else:
        log.info("无新增预印本")
    return len(found)


def main():
    parser = argparse.ArgumentParser(description="抓取 bioRxiv/medRxiv 预印本")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--server", nargs="+", default=None, choices=["biorxiv", "medrxiv"])
    parser.add_argument("--category", nargs="+", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    n = run(start_date=args.start_date, end_date=args.end_date, days=args.days,
            servers=args.server, categories=args.category,
            dry_run=args.dry_run, limit=args.limit)
    sys.exit(0 if n >= 0 else 1)


if __name__ == "__main__":
    main()
