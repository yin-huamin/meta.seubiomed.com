#!/usr/bin/env python3
"""
数据整合脚本
将 data/daily/*.json 合并为 web/data.json，供前端展示使用。
同时生成统计摘要 web/stats.json 和爬取日志 web/memory.json。
"""

import json
import logging
import os
import re
from pathlib import Path
from collections import defaultdict
import csv

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


# ── Merge daily JSONs ────────────────────────────────────────────
def merge_all() -> list:
    """合并所有 daily JSON，去重（以 pmid 为唯一键），按发布日期倒序"""
    seen = {}  # pmid -> record
    for f in sorted(DAILY_DIR.glob("*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                records = json.load(fh)
            for rec in records:
                pmid = str(rec.get("pmid", ""))
                if pmid and pmid not in seen:
                    seen[pmid] = rec
                elif pmid in seen:
                    if rec.get("ai_done") and not seen[pmid].get("ai_done"):
                        seen[pmid] = rec
        except Exception as exc:
            log.warning(f"读取 {f} 失败: {exc}")

    all_records = list(seen.values())
    all_records.sort(key=lambda r: r.get("pub_date", "") or "", reverse=True)
    log.info(f"共整合 {len(all_records)} 篇不重复文献")
    return all_records


# ── Stats ───────────────────────────────────────────────────────
def build_stats(records: list) -> dict:
    """生成统计摘要"""
    type_counts   = defaultdict(int)
    year_counts   = defaultdict(int)
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

        disease = (rec.get("disease") or "").strip()
        if disease and disease not in ("无", "（待生成）", "未描述"):
            disease_counts[disease] += 1

    return {
        "total":        len(records),
        "by_type":      dict(sorted(type_counts.items(),   key=lambda x: -x[1])),
        "by_year":      dict(sorted(year_counts.items(),   key=lambda x: x[0], reverse=True)),
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
    for rec in all_records:
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

    log.info(f"分区过滤: 排除 {excluded_count} 篇（IF<5 或 JCR Q3/Q4 或 CAS 3/4区），保留 {len(filtered)} 篇")
    all_records = filtered

    # 写 data.json（仅保留前端需要的字段，缩减体积）
    frontend_fields = [
        "pmid", "title", "doi", "journal", "pub_date",
        "journal_if", "journal_jcr", "journal_cas",
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
