#!/usr/bin/env python3
"""按期刊名单抓取最新论文：Europe PMC 为主，OpenAlex 补量。

只使用公开 API 获取元数据与摘要，不解析期刊 HTML。
输出统一写入 data/daily/YYYY-MM-DD.json，供 classify/summarize/build 复用。
"""

import argparse
import html
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
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

EPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
OPENALEX_WORKS = "https://api.openalex.org/works"
BATCH_SIZE = 25
REQUEST_DELAY = 0.6
UA_EMAIL = os.environ.get("OPENALEX_MAILTO") or os.environ.get("NCBI_EMAIL") or "yinhm17@126.com"

BAD_PUB_TYPES = {
    "news", "editorial", "comment", "published erratum", "correction",
    "retraction of publication", "retraction", "expression of concern",
    "letter", "biography", "interview",
}
BAD_TITLE_PREFIX = ("author correction", "correction to", "retraction",
                    "erratum", "editorial", "response to")


# ──────────────────────────── 期刊名单 ────────────────────────────

def valid_issn(issn: str) -> bool:
    s = re.sub(r"[^0-9Xx]", "", str(issn or "")).upper()
    if len(s) != 8:
        return False
    total = sum((10 if c == "X" else int(c)) * (8 - i) for i, c in enumerate(s))
    return total % 11 == 0


def load_sources(path: Path) -> list:
    if not path.exists():
        log.error(f"找不到期刊名单: {path}")
        return []
    rows = []
    with open(path, encoding="utf-8") as fh:
        lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
    if not lines:
        return rows
    header = lines[0].lower().split("\t")
    has_header = "name" in header or "issn" in header
    body = lines[1:] if has_header else lines
    for ln in body:
        cols = ln.split("\t")
        cols += [""] * (6 - len(cols))
        name, issn, eissn, preprint, enabled, priority = [c.strip() for c in cols[:6]]
        if enabled == "0" or preprint == "1":
            continue
        issns = [x for x in (issn, eissn) if valid_issn(x)]
        if not issns:
            log.warning(f"跳过无有效 ISSN 的期刊: {name}")
            continue
        rows.append({"name": name, "issns": issns, "priority": priority})
    return rows


# ──────────────────────────── HTTP ────────────────────────────

def _get_json(url: str, params: dict = None, tries: int = 4):
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(
                full, headers={"User-Agent": f"meta-seubiomed/1.0 (mailto:{UA_EMAIL})"})
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in (429, 500, 502, 503, 504):
                break
            time.sleep(2 ** attempt)
        except Exception as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"请求失败 {full}: {last}")


# ──────────────────────────── Europe PMC ────────────────────────────

def epmc_query(issns: list, start: str, end: str) -> str:
    # 注意：ISSN 值不能加引号，否则 Europe PMC 返回 0 命中
    issn_part = " OR ".join(f"ISSN:{i}" for i in issns)
    return f"({issn_part}) AND (FIRST_PDATE:[{start} TO {end}]) AND SRC:MED"


def iter_epmc(query: str):
    cursor = "*"
    while True:
        data = _get_json(EPMC_SEARCH, {
            "query": query,
            "format": "json",
            "resultType": "core",
            "pageSize": 1000,
            "sort": "P_PDATE_D desc",
            "cursorMark": cursor,
        })
        results = (data.get("resultList") or {}).get("result") or []
        for item in results:
            yield item
        next_cursor = data.get("nextCursorMark")
        if not results or not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
        time.sleep(REQUEST_DELAY)


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    return [str(value)]


def parse_epmc(item: dict):
    pub_types = _as_list((item.get("pubTypeList") or {}).get("pubType"))
    lower_types = {t.lower() for t in pub_types}
    title = html.unescape(str(item.get("title") or ""))
    title = re.sub(r"<[^>]+>", "", title).strip().rstrip(".")
    if not title or (lower_types & BAD_PUB_TYPES):
        return None
    if title.lower().startswith(BAD_TITLE_PREFIX):
        return None

    jinfo = (item.get("journalInfo") or {}).get("journal") or {}
    journal = jinfo.get("title") or item.get("journalTitle") or ""
    issn = jinfo.get("issn") or jinfo.get("essn") or ""
    pub_date = (item.get("firstPublicationDate")
                or item.get("electronicPublicationDate")
                or item.get("printPublicationDate") or "")
    doi = common.normalize_doi(item.get("doi"))
    pmid = str(item.get("pmid") or "").strip()
    abstract = str(item.get("abstractText") or "").strip()

    author_str = str(item.get("authorString") or "")
    authors = [a.strip() for a in author_str.split(",") if a.strip()]
    author_str = "; ".join(authors[:5])
    if len(authors) > 5:
        author_str += " et al."

    keywords = _as_list((item.get("keywordList") or {}).get("keyword"))

    import fetch_pubmed
    article_type = fetch_pubmed._classify_type(pub_types, title, abstract)

    rec = {
        "uid": f"pmid:{pmid}" if pmid else (f"doi:{doi}" if doi else ""),
        "source": "europepmc",
        "pmid": pmid,
        "doi": doi or None,
        "title": title,
        "journal": journal,
        "issn": issn,
        "journal_issn": issn,
        "pub_date": pub_date,
        "authors": author_str,
        "abstract": abstract,
        "pub_types": pub_types,
        "article_type": article_type,
        "keywords": keywords,
        "is_preprint": False,
        "trusted_source": True,
        "summary_zh": "", "innovation": "", "limitation": "",
        "study_object": "", "disease": "", "sample_size": "",
        "ai_done": False,
    }
    rec["url"] = common.record_url(rec)
    return rec


# ──────────────────────────── OpenAlex ────────────────────────────

def _deinvert(index: dict) -> str:
    if not index:
        return ""
    positions = []
    for word, pos_list in index.items():
        for pos in pos_list:
            positions.append((int(pos), word))
    positions.sort()
    return " ".join(w for _, w in positions)


def openalex_url(issns: list, start: str, end: str, cursor: str = "*") -> tuple:
    filter_str = (f"primary_location.source.issn:{'|'.join(issns)},"
                  f"from_publication_date:{start},to_publication_date:{end},"
                  f"type:article|review")
    return OPENALEX_WORKS, {
        "filter": filter_str,
        "sort": "publication_date:desc",
        "per-page": 200,
        "cursor": cursor,
        "select": "id,doi,ids,title,publication_date,type,primary_location,"
                  "abstract_inverted_index,authorships",
        "mailto": UA_EMAIL,
    }


def iter_openalex(issns: list, start: str, end: str):
    cursor = "*"
    while True:
        url, params = openalex_url(issns, start, end, cursor)
        data = _get_json(url, params)
        results = data.get("results") or []
        for item in results:
            yield item
        next_cursor = (data.get("meta") or {}).get("next_cursor")
        if not results or not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
        time.sleep(0.3)


def parse_openalex(item: dict):
    title = re.sub(r"<[^>]+>", "", str(item.get("title") or "")).strip().rstrip(".")
    if not title:
        return None
    ids = item.get("ids") or {}
    pmid_url = str(ids.get("pmid") or "")
    m = re.search(r"(\d+)\s*$", pmid_url)
    pmid = m.group(1) if m else ""
    doi = common.normalize_doi(item.get("doi"))
    source_info = (item.get("primary_location") or {}).get("source") or {}
    journal = source_info.get("display_name") or ""
    issn_list = source_info.get("issn") or []
    issn = issn_list[0] if isinstance(issn_list, list) and issn_list else ""
    pub_date = str(item.get("publication_date") or "")
    abstract = _deinvert(item.get("abstract_inverted_index") or {})
    authors = [((a.get("author") or {}).get("display_name") or "")
               for a in (item.get("authorships") or [])]
    authors = [a for a in authors if a]
    author_str = "; ".join(authors[:5]) + (" et al." if len(authors) > 5 else "")
    otype = str(item.get("type") or "")
    pub_types = ["Review"] if otype == "review" else ["Journal Article"]

    import fetch_pubmed
    article_type = fetch_pubmed._classify_type(pub_types, title, abstract)

    rec = {
        "uid": f"pmid:{pmid}" if pmid else (f"doi:{doi}" if doi else ""),
        "source": "openalex",
        "pmid": pmid,
        "doi": doi or None,
        "title": title,
        "journal": journal,
        "issn": issn,
        "journal_issn": issn,
        "pub_date": pub_date,
        "authors": author_str,
        "abstract": abstract,
        "pub_types": pub_types,
        "article_type": article_type,
        "keywords": [],
        "is_preprint": False,
        "trusted_source": True,
        "summary_zh": "", "innovation": "", "limitation": "",
        "study_object": "", "disease": "", "sample_size": "",
        "ai_done": False,
    }
    rec["url"] = common.record_url(rec)
    return rec


# ──────────────────────────── 主流程 ────────────────────────────

def _date_window(days: int, start=None, end=None) -> tuple:
    end_date = end or date.today().strftime("%Y-%m-%d")
    if start:
        start_date = start
    else:
        start_date = (datetime.strptime(end_date, "%Y-%m-%d").date()
                      - timedelta(days=max(1, days) - 1)).strftime("%Y-%m-%d")
    return start_date, end_date


def run(start_date=None, end_date=None, days=7, sources_file=None,
        dry_run=False, use_openalex=True, limit=None):
    if os.environ.get("ENABLE_OPENALEX", "1").strip().lower() in ("0", "false", "no", "off"):
        use_openalex = False
    sources_file = Path(sources_file) if sources_file else common.JOURNAL_SOURCES_FILE
    sources = load_sources(sources_file)
    if not sources:
        log.error("期刊名单为空，无法抓取")
        return 0

    start, end = _date_window(days, start_date, end_date)
    issns = sorted({i for s in sources for i in s["issns"]})
    sel = load_excludes_and_existing()
    log.info(f"期刊 {len(sources)} 本 / ISSN {len(issns)} 个，窗口 {start} ~ {end}")

    found = {}
    stats = {"epmc": 0, "openalex": 0, "topic_skip": 0,
             "excluded": 0, "existing": 0, "wrong_journal": 0}

    def consider(rec):
        if not rec:
            return
        if not rec.get("uid"):
            return
        if rec["uid"] in found:
            return
        if common.is_excluded(rec, sel["excluded"]):
            stats["excluded"] += 1
            return
        if common.alias_keys(rec) & sel["existing"]:
            stats["existing"] += 1
            return
        ok, hits = topic_keywords.matches(topic_keywords.record_text(rec))
        if not ok:
            stats["topic_skip"] += 1
            return
        rec["topic_hits"] = hits
        found[rec["uid"]] = rec

    # Europe PMC
    for i in range(0, len(issns), BATCH_SIZE):
        batch = issns[i:i + BATCH_SIZE]
        query = epmc_query(batch, start, end)
        log.info(f"Europe PMC ISSN 批次 {i // BATCH_SIZE + 1}: "
                 f"{batch[0]} ... {batch[-1]}")
        try:
            for item in iter_epmc(query):
                rec = parse_epmc(item)
                if rec:
                    consider(rec)
                    stats["epmc"] += 1
                if limit and len(found) >= limit:
                    break
        except Exception as exc:
            log.error(f"Europe PMC 批次失败: {exc}")
        if limit and len(found) >= limit:
            break
        time.sleep(REQUEST_DELAY)

    # OpenAlex 补量
    if use_openalex and (not limit or len(found) < limit):
        for i in range(0, len(issns), BATCH_SIZE):
            batch = issns[i:i + BATCH_SIZE]
            try:
                for item in iter_openalex(batch, start, end):
                    rec = parse_openalex(item)
                    if rec:
                        consider(rec)
                        stats["openalex"] += 1
                    if limit and len(found) >= limit:
                        break
            except Exception as exc:
                log.error(f"OpenAlex 批次失败: {exc}")
            if limit and len(found) >= limit:
                break

    # Europe PMC 部分 ahead-of-print 记录缺摘要，按 PMID 从 PubMed 补齐
    missing = [r["pmid"] for r in found.values()
               if r.get("pmid") and not (r.get("abstract") or "").strip()]
    if missing:
        try:
            import fetch_pubmed
            details = fetch_pubmed.fetch_details(missing)
            by_pmid = {str(d.get("pmid")): d for d in details}
            enriched = 0
            for rec in found.values():
                detail = by_pmid.get(str(rec.get("pmid") or ""))
                if detail and detail.get("abstract"):
                    rec["abstract"] = detail["abstract"]
                    enriched += 1
            log.info(f"摘要补全(PubMed): {enriched}/{len(missing)} 篇")
        except Exception as exc:
            log.warning(f"PubMed 摘要补全失败: {exc}")

    # 仍缺摘要的，用 OpenAlex DOI 记录兜底
    still = [r for r in found.values()
             if r.get("doi") and not (r.get("abstract") or "").strip()]
    if still:
        fixed = 0
        for rec in still:
            try:
                url = "https://api.openalex.org/works/" + urllib.parse.quote(
                    "https://doi.org/" + rec["doi"], safe="")
                obj = _get_json(url, {"mailto": UA_EMAIL})
                abstract = _deinvert(obj.get("abstract_inverted_index") or {})
                if abstract:
                    rec["abstract"] = abstract
                    fixed += 1
            except Exception:
                continue
        log.info(f"摘要补全(OpenAlex): {fixed}/{len(still)} 篇")

    # 仍无摘要的非综述记录不入库（无法生成有意义的 AI 摘要）
    no_abs = [uid for uid, r in found.items()
              if not (r.get("abstract") or "").strip()
              and r.get("article_type") not in ("综述", "系统综述/Meta分析")]
    for uid in no_abs:
        found.pop(uid, None)
    if no_abs:
        log.info(f"丢弃无摘要记录 {len(no_abs)} 篇")

    log.info(f"统计: {stats} | 主题命中待入库 {len(found)} 篇")
    if dry_run:
        for rec in list(found.values())[:15]:
            log.info(f"  [{rec['source']}] {rec.get('pub_date')} | "
                     f"{rec.get('journal')} | {str(rec.get('title') or '')[:80]}")
        log.info("dry-run：未写入 daily 文件")
        return len(found)

    if found:
        target = common.DAILY_DIR / f"{end}.json"
        added = common.merge_into_daily(target, list(found.values()))
        log.info(f"写入 {target.name}: 新增 {added} 篇（本地去重后）")
    else:
        log.info("无新增期刊论文")
    return len(found)


def load_excludes_and_existing():
    return {
        "excluded": common.load_excluded(),
        "existing": common.load_existing_keys(include_excluded=False),
    }


def main():
    parser = argparse.ArgumentParser(description="按期刊名单抓取最新论文")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--sources", default=None, help="期刊名单 TSV")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-openalex", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    n = run(start_date=args.start_date, end_date=args.end_date, days=args.days,
            sources_file=args.sources, dry_run=args.dry_run,
            use_openalex=not args.no_openalex, limit=args.limit)
    sys.exit(0 if n >= 0 else 1)


if __name__ == "__main__":
    main()
