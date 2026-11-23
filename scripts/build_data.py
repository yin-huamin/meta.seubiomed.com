#!/usr/bin/env python3
"""
数据整合脚本（增量模式）
以已有 web/data.json 为累积数据库，合并 data/daily/*.json 中的新增文献。
以 pmid 去重，优先保留 ai_done=True 的版本。
生成 web/data.json、web/data/YYYY.json、web/stats.json 和 web/memory.json。

daily JSON 在 build 完成后即可安全删除，不影响后续运行。
"""

import json
import logging
import os
import re
from pathlib import Path
from collections import defaultdict
import csv

import common

BASE_DIR   = Path(__file__).resolve().parent.parent
DAILY_DIR  = BASE_DIR / "data" / "daily"
WEB_DIR    = BASE_DIR / "web"
OUT_FILE   = WEB_DIR / "data.json"
STATS_FILE = WEB_DIR / "stats.json"
MEMORY_DIR = BASE_DIR / ".workbuddy" / "memory"
MEMORY_OUT = WEB_DIR / "memory.json"
TSV_PATH   = BASE_DIR / "journal_info.tsv"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ── PubMed full name → TSV standard name aliases ─────────────────
# These are journals where PubMed uses a longer/different name than
# what appears in journal_info.tsv. The normalize function alone
# cannot resolve these because of too-short or ambiguous cores.
PUBMED_ALIASES = {
    # --- High-frequency (≥5 papers) ---
    "medrxiv : the preprint server for health sciences": None,  # preprint, no IF
    "advanced science (weinheim, baden-wurttemberg, germany)": "ADVANCED SCIENCE",
    "journal of computational biology : a journal of computational molecular cell biology": "JOURNAL OF COMPUTATIONAL BIOLOGY",
    "proceedings. biological sciences": "PROCEEDINGS OF THE ROYAL SOCIETY B: BIOLOGICAL SCIENCES",
    "journal of infection and chemotherapy : official journal of the japan society of chemotherapy": "JOURNAL OF INFECTION AND CHEMOTHERAPY",
    "philosophical transactions of the royal society of london. series b, biological sciences": "PHILOSOPHICAL TRANSACTIONS OF THE ROYAL SOCIETY B: BIOLOGICAL SCIENCES",
    "genome biology and evolution": "Genome Biology and Evolution",
    "biochemical and biophysical research communications": "BIOCHEMICAL AND BIOPHYSICAL RESEARCH COMMUNICATIONS",
    "digestive diseases and sciences": "DIGESTIVE DISEASES AND SCIENCES",
    "water science and technology : a journal of the international association on water pollution research": "WATER SCIENCE AND TECHNOLOGY",
    "journal of pediatric gastroenterology and nutrition": "JOURNAL OF PEDIATRIC GASTROENTEROLOGY AND NUTRITION",
    "brain sciences": "Brain Sciences",
    "nature aging": "Nature Aging",
    "briefings in functional genomics": "Briefings in Functional Genomics",
    "nature computational science": "Nature Computational Science",
    "cancer epidemiology, biomarkers & prevention : a publication of the american association for cancer research, cosponsored by the american society of preventive oncology": "CANCER EPIDEMIOLOGY, BIOMARKERS & PREVENTION",
    "bioscience, biotechnology, and biochemistry": "BIOSCIENCE BIOTECHNOLOGY AND BIOCHEMISTRY",
    "journal of oral biosciences": "Journal of Oral Biosciences",
    "journal of clinical and experimental hepatology": "Journal of Clinical and Experimental Hepatology",
    "bioessays : news and reviews in molecular, cellular and developmental biology": "BIOESSAYS",
    "gastroenterology research and practice": "GASTROENTEROLOGY RESEARCH AND PRACTICE",
    # --- Medium-frequency (2-4 papers) ---
    "cell & bioscience": "Cell & Bioscience",
    "progress in molecular biology and translational science": None,  # book series
    "medical science monitor : international medical journal of experimental and clinical research": "MEDICAL SCIENCE MONITOR",
    "current opinion in gastroenterology": "CURRENT OPINION IN GASTROENTEROLOGY",
    "current protein & peptide science": "CURRENT PROTEIN & PEPTIDE SCIENCE",
    "jgh open : an open access journal of gastroenterology and hepatology": "JGH Open",
    "royal society open science": "Royal Society Open Science",
    "bioinformatics and biology insights": "Bioinformatics and Biology Insights",
    "journal of integrative bioinformatics": "Journal of Integrative Bioinformatics",
    "transplant immunology": "Transplant Immunology",
    "biology letters": "Biology Letters",
    "medical microbiology and immunology": "MEDICAL MICROBIOLOGY AND IMMUNOLOGY",
    "nature biomedical engineering": "Nature Biomedical Engineering",
    "philosophical transactions. series a, mathematical, physical, and engineering sciences": "PHILOSOPHICAL TRANSACTIONS OF THE ROYAL SOCIETY A: MATHEMATICAL, PHYSICAL AND ENGINEERING SCIENCES",
    "journal of cancer research and clinical oncology": "JOURNAL OF CANCER RESEARCH AND CLINICAL ONCOLOGY",
    "neurological sciences : official journal of the italian neurological society and of the italian society of clinical neurophysiology": "NEUROLOGICAL SCIENCES",
    "journal of clinical gastroenterology": "JOURNAL OF CLINICAL GASTROENTEROLOGY",
    "evolutionary bioinformatics online": "Evolutionary Bioinformatics",
    "journal of bioinformatics and computational biology": "Journal of Bioinformatics and Computational Biology",
    "clinical and translational gastroenterology": "Clinical and Translational Gastroenterology",
    "journal of periodontal & implant science": "Journal of Periodontal & Implant Science",
    "journal of diabetes investigation": "Journal of Diabetes Investigation",
    "journal of obesity & metabolic syndrome": "Journal of Obesity & Metabolic Syndrome",
    "life science alliance": "Life Science Alliance",
    "marvelous life science & technology": "Marine Life Science & Technology",
    "cellular physiology and biochemistry : international journal of experimental cellular physiology, biochemistry, and pharmacology": "CELLULAR PHYSIOLOGY AND BIOCHEMISTRY",
    "infection and immunity": "INFECTION AND IMMUNITY",
    "american journal of cancer research": "American Journal of Cancer Research",
    "diabetes, metabolic syndrome and obesity : targets and therapy": "Diabetes, Metabolic Syndrome and Obesity: Targets and Therapy",
    "journal of asthma and allergy": "Journal of Asthma and Allergy",
    "expert review of gastroenterology & hepatology": "Expert Review of Gastroenterology & Hepatology",
    "standards in genomic sciences": None,  # merged
    "peerj. computer science": "PeerJ",
    "journal of biosciences": "JOURNAL OF BIOSCIENCES",
    "human microbiome journal": "Human Microbiome Journal",
    # --- BMC journals mis-matched by substring rule ---
    "bmc gastroenterology": None,  # no IF (BMC series, ~2.5)
    "bmc pediatrics": None,  # no IF (BMC series, ~2.0)
    "bmc ophthalmology": None,  # no IF (BMC series, ~2.5)
}


# ── Journal name normalization ───────────────────────────────────
def normalize_journal_name(name: str) -> str:
    """
    Normalize a journal name for matching:
    - lowercase
    - remove leading 'the '
    - remove common suffixes: (journal), : xxx, = xxx, edition info
    - collapse whitespace
    - remove punctuation except & and /
    """
    s = name.strip().lower()
    # Remove leading "the "
    if s.startswith("the "):
        s = s[4:]
    # Remove parenthetical location info: "(oxford, england)", "(weinheim, ...)"
    s = re.sub(r"\([^)]*\)", "", s)
    # Remove ": xxx" suffixes like ": cb", ": the preprint server..."
    s = re.sub(r"\s*:\s*.*$", "", s)
    # Remove "= xxx" suffixes like "= nihon chikusan..."
    s = re.sub(r"\s*=\s*.*$", "", s)
    # Remove trailing ". xxx" ONLY if it looks like an edition/volume note,
    # e.g. ". a journal of...", ". vol. 12", ". edition 3"
    # BUT preserve ". Life sciences", ". Biological sciences" etc.
    # Strategy: only strip if the part after "." starts with a lowercase
    # common pattern word like "a ", "an ", "the ", "vol", "ed", "ser"
    dot_match = re.search(r"\.\s+(?=[a-z])", s)
    if dot_match:
        rest = s[dot_match.end():]
        first_word = rest.split()[0] if rest.split() else ""
        if first_word in ("a", "an", "the", "vol", "ed", "ser", "edition", "series",
                          "rev", "journal", "official", "international"):
            s = s[:dot_match.start()]
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    # Remove punctuation (keep & and /)
    s = re.sub(r"[,.\-:;\"'()]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ── Journal info lookup ─────────────────────────────────────────
def load_journal_lookup():
    """
    Load journal_info.tsv into multiple lookup structures.
    Returns:
      name_lut     = {normalized_name: {"if":.., "jcr":.., "cas":.., "raw":..}}
      issn_lut     = {issn_no_dash:  info_dict}
      norm_names   = set of all normalized names (for substring matching)
    """
    name_lut = {}
    issn_lut = {}
    norm_names = set()

    with open(TSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        next(reader)  # skip header
        for row in reader:
            if len(row) < 7:
                continue
            raw_name = row[0].strip()
            if_val   = row[1].strip()
            jcr      = row[2].strip()
            cas      = row[6].strip()

            info = {"if": if_val or "", "jcr": jcr or "", "cas": cas or "", "raw": raw_name}
            if raw_name:
                # Store by exact lowercase name
                name_lut[raw_name.lower()] = info
                # Also store by normalized name (if different)
                norm = normalize_journal_name(raw_name)
                if norm and norm != raw_name.lower():
                    name_lut[norm] = info
                norm_names.add(norm)

            for issn_raw in (row[4].strip(), row[5].strip()):
                if issn_raw and issn_raw != "N/A":
                    issn_key = issn_raw.replace("-", "").lower()
                    issn_lut[issn_key] = info

    log.info(f"Journal lookup loaded: {len(name_lut)} names, {len(issn_lut)} ISSNs")
    return name_lut, issn_lut, norm_names


def lookup_journal(article, name_lut, issn_lut, norm_names):
    """
    Return {"if", "jcr", "cas"} for a paper record.
    Matching priority:
      0) PubMed alias lookup (hardcoded mapping)
      1) ISSN (if available)
      2) Exact name match (case-insensitive)
      3) Normalized name match
      4) Strict substring match (≥60% length coverage, both names ≥10 chars)
    """
    jname = (article.get("journal") or "").strip()
    if not jname:
        return {"if": "", "jcr": "", "cas": ""}

    jname_lower = jname.lower()
    jname_norm  = normalize_journal_name(jname)

    # 0) PubMed alias lookup
    alias_target = PUBMED_ALIASES.get(jname_lower)
    if alias_target is not None:
        target_lower = alias_target.lower()
        if target_lower in name_lut:
            info = name_lut[target_lower]
            return {"if": info["if"], "jcr": info["jcr"], "cas": info["cas"]}
    elif jname_lower in PUBMED_ALIASES:
        # alias maps to None = explicitly skip (preprint, no IF)
        return {"if": "", "jcr": "", "cas": ""}

    # 1) ISSN (if available in article data)
    issn = (article.get("issn") or "").replace("-", "").strip().lower()
    if issn and issn in issn_lut:
        info = issn_lut[issn]
        return {"if": info["if"], "jcr": info["jcr"], "cas": info["cas"]}

    # 2) Exact name match (case-insensitive)
    if jname_lower in name_lut:
        info = name_lut[jname_lower]
        return {"if": info["if"], "jcr": info["jcr"], "cas": info["cas"]}

    # 3) Normalized name match
    if jname_norm and jname_norm in name_lut:
        info = name_lut[jname_norm]
        return {"if": info["if"], "jcr": info["jcr"], "cas": info["cas"]}

    # 4) Strict substring match
    #    Only if normalized name is ≥10 chars
    #    The shorter name must cover ≥60% of the longer name's length
    if jname_norm and len(jname_norm) >= 10:
        best_match = None
        best_ratio = 0.0
        for tnorm in norm_names:
            if len(tnorm) < 10:
                continue
            if tnorm in jname_norm or jname_norm in tnorm:
                shorter = min(len(tnorm), len(jname_norm))
                longer  = max(len(tnorm), len(jname_norm))
                ratio = shorter / longer
                if ratio >= 0.6 and ratio > best_ratio:
                    best_ratio = ratio
                    best_match = tnorm
        if best_match and best_match in name_lut:
            info = name_lut[best_match]
            return {"if": info["if"], "jcr": info["jcr"], "cas": info["cas"]}

    return {"if": "", "jcr": "", "cas": ""}


# ── Merge: existing data.json + daily JSONs ──────────────────────
def _load_existing_data() -> list:
    """加载已有的 web/data.json 作为基础数据（累积数据库）。"""
    if not OUT_FILE.exists():
        return []
    try:
        with open(OUT_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        log.warning(f"读取已有 {OUT_FILE} 失败，将从零开始: {exc}")
        return []


AI_FIELDS = ["summary_zh", "innovation", "limitation",
             "study_object", "disease", "sample_size"]


def _is_ai_complete(rec: dict) -> bool:
    """判断记录是否真的带完整 AI 注释（排除历史失败留下的“（待生成）”占位）。"""
    return all(
        str(rec.get(f) or "").strip() and "（待生成）" not in str(rec.get(f))
        for f in AI_FIELDS
    )


def _env_bool(name: str, default: bool = True) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


_IDENTITY_FIELDS = ("uid", "source", "pmid", "doi", "url",
                    "is_preprint", "published_doi", "journal_issn")


def _normalize_record(rec: dict, doi_map: dict) -> dict:
    """补齐统一身份字段，并用 pmid→doi 映射回填历史 DOI。"""
    rec = dict(rec)
    pmid = str(rec.get("pmid") or "").strip()
    if pmid and not common.normalize_doi(rec.get("doi")):
        mapped = doi_map.get(pmid)
        if mapped:
            rec["doi"] = mapped
    common.ensure_identity(rec)
    rec["is_preprint"] = bool(rec.get("is_preprint"))
    rec.setdefault("trusted_source", False)
    published = common.normalize_doi(rec.get("published_doi"))
    rec["published_doi"] = published or None
    return rec


def _merge_two(base: dict, new: dict) -> dict:
    """合并同一条论文的两个来源，保护正式版身份。"""
    if base.get("is_preprint") and not new.get("is_preprint"):
        # 正式版出现：身份字段以正式版为准
        for key in _IDENTITY_FIELDS:
            if new.get(key) not in (None, "", False):
                base[key] = new[key]
        base["is_preprint"] = False
        base["trusted_source"] = base.get("trusted_source") or new.get("trusted_source", False)
        return common.merge_record(base, {k: v for k, v in new.items()
                                          if k not in _IDENTITY_FIELDS})
    if new.get("is_preprint") and not base.get("is_preprint"):
        # 已有正式版：预印本只用于补摘要，不改变身份
        return common.merge_record(base, {k: v for k, v in new.items()
                                          if k not in _IDENTITY_FIELDS})
    return common.merge_record(base, new)


def merge_all() -> list:
    """
    增量合并：以 web/data.json 为基础，整合新增 daily JSON。
    以 uid/PMID/DOI/标题哈希的别名集合去重；已注释版本优先。
    """
    doi_map = common.load_json(common.PMID_DOI_MAP_FILE, {}) or {}
    excluded = common.load_excluded()

    records = []
    alias_index = {}
    base_count = 0
    new_count = 0
    excluded_count = 0

    def add(rec: dict):
        nonlocal excluded_count
        rec = _normalize_record(rec, doi_map)
        if common.is_excluded(rec, excluded):
            excluded_count += 1
            return False
        keys = common.alias_keys(rec)
        hit = next((alias_index[k] for k in keys if k in alias_index), None)
        if hit is None:
            records.append(rec)
            idx = len(records) - 1
            for key in keys:
                alias_index.setdefault(key, idx)
            for key in common.alias_keys(rec):
                alias_index.setdefault(key, idx)
            return True
        base = records[hit]
        _merge_two(base, rec)
        for key in common.alias_keys(base) | keys:
            alias_index.setdefault(key, hit)
        return False

    for rec in _load_existing_data():
        if add(rec):
            base_count += 1

    for f in sorted(DAILY_DIR.glob("*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                for rec in json.load(fh):
                    if add(rec):
                        new_count += 1
        except Exception as exc:
            log.warning(f"读取 {f} 失败: {exc}")

    # 正式版已存在时丢弃对应预印本
    if _env_bool("PREFER_PUBLISHED_OVER_PREPRINT", True):
        published_dois = {common.normalize_doi(r.get("doi"))
                          for r in records
                          if not r.get("is_preprint") and common.normalize_doi(r.get("doi"))}
        published_titles = {common.title_hash(r.get("title"))
                            for r in records if not r.get("is_preprint")}
        kept, dropped = [], 0
        for rec in records:
            if rec.get("is_preprint"):
                pub_doi = common.normalize_doi(rec.get("published_doi"))
                if (pub_doi and pub_doi in published_dois) or \
                   common.title_hash(rec.get("title")) in published_titles:
                    dropped += 1
                    continue
            kept.append(rec)
        if dropped:
            log.info(f"预印本去重: 丢弃 {dropped} 篇已有正式版的预印本")
        records = kept

    records.sort(key=lambda r: r.get("pub_date", "") or "", reverse=True)
    log.info(f"累积基础 {base_count} 篇 + daily 新增 {new_count} 篇 = 共 {len(records)} 篇"
             f"（排除清单跳过 {excluded_count} 篇）")
    return records


# ── Stats ───────────────────────────────────────────────────────
def build_stats(records: list) -> dict:
    """生成统计摘要"""
    type_counts   = defaultdict(int)
    year_counts   = defaultdict(int)
    journal_counts = defaultdict(int)
    disease_counts = defaultdict(int)
    source_counts = defaultdict(int)
    preprint_total = 0

    for rec in records:
        art_type = rec.get("article_type") or "其他"
        type_counts[art_type] += 1

        pub_date = rec.get("pub_date", "") or ""
        year = pub_date[:4] if len(pub_date) >= 4 else "未知"
        year_counts[year] += 1

        journal = rec.get("journal", "") or "未知"
        if journal:
            journal_counts[journal] += 1

        disease = (rec.get("disease") or "").strip()
        if disease and disease not in ("无", "（待生成）", "未描述"):
            disease_counts[disease] += 1

        source = rec.get("source") or ("pubmed" if rec.get("pmid") else "unknown")
        source_counts[source] += 1
        if rec.get("is_preprint"):
            preprint_total += 1

    return {
        "total":        len(records),
        "by_type":      dict(sorted(type_counts.items(),   key=lambda x: -x[1])),
        "by_year":      dict(sorted(year_counts.items(),   key=lambda x: x[0], reverse=True)),
        "by_source":    dict(sorted(source_counts.items(), key=lambda x: -x[1])),
        "preprint_total": preprint_total,
        "top_journals": dict(sorted(journal_counts.items(), key=lambda x: -x[1])[:20]),
        "top_diseases": dict(sorted(disease_counts.items(), key=lambda x: -x[1])[:20]),
    }


# ── Split by year (for lazy loading) ───────────────────────────
def split_by_year(records: list):
    """将数据按 pub_date 年份拆分为 web/data/YYYY.json + index.json"""
    by_year = defaultdict(list)
    for rec in records:
        y = (rec.get("pub_date") or "")[:4]
        if y and len(y) == 4:
            by_year[y].append(rec)

    data_dir = WEB_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # 已存在的年份分片若本次无记录，显式写 []，避免旧数据残留
    existing_years = {p.stem for p in data_dir.glob("*.json")
                      if p.stem.isdigit() and len(p.stem) == 4}
    for y in sorted(existing_years - set(by_year)):
        with open(data_dir / f"{y}.json", "w", encoding="utf-8") as fh:
            json.dump([], fh)
        log.info(f"  {y}: 0 篇（清空旧分片）")

    index = []
    for y in sorted(by_year):
        out_path = data_dir / f"{y}.json"
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(by_year[y], fh, ensure_ascii=False, separators=(",", ":"))
        index.append({"year": y, "count": len(by_year[y]), "file": f"data/{y}.json"})
        log.info(f"  {y}: {len(by_year[y])} 篇 -> {out_path.name}")

    index_path = data_dir / "index.json"
    with open(index_path, "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=2)
    log.info(f"已写入 {index_path}（{len(index)} 个年份）")


# ── Memory JSON ─────────────────────────────────────────────────
def generate_memory_json():
    """读取最新每日 memory 文件和 MEMORY.md，写入 web/memory.json。"""
    entries = []

    if MEMORY_DIR.exists():
        md_files = sorted(MEMORY_DIR.glob("*.md"), reverse=True)
        daily_files = [f for f in md_files if f.name != "MEMORY.md"]
        if daily_files:
            latest = daily_files[0]
            with open(latest, encoding="utf-8") as f:
                entries.append({"file": latest.name, "content": f.read().strip()})

    memory_md = MEMORY_DIR / "MEMORY.md"
    if memory_md.exists():
        with open(memory_md, encoding="utf-8") as f:
            entries.append({"file": "MEMORY.md", "content": f.read().strip()})

    MEMORY_OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(MEMORY_OUT, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    log.info(f"已写入 {MEMORY_OUT}")


def _bypass_quality(rec: dict) -> bool:
    """预印本与用户选定/可信来源不参与 IF/分区过滤。"""
    if rec.get("is_preprint") and _env_bool("BYPASS_QUALITY_FOR_PREPRINTS", True):
        return True
    if rec.get("trusted_source") and _env_bool("BYPASS_QUALITY_FOR_TRUSTED", True):
        return True
    return False


# ── Main ─────────────────────────────────────────────────────────
def run():
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    all_records = merge_all()

    # 注入期刊 IF / JCR / 中科院分区
    name_lut, issn_lut, norm_names = load_journal_lookup()
    for rec in all_records:
        info = lookup_journal(rec, name_lut, issn_lut, norm_names)
        rec["journal_if"]  = info["if"]
        rec["journal_jcr"] = info["jcr"]
        rec["journal_cas"] = info["cas"]

    # ── 过滤：IF<5 / JCR Q3,Q4 / CAS 3,4 区期刊 ──
    filtered = []
    excluded_count = 0
    bypass_count = 0
    for rec in all_records:
        if _bypass_quality(rec):
            bypass_count += 1
            filtered.append(rec)
            continue

        jcr = (rec.get("journal_jcr") or "").strip()
        cas = (rec.get("journal_cas") or "").strip()
        if_str = (rec.get("journal_if") or "").strip()
        try:
            if_val = float(if_str) if if_str else 0.0
        except ValueError:
            if_val = 0.0

        if jcr in ("Q3", "Q4"):
            excluded_count += 1
            continue
        if cas in ("3", "4"):
            excluded_count += 1
            continue
        if if_val < 5.0 and if_str:
            # 只有当 IF 有值且 <5 时才排除（无 IF 数据的不排除，由爬取阶段兜底）
            excluded_count += 1
            continue
        filtered.append(rec)

    log.info(f"分区过滤: 排除 {excluded_count} 篇（IF<5 或 JCR Q3/Q4 或 CAS 3/4区），"
             f"豁免 {bypass_count} 篇（预印本/可信来源），保留 {len(filtered)} 篇")
    all_records = filtered

    # 写 data.json（仅保留前端需要的字段，缩减体积）
    frontend_fields = [
        "uid", "pmid", "title", "doi", "url", "source", "is_preprint",
        "journal", "journal_issn", "pub_date",
        "journal_if", "journal_jcr", "journal_cas",
        "authors", "article_type", "summary_zh",
        "innovation", "limitation", "study_object",
        "disease", "sample_size", "ai_done",
    ]
    frontend_data = []
    for rec in all_records:
        item = {k: rec.get(k, "") for k in frontend_fields}
        item["is_preprint"] = bool(rec.get("is_preprint"))
        item["pmid"] = str(rec.get("pmid") or "")
        item["doi"] = common.normalize_doi(rec.get("doi")) or None
        item["uid"] = rec.get("uid") or common.record_uid(rec)
        item["url"] = rec.get("url") or common.record_url(rec)
        frontend_data.append(item)

    with open(OUT_FILE, "w", encoding="utf-8") as fh:
        json.dump(frontend_data, fh, ensure_ascii=False, separators=(",", ":"))
    log.info(f"已写入 {OUT_FILE} ({OUT_FILE.stat().st_size // 1024} KB)")

    # 按年份拆分，供前端懒加载
    split_by_year(frontend_data)

    stats = build_stats(all_records)
    with open(STATS_FILE, "w", encoding="utf-8") as fh:
        json.dump(stats, fh, ensure_ascii=False, indent=2)
    log.info(f"已写入 {STATS_FILE}")

    generate_memory_json()

    return stats


if __name__ == "__main__":
    run()
