#!/usr/bin/env python3
"""跨脚本共享工具：论文身份(uid)、DOI、排除清单、JSON 读写与 daily 合并。

纯标准库实现，供 fetch_pubmed / fetch_journals / fetch_preprints /
classify_scope / scope_purge / build_data / summarize 复用。
"""

import hashlib
import json
import os
import re
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DAILY_DIR = DATA_DIR / "daily"
WEB_DIR = BASE_DIR / "web"

EXCLUDED_FILE = DATA_DIR / "excluded_pmids.json"
SCOPE_STATE_FILE = DATA_DIR / "scope_classification.json"
SCOPE_OVERRIDES_FILE = DATA_DIR / "scope_overrides.json"
SCOPE_REVIEW_FILE = DATA_DIR / "scope_review.tsv"
PURGE_STATE_FILE = DATA_DIR / "purge_state.json"
PMID_DOI_MAP_FILE = DATA_DIR / "pmid_doi_map.json"
JOURNAL_SOURCES_FILE = DATA_DIR / "journals_sources.tsv"

AI_FIELDS = ["summary_zh", "innovation", "limitation",
             "study_object", "disease", "sample_size"]
PENDING_MARK = "（待生成）"


def load_env(path=None):
    """加载 config.env，不覆盖已存在的环境变量。"""
    path = Path(path) if path else (BASE_DIR / "config.env")
    if not path.exists():
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")


# ──────────────────────────── 标识与 URL ────────────────────────────

def normalize_doi(raw) -> str:
    """规范化 DOI：去 URL/doi: 前缀，小写，校验 10.xxxx/yyy 格式。"""
    if not raw:
        return ""
    s = str(raw).strip().lower()
    s = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", s)
    s = s.rstrip(".,;")
    return s if _DOI_RE.match(s) else ""


def normalize_title(title) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(title or "").lower()).strip()


def title_hash(title) -> str:
    norm = normalize_title(title)
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16] if norm else ""


def record_uid(rec: dict) -> str:
    """稳定主键：uid > pmid > doi > 标题哈希。"""
    uid = str(rec.get("uid") or "").strip()
    if uid:
        return uid
    pmid = str(rec.get("pmid") or "").strip()
    if pmid:
        return f"pmid:{pmid}"
    doi = normalize_doi(rec.get("doi"))
    if doi:
        return f"doi:{doi}"
    th = title_hash(rec.get("title"))
    return f"title:{th}" if th else ""


def alias_keys(rec: dict) -> set:
    """同一篇论文可能携带的多个可匹配键。"""
    keys = set()
    uid = str(rec.get("uid") or "").strip()
    if uid:
        keys.add(uid)
    pmid = str(rec.get("pmid") or "").strip()
    if pmid:
        keys.add(f"pmid:{pmid}")
    doi = normalize_doi(rec.get("doi"))
    if doi:
        keys.add(f"doi:{doi}")
    # 标题哈希只用于无 PMID 的记录（预印本/纯 DOI）兜底匹配。
    # 有 PMID 时不再按标题合并，避免不同论文同标题被误并。
    if not pmid:
        th = title_hash(rec.get("title"))
        if th:
            keys.add(f"title:{th}")
    return keys


def record_url(rec: dict) -> str:
    if rec.get("url"):
        return str(rec["url"])
    pmid = str(rec.get("pmid") or "").strip()
    if pmid:
        return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    doi = normalize_doi(rec.get("doi"))
    if doi:
        return f"https://doi.org/{doi}"
    return ""


def ensure_identity(rec: dict) -> dict:
    """补齐 uid/source/url/is_preprint/journal_issn 等统一字段（原地修改）。"""
    doi = normalize_doi(rec.get("doi"))
    if doi:
        rec["doi"] = doi
    rec["uid"] = record_uid(rec)
    rec.setdefault("source", "pubmed" if rec.get("pmid") else "unknown")
    rec.setdefault("is_preprint", False)
    rec["url"] = record_url(rec)
    if not rec.get("journal_issn"):
        rec["journal_issn"] = rec.get("issn") or ""
    return rec


# ──────────────────────────── JSON IO ────────────────────────────

def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save_json(path, obj, indent=2):
    """原子写入，避免中断产生半截 JSON。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=indent)
    os.replace(tmp, path)


# ──────────────────────────── 排除清单 ────────────────────────────

def load_excluded(path=EXCLUDED_FILE) -> dict:
    """返回 {items, uids, pmids, dois, title_hashes}。"""
    data = load_json(path, {}) or {}
    items = data.get("items") or {}
    uids, pmids, dois, ths = set(), set(), set(), set()
    for uid, item in items.items():
        uids.add(uid)
        if item.get("pmid"):
            pmids.add(str(item["pmid"]))
        doi = normalize_doi(item.get("doi"))
        if doi:
            dois.add(doi)
        if item.get("title"):
            th = title_hash(item["title"])
            if th:
                ths.add(th)
    return {"items": items, "uids": uids, "pmids": pmids,
            "dois": dois, "title_hashes": ths, "updated": data.get("updated")}


def is_excluded(rec: dict, excluded: dict = None) -> bool:
    if excluded is None:
        excluded = load_excluded()
    uid = str(rec.get("uid") or "").strip()
    if uid and uid in excluded["uids"]:
        return True
    pmid = str(rec.get("pmid") or "").strip()
    if pmid and pmid in excluded["pmids"]:
        return True
    doi = normalize_doi(rec.get("doi"))
    if doi and doi in excluded["dois"]:
        return True
    th = title_hash(rec.get("title"))
    return bool(th and th in excluded["title_hashes"])


def save_excluded(items: dict, updated=None):
    save_json(EXCLUDED_FILE, {
        "version": 1,
        "updated": updated or date.today().strftime("%Y-%m-%d"),
        "items": items,
    })


def load_purge_state() -> dict:
    return load_json(PURGE_STATE_FILE, {}) or {}


def save_purge_state(state: dict):
    save_json(PURGE_STATE_FILE, state)


# ──────────────────────────── 合并 ────────────────────────────

def _is_ai_complete(rec: dict) -> bool:
    return all(
        str(rec.get(f) or "").strip() and PENDING_MARK not in str(rec.get(f))
        for f in AI_FIELDS
    )


def merge_record(base: dict, new: dict) -> dict:
    """把 new 合并进 base：不丢已有 AI 注释，补齐空字段。"""
    for key, value in new.items():
        if value in (None, "", [], {}):
            continue
        if key in AI_FIELDS and base.get("ai_done") and str(base.get(key) or "").strip():
            continue
        if key == "abstract" and base.get("abstract"):
            continue
        base[key] = value
    if new.get("ai_done"):
        base["ai_done"] = True
    if not base.get("uid"):
        base["uid"] = record_uid(base)
    return base


def merge_into_daily(path, new_records: list) -> int:
    """按 uid/别名合并写入 daily JSON，返回新增条数。"""
    path = Path(path)
    existing = load_json(path, []) or []
    index = {}
    for i, rec in enumerate(existing):
        for key in alias_keys(rec):
            index.setdefault(key, i)

    added = 0
    for rec in new_records:
        ensure_identity(rec)
        keys = alias_keys(rec)
        hit = next((index[k] for k in keys if k in index), None)
        if hit is None:
            existing.append(rec)
            idx = len(existing) - 1
            for key in keys:
                index.setdefault(key, idx)
            added += 1
        else:
            merge_record(existing[hit], rec)
            for key in alias_keys(existing[hit]):
                index.setdefault(key, hit)

    save_json(path, existing)
    return added


def load_existing_keys(include_excluded: bool = True) -> set:
    """web/data.json + 所有 daily 的别名键；可选并入排除清单。"""
    keys = set()
    for rec in load_json(WEB_DIR / "data.json", []) or []:
        keys.update(alias_keys(rec))
    for f in DAILY_DIR.glob("*.json"):
        for rec in load_json(f, []) or []:
            keys.update(alias_keys(rec))
    if include_excluded:
        ex = load_excluded()
        keys.update(ex["uids"])
        keys.update(f"pmid:{p}" for p in ex["pmids"])
        keys.update(f"doi:{d}" for d in ex["dois"])
        keys.update(f"title:{t}" for t in ex["title_hashes"])
    return keys
