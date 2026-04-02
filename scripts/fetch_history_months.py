#!/usr/bin/env python3
"""
PubMed 宏基因组领域论文历史月份批量搜索脚本
按照 NCBI E-utilities 使用规范合理爬取：
  - 使用 History Server (usehistory=y) 减少重复请求
  - 有 API Key: 每秒最多10请求，批次间 ≥0.15s 延迟
  - 每50条批次间额外延迟1s，防止滥用
  - 附带 tool 和 email 参数（NCBI 要求）
"""

import os
import json
import time
import datetime
import argparse
import logging
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

# ──────────────────────────── 配置区 ──────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DAILY_DIR = DATA_DIR / "daily"

KEYWORDS = ["metagenome", "metagenomic", "microbiom"]
NCBI_EMAIL = "yinhm17@126.com"
NCBI_API_KEY = "ce30363de49e75a27b8c1fdf66a48f2f8108"  # API Key：提升至10请求/秒
MAX_RESULTS_PER_QUERY = 9999  # 每次搜索最多取回数量（NCBI上限10000）

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

# ── 请求频率控制（遵守NCBI规范）──
# 有API Key时：≤10请求/秒 → 设0.15s间隔（保守，防止并发问题）
REQUEST_DELAY = 0.15          # 相邻请求最短间隔（秒）
BATCH_DELAY   = 1.0           # 每50条批次间额外延迟（秒）

# ──────────────────────────── 排除关键词（标题/摘要内容过滤）──────────────────────────────
EXCLUDE_KEYWORDS = [
    # ──── 家畜/反刍动物 ────
    "rumen", "ruminant", "bovine", "porcine", "ovine", "equine", "livestock", "feedlot", "calf", "lamb", "flock",
    "cattle", "sheep", "goat", "pig ", "swine", "horse", "donkey", "buffalo",
    
    # ──── 家禽/鸟类 ────
    "broiler", "poultry", "avian", "turkey", "duck ", "goose", "quail", "hatch",
    "chicken meat", "chicken farm", "egg production", "pullet", "laying hen", "broiler chicken",
    
    # ──── 蜜蜂/蜂类 ────
    "bee ", "honeybee", "apis ", "hive", "pollinator", "bumblebee", "stingless bee",
    
    # ──── 蚊子/蜱虫/昆虫媒介 ────
    "mosquito", "tick", "sandfly", "sand fly", "tsetse", "midge", "termite", "cockroach", "louse", "flea",
    
    # ──── 鱼类/水产养殖 ────
    "aquaculture", "aquatic farm", "shrimp farm", "oyster", "mussel", "clam ", "crab ", "lobster", "seashell",
    
    # ──── 噬菌体（只排除非临床、纯环境/水产来源的） ────
    "ocean virome", "marine virome", "marine phage", "seawater phage", "soil phage",
    
    # ──── 食品发酵（除益生菌外，全排） ────
    "cheese", "yogurt", "kefir", "beer", "wine", "coffee", "cocoa", "bread", "sourdough", "dairy ferment",
    "kimchi", "sauerkraut", "soy sauce", "vinegar", "fermented vegetable", "miso", "tempeh", "sake",
    
    # ──── 植物/土壤/农业 ────
    "plant", "plants", "rhizosphere", "soil", "leaf", "root", "crop", "rice ", "wheat", "corn ", "maize",
    "soybean", "barley", "vegetable", "fruit ", "forest", "tree ", "wood", "agricultural",
    
    # ──── 环境工程/污染/工业 ────
    "factory", "industrial", "wastewater", "sewage", "effluent", "sludge", "mound", "waste",
    "bioreactor", "remediation", "biogas", "methane", "sulfur", "biosolids",
    
    # ──── 极端环境 ────
    "permafrost", "glacier", "hot spring", "geothermal", "deep sea", "hydrothermal",
    
    # ──── 其他环境专题（非人源） ────
    "ecosystem", "biodiversity", "coastal", "sediment", "reservoir", "wetland", "mangrove", "coral reef",
    "algae", "phytoplankton", "diatom", "seaweed", "kelp", "cyanobacteria",

    # ──── 中文关键词 ────
    # 家畜
    "瘤胃", "反刍", "奶牛", "肉牛", "小牛", "羔羊", "山羊", "绵羊", "育肥猪", "仔猪", "牧场",
    # 家禽
    "蛋鸡", "肉鸡", "家禽", "禽类", "鸡舍", "鸭肉", "鹅肉", "孵化",
    # 蜜蜂
    "蜜蜂", "蜂群", "授粉", "蜂箱", "蜂巢", "养蜂",
    # 蚊子等
    "蚊子", "蜱虫", "白蛉", "螨虫", "昆虫媒介",
    # 食品/发酵（除益生菌）
    "奶酪", "酸奶", "发酵食品", "咖啡豆", "可可豆", "面包", "乳制品", "泡菜", "酱油", "味噌",
    # 植物/农业
    "植物", "土壤", "根系", "根际", "叶子", "叶片", "作物", "稻田", "农业", "菜地",
    # 环境工程
    "污水处理", "工业废水", "生物反应器", "甲烷", "硫磺", "污泥",
    # 其他环保
    "生态系统", "生物多样性", "沿海", "沉积物", "水库", "湿地", "红树林", "珊瑚礁", "藻类", "浮游植物", "海草", "海带"
]

# 安全词列表：如果文章同时包含排除词 AND 安全词，则不排除
SAFE_WORDS = [
    "human", "patient", "clinical", "cancer", "tumor", "tumour", "disease",
    "infant", "pregnan", "mouse", "mice", "murine", "rat ", "rat model",
    "gut microbi", "fecal", "stool", "blood", "serum", "urine", "saliva",
    "oral microbi", "skin microbi", "lung microbi", "vaginal microbi",
    "diabetes", "obesity", "ibd", "crohn", "colitis", "copd", "asthma",
    "alzheimer", "parkinson", "autism", "sepsis", "hiv", "hepatitis",
    "cirrhosis", "nafld", "stroke", "kidney", "renal", "bone ",
    "psoriasis", "eczema", "atopic dermatitis", "immunotherapy", "chemotherapy",
    "probiotic", "prebiotic", "synbiotic", "fecal microbiota transplantation",
    "metabolome", "biomarker", "therapeutic", "treatment", "therapy",
    "trial", "cohort", "case-control", "cross-sectional",
    "inflammation", "immune", "immunity",
    "zebrafish", "drosophila", "c. elegans", "cell line", "in vitro",
    "fishing ", "fisher",
]

# ──────────────────────────── 期刊白名单（JCR Q1/Q2，IF>3，排除含 food 字样）────────────────────────────
# 来源：2023/2024 JCR 微生物学、多学科、生物技术等相关学科分区
# 仅保留宏基因组/微生物组核心相关 & 高质量综合期刊
# 期刊名已转为小写用于匹配（实际比对时用lower()处理）
#
# 注：此白名单基于公开JCR数据，涵盖微生物学/多学科/生物信息学领域
#     Q1/Q2 且 IF > 3 的主要期刊。不在此列表中的期刊将被过滤。
JOURNAL_WHITELIST = {
    # ── 顶级综合期刊 ──
    "nature",
    "science",
    "cell",
    "the lancet",
    "lancet",
    "new england journal of medicine",
    "bmj",
    "jama",
    "science advances",
    "nature communications",
    "elife",
    "plos biology",

    # ── 微生物学顶刊 ──
    "nature reviews microbiology",
    "nature microbiology",
    "cell host & microbe",
    "cell host and microbe",
    "microbiome",
    "gut",
    "gut microbes",
    "npj biofilms and microbiomes",
    "npj biofilms & microbiomes",
    "imeta",
    "msystems",
    "mbio",
    "isme journal",
    "the isme journal",
    "isme communications",
    "microbiota",
    "microbial biotechnology",
    "microbial genomics",
    "microbiology spectrum",
    "frontiers in microbiology",
    "applied and environmental microbiology",
    "environmental microbiology",
    "environmental microbiology reports",
    "microbial ecology",
    "asm journals",
    "journal of bacteriology",
    "infection and immunity",
    "clinical microbiology reviews",
    "clinical microbiology and infection",
    "journal of clinical microbiology",
    "journal of medical microbiology",
    "fems microbiology ecology",
    "fems microbiology reviews",
    "fems microbiology letters",
    "international journal of systematic and evolutionary microbiology",
    "antonie van leeuwenhoek",
    "extremophiles",

    # ── 生物信息学/基因组学 ──
    "genome biology",
    "genome research",
    "genome medicine",
    "genomics proteomics & bioinformatics",
    "genomics",
    "bioinformatics",
    "briefings in bioinformatics",
    "plos computational biology",
    "plos genetics",
    "nucleic acids research",
    "molecular biology and evolution",
    "bmc genomics",
    "bmc bioinformatics",
    "frontiers in genetics",
    "genes",

    # ── 医学/临床 ──
    "nature medicine",
    "cell medicine",
    "journal of clinical investigation",
    "journal of hepatology",
    "hepatology",
    "gastroenterology",
    "alimentary pharmacology & therapeutics",
    "american journal of gastroenterology",
    "inflammatory bowel diseases",
    "journal of crohn's and colitis",
    "clinical gastroenterology and hepatology",
    "digestive diseases and sciences",
    "annals of internal medicine",
    "diabetes",
    "diabetologia",
    "diabetes care",
    "journal of diabetes investigation",
    "obesity",
    "international journal of obesity",
    "metabolism",
    "clinical nutrition",
    "nutrients",  # IF ~5.9, Q1
    "european journal of nutrition",
    "journal of nutrition",
    "american journal of clinical nutrition",
    "nutrition & metabolism",
    "neuroscience & biobehavioral reviews",
    "brain behavior and immunity",
    "brain, behavior, and immunity",
    "neuropsychopharmacology",
    "journal of neuroinflammation",
    "journal of psychiatric research",
    "npj schizophrenia",
    "nature mental health",
    "cancer research",
    "clinical cancer research",
    "journal of clinical oncology",
    "oncogene",
    "cancer letters",
    "international journal of cancer",
    "cancer immunology immunotherapy",

    # ── 生物技术/生物化学 ──
    "nature biotechnology",
    "nature chemical biology",
    "nature metabolism",
    "cell metabolism",
    "cell reports",
    "cell reports medicine",
    "iscience",
    "current biology",
    "plos one",
    "scientific reports",
    "molecular cell",
    "journal of biological chemistry",
    "biochemical and biophysical research communications",
    "biochemistry",
    "metabolomics",
    "journal of proteome research",
    "journal of proteomics",
    "frontiers in cell and developmental biology",

    # ── 微生物学趋势（保留） ──
    "trends in microbiology",

    # ── 其他相关高质量期刊 ──
    "journal of infection",
    "virulence",
    "emerging microbes & infections",
    "emerging infectious diseases",
    "lancet infectious diseases",
    "lancet microbe",
    "nature reviews gastroenterology & hepatology",
    "nature reviews gastroenterology and hepatology",
    "cellular and molecular life sciences",
    "international journal of molecular sciences",  # Q1, IF ~5.6
    "frontiers in immunology",
    "journal of autoimmunity",
    "immunology",
    "mucosal immunology",
    "european journal of immunology",
    "allergy",
    "journal of allergy and clinical immunology",
    "clinical and translational allergy",
    "international journal of antimicrobial agents",
    "antimicrobial agents and chemotherapy",
    "journal of antimicrobial chemotherapy",
    "pharmacological research",
    "expert opinion on drug metabolism & toxicology",
}

# 期刊排除关键词（期刊名包含以下任一关键词即排除）
EXCLUDE_JOURNAL_KEYWORDS = [
    "food",
    "environment",      # 环境类期刊
    "veterinary",       # 兽医类期刊
    "insect",           # 昆虫类期刊
    "poultry",          # 家禽类期刊
    "aquaculture",      # 水产养殖
    "ecology",          # 生态学
    "archives",         # 档案/综述类低质量期刊
]

# 新增：特定期刊排除列表（期刊名模糊匹配，不区分大小写）
# 格式：期刊名关键词（5个单词以上的期刊使用部分匹配）
EXCLUDE_JOURNALS_SPECIFIC = [
    # 完全匹配或包含以下关键词即排除
    "the journal of allergy and clinical immunology",
    "global",
    "microbial pathogenesis",
    "journal of infection in developing countries",
    "medicine",
    "scientific reports",
    "clinical microbiology and infection",
    "gut pathogens",
    "sichuan da xue xue bao",
    "international journal of molecular sciences",
    "bmc gastroenterology",
    "bmc genomics",
    "animal microbiome",
    "frontiers in bioscience",
    "investigative ophthalmology",
    "cancer research communications",
    "fish & shellfish immunology",
    "international journal of obesity",
    "european journal of clinical microbiology",
    "virus genes",
    "gene",
    "journal of chromatography",
    "analytical technologies",
    "bmj open",
    "comparative biochemistry and physiology",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

_last_request_time = 0.0


def _throttle():
    """确保相邻请求间隔符合NCBI规范（有API Key：≤10/秒）"""
    global _last_request_time
    now = time.monotonic()
    elapsed = now - _last_request_time
    if elapsed < REQUEST_DELAY:
        time.sleep(REQUEST_DELAY - elapsed)
    _last_request_time = time.monotonic()


def _get(url, params: dict, retries=5, base_delay=2.0) -> bytes:
    """带重试和频率控制的 HTTP GET"""
    params = dict(params)
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    params["tool"]  = "meta-seubiomed"
    params["email"] = NCBI_EMAIL
    full_url = url + "?" + urllib.parse.urlencode(params)

    for attempt in range(retries):
        _throttle()
        try:
            with urllib.request.urlopen(full_url, timeout=60) as resp:
                return resp.read()
        except Exception as exc:
            wait = base_delay * (2 ** attempt)  # 指数退避
            log.warning(f"请求失败 ({attempt+1}/{retries}): {exc}，等待 {wait:.1f}s 重试...")
            time.sleep(wait)
    raise RuntimeError(f"无法访问 {url}，已重试 {retries} 次")


def build_query_for_month(year: int, month: int) -> str:
    """构建按整月搜索的 PubMed 查询字符串"""
    kw_part = " OR ".join(f'"{kw}"[Title/Abstract]' for kw in KEYWORDS)
    # NCBI 日期范围格式：YYYY/MM/DD[PDAT]
    last_day = (datetime.date(year, month % 12 + 1, 1) - datetime.timedelta(days=1)).day if month < 12 \
               else 31
    start = f"{year}/{month:02d}/01"
    end   = f"{year}/{month:02d}/{last_day:02d}"
    return f"({kw_part}) AND {start}:{end}[Date - Publication]"


def search_pmids_with_history(query: str) -> tuple:
    """
    ESearch with History Server：
    返回 (pmids, total_count, webenv, query_key)
    使用 usehistory=y 将结果缓存在 NCBI 服务器，避免重复传输大量 ID
    """
    # 第一步：仅获取总数和 WebEnv/query_key
    params = {
        "db":          "pubmed",
        "term":        query,
        "retmax":      0,      # 先不取ID，只取 count
        "retmode":     "json",
        "usehistory":  "y",
    }
    raw = _get(ESEARCH_URL, params)
    data = json.loads(raw)
    result = data.get("esearchresult", {})
    total_count = int(result.get("count", 0))
    webenv    = result.get("webenv", "")
    query_key = result.get("querykey", "")
    log.info(f"  搜索总计 {total_count} 篇，WebEnv已存储于NCBI服务器")

    # 第二步：分页取回所有 PMID
    pmids = []
    batch_size = 500
    for start in range(0, total_count, batch_size):
        fetch_params = {
            "db":        "pubmed",
            "WebEnv":    webenv,
            "query_key": query_key,
            "retstart":  start,
            "retmax":    batch_size,
            "retmode":   "json",
            "usehistory": "y",
        }
        raw2 = _get(ESEARCH_URL, fetch_params)
        data2 = json.loads(raw2)
        batch_ids = data2.get("esearchresult", {}).get("idlist", [])
        pmids.extend(batch_ids)
        log.info(f"  已取回 {len(pmids)}/{total_count} 篇 PMID...")

    return pmids, total_count, webenv, query_key


def fetch_details(pmids: list) -> list:
    """EFetch：批量获取论文详情（XML格式），返回解析后列表"""
    if not pmids:
        return []

    batch_size = 50
    articles = []
    for i in range(0, len(pmids), batch_size):
        batch = pmids[i:i + batch_size]
        params = {
            "db":      "pubmed",
            "id":      ",".join(batch),
            "retmode": "xml",
            "rettype": "abstract",
        }
        raw = _get(EFETCH_URL, params)
        parsed = _parse_xml(raw)
        articles.extend(parsed)
        done = min(i + batch_size, len(pmids))
        log.info(f"  已获取详情 {done}/{len(pmids)} 篇...")
        # 每批次间额外延迟，避免对NCBI造成负担
        if done < len(pmids):
            time.sleep(BATCH_DELAY)

    return articles


def _parse_xml(raw: bytes) -> list:
    """解析 PubMed XML，提取关键字段"""
    root = ET.fromstring(raw)
    results = []
    for article in root.findall(".//PubmedArticle"):
        try:
            rec = _extract_article(article)
            results.append(rec)
        except Exception as exc:
            log.warning(f"解析论文出错: {exc}")
    return results


def _get_text(elem, path, default=""):
    node = elem.find(path)
    return (node.text or "").strip() if node is not None else default


def _extract_article(article) -> dict:
    medline = article.find("MedlineCitation")
    art     = medline.find("Article")

    # ── PMID ──
    pmid = _get_text(medline, "PMID")

    # ── 标题 ──
    title = ""
    if art.find("ArticleTitle") is not None:
        title = "".join(art.find("ArticleTitle").itertext()).strip()

    # ── 摘要 ──
    abstract_parts = []
    for ab in art.findall(".//AbstractText"):
        label = ab.get("Label") or ""
        text  = "".join(ab.itertext()).strip()
        if label:
            abstract_parts.append(f"{label}: {text}")
        else:
            abstract_parts.append(text)
    abstract = "\n".join(abstract_parts)

    # ── 发表日期 ──
    pub_date_node = art.find(".//Journal/JournalIssue/PubDate")
    if pub_date_node is not None:
        year  = _get_text(pub_date_node, "Year",  "")
        month = _get_text(pub_date_node, "Month", "")
        day   = _get_text(pub_date_node, "Day",   "")
        pub_date = "-".join(filter(None, [year, month, day]))
    else:
        pub_date = ""

    # ── DOI ──
    doi = ""
    for eid in article.findall(".//ArticleId"):
        if eid.get("IdType") == "doi":
            doi = (eid.text or "").strip()
    if not doi:
        for eid in art.findall(".//ELocationID"):
            if eid.get("EIdType") == "doi":
                doi = (eid.text or "").strip()

    # ── 期刊 ──
    journal = _get_text(art, "Journal/Title")

    # ── 作者 ──
    authors = []
    for auth in art.findall(".//Author"):
        ln = _get_text(auth, "LastName")
        fn = _get_text(auth, "ForeName")
        if ln:
            authors.append(f"{ln} {fn}".strip())
    author_str = "; ".join(authors[:5])
    if len(authors) > 5:
        author_str += " et al."

    # ── 文章类型 ──
    pub_types = []
    for pt in art.findall(".//PublicationType"):
        pub_types.append((pt.text or "").strip())
    article_type = _classify_type(pub_types, title, abstract)

    # ── MeSH关键词 ──
    mesh_terms = []
    for mh in medline.findall(".//MeshHeading/DescriptorName"):
        mesh_terms.append((mh.text or "").strip())

    # ── 关键词 ──
    kw_list = []
    for kw in medline.findall(".//Keyword"):
        kw_list.append((kw.text or "").strip())

    return {
        "pmid":         pmid,
        "title":        title,
        "doi":          doi,
        "journal":      journal,
        "pub_date":     pub_date,
        "authors":      author_str,
        "abstract":     abstract,
        "pub_types":    pub_types,
        "article_type": article_type,
        "mesh_terms":   mesh_terms,
        "keywords":     kw_list,
        # AI 摘要字段（由 summarize_papers.py 填写）
        "summary_zh":   "",
        "innovation":   "",
        "limitation":   "",
        "study_object": "",
        "disease":      "",
        "sample_size":  "",
        "ai_done":      False,
    }


def _classify_type(pub_types: list, title: str, abstract: str) -> str:
    """根据发表类型和文本关键词推断文章大类"""
    pts = " ".join(pub_types).lower()
    txt = (title + " " + abstract).lower()

    if "systematic review" in pts or "meta-analysis" in pts:
        return "系统综述/Meta分析"
    if "review" in pts:
        return "综述"
    if "benchmark" in txt or ("comparison" in txt and "tool" in txt):
        return "Benchmark"
    if "clinical trial" in pts or "randomized" in pts:
        return "临床试验"
    if "case report" in pts or "case study" in pts:
        return "案例报告"
    if "journal article" in pts:
        return "研究论文"
    return "其他"


def should_exclude_by_content(rec: dict) -> tuple:
    """
    检查文章是否应该被排除（根据标题/摘要关键词过滤，安全词保护）
    返回 (bool, reason)
    """
    text_fields = [
        rec.get("title", ""),
        rec.get("abstract", ""),
    ]
    full_text = " ".join(text_fields).lower()

    # 先检查安全词 → 有安全词则不排除
    has_safe = any(safe.lower() in full_text for safe in SAFE_WORDS)
    if has_safe:
        return False, ""

    for keyword in EXCLUDE_KEYWORDS:
        if keyword.lower() in full_text:
            return True, f"内容含排除词: {keyword}"
    return False, ""


def should_exclude_by_journal(rec: dict) -> tuple:
    """
    检查文章期刊是否应该被排除：
    1. 期刊名含排除关键词 → 排除
    2. 期刊在特定排除列表中 → 排除
    3. 期刊不在白名单 → 排除（非Q1/Q2高质量期刊）
    返回 (bool, reason)
    """
    journal = rec.get("journal", "").lower().strip()

    # 1. 排除含关键词的期刊
    for excl_kw in EXCLUDE_JOURNAL_KEYWORDS:
        if excl_kw in journal:
            return True, f"期刊含排除词: {excl_kw} ({rec.get('journal')})"

    # 2. 排除特定期刊（模糊匹配）
    for excl_journal in EXCLUDE_JOURNALS_SPECIFIC:
        # 如果排除词在期刊名中，或期刊名在排除词中（用于长期刊名部分匹配）
        if excl_journal in journal or journal in excl_journal:
            return True, f"特定期刊排除: {rec.get('journal')}"

    # 3. 不在白名单中 → 排除
    # 使用模糊匹配：白名单中任意一项是期刊名的子串，或期刊名是白名单项的子串
    for wl_journal in JOURNAL_WHITELIST:
        if wl_journal in journal or journal in wl_journal:
            return False, ""

    return True, f"期刊不在Q1/Q2白名单: {rec.get('journal')}"


def load_existing_pmids() -> set:
    """加载已下载过的所有 PMID，避免重复"""
    seen = set()
    for f in DAILY_DIR.glob("*.json"):
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            for rec in data:
                if rec.get("pmid"):
                    seen.add(str(rec["pmid"]))
        except Exception:
            pass
    return seen


def fetch_month(year: int, month: int, existing_pmids: set, dry_run: bool = False) -> list:
    """
    爬取指定年月的论文
    dry_run=True 时只统计数量，不写文件
    返回: 过滤后的文章列表
    """
    month_str = f"{year}-{month:02d}"
    log.info(f"\n{'='*60}")
    log.info(f"开始处理 {month_str}")
    log.info(f"{'='*60}")

    query = build_query_for_month(year, month)
    log.info(f"查询语句: {query}")

    # Step 1: 搜索 PMID（使用 History Server）
    pmids, total_count, webenv, query_key = search_pmids_with_history(query)
    log.info(f"NCBI返回 {len(pmids)} 篇 PMID（总计 {total_count} 篇）")

    # 过滤已有PMID
    new_pmids = [p for p in pmids if p not in existing_pmids]
    log.info(f"其中新增 {len(new_pmids)} 篇（已有 {len(pmids) - len(new_pmids)} 篇）")

    if not new_pmids:
        log.info(f"{month_str} 无新增文章，跳过")
        return []

    # Step 2: 获取详情
    log.info(f"开始获取 {len(new_pmids)} 篇文章详情...")
    details = fetch_details(new_pmids)
    log.info(f"成功获取 {len(details)} 篇文章详情")

    # Step 3: 内容过滤（标题/摘要关键词）
    after_content_filter = []
    content_excluded = 0
    for rec in details:
        excl, reason = should_exclude_by_content(rec)
        if excl:
            content_excluded += 1
            log.debug(f"  [内容过滤] PMID {rec.get('pmid')}: {reason}")
        else:
            after_content_filter.append(rec)
    log.info(f"内容过滤: 排除 {content_excluded} 篇，保留 {len(after_content_filter)} 篇")

    # Step 4: 期刊过滤（白名单 + food 排除）
    final_papers = []
    journal_excluded = 0
    journal_excluded_food = 0
    journal_excluded_q34 = 0
    for rec in after_content_filter:
        excl, reason = should_exclude_by_journal(rec)
        if excl:
            journal_excluded += 1
            if "food" in reason.lower():
                journal_excluded_food += 1
            else:
                journal_excluded_q34 += 1
            log.debug(f"  [期刊过滤] PMID {rec.get('pmid')}: {reason}")
        else:
            final_papers.append(rec)
            existing_pmids.add(str(rec["pmid"]))

    log.info(f"期刊过滤: 排除 {journal_excluded} 篇 "
             f"（food期刊: {journal_excluded_food}，Q3/Q4: {journal_excluded_q34}），"
             f"保留 {len(final_papers)} 篇")

    if dry_run:
        log.info(f"[DRY RUN] {month_str} 最终 {len(final_papers)} 篇（不写入文件）")
        return final_papers

    if not final_papers:
        log.info(f"{month_str} 过滤后无有效文章")
        return []

    # Step 5: 添加 fetch_date 并按日期分拆保存
    # 按 pub_date 分组，存入对应日期文件
    # 如果 pub_date 无法解析，统一存为月份第1天
    by_date = {}
    for rec in final_papers:
        rec["fetch_date"] = datetime.date.today().strftime("%Y-%m-%d")
        # 解析发表日期，存到对应的 daily 文件
        pd = rec.get("pub_date", "")
        # 尝试提取年月日
        file_date = f"{year}-{month:02d}-01"  # 默认
        if pd:
            parts = pd.replace(" ", "-").split("-")
            if len(parts) >= 3:
                try:
                    yr = int(parts[0])
                    mo = int(parts[1]) if parts[1].isdigit() else _month_abbr_to_num(parts[1])
                    dy = int(parts[2]) if parts[2].isdigit() else 1
                    file_date = f"{yr}-{mo:02d}-{dy:02d}"
                except Exception:
                    pass
            elif len(parts) == 2:
                try:
                    yr = int(parts[0])
                    mo = int(parts[1]) if parts[1].isdigit() else _month_abbr_to_num(parts[1])
                    file_date = f"{yr}-{mo:02d}-01"
                except Exception:
                    pass
        by_date.setdefault(file_date, []).append(rec)

    total_saved = 0
    for date_key, recs in sorted(by_date.items()):
        out_file = DAILY_DIR / f"{date_key}.json"
        if out_file.exists():
            with open(out_file, encoding="utf-8") as fh:
                old_data = json.load(fh)
            existing_in_file = {r["pmid"] for r in old_data}
            to_add = [r for r in recs if r["pmid"] not in existing_in_file]
            merged = old_data + to_add
        else:
            merged = recs
            to_add = recs
        with open(out_file, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, ensure_ascii=False, indent=2)
        total_saved += len(to_add)
        if to_add:
            log.info(f"  → 保存 {len(to_add)} 篇到 {out_file.name}")

    log.info(f"{month_str} 完成：共保存 {total_saved} 篇")
    return final_papers


def _month_abbr_to_num(abbr: str) -> int:
    """将月份缩写转为数字，如 Jan→1"""
    mapping = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4,
        "may": 5, "jun": 6, "jul": 7, "aug": 8,
        "sep": 9, "oct": 10, "nov": 11, "dec": 12
    }
    return mapping.get(abbr.lower()[:3], 1)


def run(year_months: list, dry_run: bool = False):
    """
    主入口：爬取指定的年月列表
    year_months: [(year, month), ...]
    dry_run: True → 只统计，不写文件
    """
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    existing = load_existing_pmids()
    log.info(f"已有 {len(existing)} 篇文献记录（去重用）")

    total_stats = {}
    all_results = []

    for year, month in year_months:
        papers = fetch_month(year, month, existing, dry_run=dry_run)
        key = f"{year}-{month:02d}"
        total_stats[key] = len(papers)
        all_results.extend(papers)
        # 月份之间等待，礼貌性延迟
        time.sleep(2.0)

    # 汇总报告
    log.info(f"\n{'='*60}")
    log.info("爬取汇总报告")
    log.info(f"{'='*60}")
    grand_total = 0
    for key, count in sorted(total_stats.items()):
        log.info(f"  {key}: {count} 篇")
        grand_total += count
    log.info(f"  合计: {grand_total} 篇")
    if dry_run:
        log.info("  [DRY RUN 模式，未写入文件]")

    return all_results, total_stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="PubMed 宏基因组文献历史月份批量爬取（遵守NCBI E-utilities使用规范）"
    )
    parser.add_argument(
        "--months",
        nargs="+",
        default=["2026-01", "2026-02"],
        help="目标年月列表，格式 YYYY-MM，如 2026-01 2026-02"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="仅统计数量，不写入文件"
    )
    args = parser.parse_args()

    year_months = []
    for ym in args.months:
        try:
            y, m = ym.split("-")
            year_months.append((int(y), int(m)))
        except ValueError:
            log.error(f"月份格式错误: {ym}，应为 YYYY-MM")
            exit(1)

    results, stats = run(year_months, dry_run=args.dry_run)
    print(f"\n[完成] 爬取完成，共获取 {sum(stats.values())} 篇文章")
    for k, v in sorted(stats.items()):
        print(f"   {k}: {v} 篇")
