#!/usr/bin/env python3
"""
PubMed 宏基因组领域论文每日搜索脚本
使用 NCBI E-utilities API 搜索最新论文
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
NCBI_EMAIL = "yinhm17@126.com"          # NCBI要求提供联系邮箱
NCBI_API_KEY = "ce30363de49e75a27b8c1fdf66a48f2f8108"                       # 可选：NCBI API Key（提速用）
MAX_RESULTS = 200                       # 每次最多取回论文数

# 需要排除的关键词
# 排除范围：
#   1. 环境/水产噬菌体、病毒（非人源临床）
#   2. 所有食品发酵类（除益生菌外）
#   3. 家畜、家禽、蜜蜂、蚊子等非人源动物
#   4. 植物、土壤、农业相关
#   5. 环保/工业污染相关
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
    # 保留：人源临床、医学相关的phage研究
    # 排除：ocean virome, marine phage, fish virome等纯环境来源
    "ocean virome", "marine virome", "marine phage", "seawater phage", "soil phage",
    
    # ──── 食品发酵（除益生菌外，全排）────
    "cheese", "yogurt", "kefir", "beer", "wine", "coffee", "cocoa", "bread", "sourdough", "dairy ferment",
    "kimchi", "sauerkraut", "soy sauce", "vinegar", "fermented vegetable", "miso", "tempeh", "sake",
    
    # ──── 植物/土壤/农业 ────
    "plant", "plants", "rhizosphere", "soil", "leaf", "root", "crop", "rice ", "wheat", "corn ", "maize",
    "soybean", "barley", "vegetable", "fruit ", "forest", "tree ", "wood", "agricultural",
    
    # ──── 环境工程/污染/工业 ────
    "factory", "industrial", "wastewater", "sewage", "effluent", "sludge", "mound", "waste",
    "bioreactor", "remediation", "biogas", "methane", "sulfur", "biosolids",
    
    # ──── 极端环境（大部分排除，医学应用除外） ────
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
# 用于防止误杀（如 FISH荧光原位杂交被 fish 误匹配）
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
    "fishing ",     # 捕鱼相关 ≠ fish 鱼类
    "fisher",       # Fisher's test 等 ≠ fish 鱼类
]

# ──────────────────────────── 期刊白名单（JCR Q1/Q2，IF>3，排除含 food 字样）────────────────────────────
# 来源：2023/2024 JCR 微生物学、多学科、生物技术等相关学科分区
# 仅保留宏基因组/微生物组核心相关 & 高质量综合期刊
# 期刊名已转为小写用于匹配（实际比对时用lower()处理）
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
    "nutrients",
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
    "international journal of molecular sciences",
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

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ──────────────────────────── 工具函数 ────────────────────────────

def _get(url, params: dict, retries=5, delay=2.0) -> bytes:
    """带重试的 HTTP GET"""
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    params["tool"]  = "meta-seubiomed"
    params["email"] = NCBI_EMAIL
    full_url = url + "?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(full_url, timeout=60) as resp:
                return resp.read()
        except Exception as exc:
            wait = delay * (attempt + 1)
            log.warning(f"请求失败 ({attempt+1}/{retries}): {exc}，等待 {wait:.1f}s 重试...")
            time.sleep(wait)
    raise RuntimeError(f"无法访问 {url}，已重试 {retries} 次")


def build_query(date_str: str) -> str:
    """构建 PubMed 查询字符串，date_str 格式 YYYY/MM/DD"""
    kw_part = " OR ".join(f'"{kw}"[Title/Abstract]' for kw in KEYWORDS)
    return f"({kw_part}) AND {date_str}[Date - Publication]"


def should_exclude_article(article_data: dict) -> tuple[bool, str]:
    """检查文章是否应该被排除（根据关键词过滤，安全词保护）"""
    # 收集所有文本内容用于匹配
    text_fields = [
        article_data.get("title", ""),
        article_data.get("abstract", ""),
    ]
    full_text = " ".join(text_fields).lower()

    # 先检查是否包含安全词 → 有安全词则不排除
    has_safe = any(safe.lower() in full_text for safe in SAFE_WORDS)
    if has_safe:
        return False, ""

    # 检查是否包含任何排除关键词
    for keyword in EXCLUDE_KEYWORDS:
        if keyword.lower() in full_text:
            return True, f"内容含排除词: {keyword}"
    return False, ""


def should_exclude_by_journal(article_data: dict) -> tuple[bool, str]:
    """
    检查文章期刊是否应该被排除：
    1. 期刊名含排除关键词 → 排除
    2. 期刊在特定排除列表中 → 排除
    3. 期刊不在白名单 → 排除（非Q1/Q2高质量期刊）
    返回 (bool, reason)
    """
    journal = article_data.get("journal", "").lower().strip()

    # 1. 排除含关键词的期刊
    for excl_kw in EXCLUDE_JOURNAL_KEYWORDS:
        if excl_kw in journal:
            return True, f"期刊含排除词: {excl_kw} ({article_data.get('journal')})"

    # 2. 排除特定期刊（模糊匹配）
    for excl_journal in EXCLUDE_JOURNALS_SPECIFIC:
        # 如果排除词在期刊名中，或期刊名在排除词中（用于长期刊名部分匹配）
        if excl_journal in journal or journal in excl_journal:
            return True, f"特定期刊排除: {article_data.get('journal')}"

    # 3. 不在白名单中 → 排除
    # 使用模糊匹配：白名单中任意一项是期刊名的子串，或期刊名是白名单项的子串
    for wl_journal in JOURNAL_WHITELIST:
        if wl_journal in journal or journal in wl_journal:
            return False, ""

    return True, f"期刊不在Q1/Q2白名单: {article_data.get('journal')}"


def search_pmids(query: str) -> list:
    """ESearch：返回 PMID 列表"""
    params = {
        "db":      "pubmed",
        "term":    query,
        "retmax":  MAX_RESULTS,
        "retmode": "json",
        "sort":    "relevance",
    }
    raw = _get(ESEARCH_URL, params)
    if not raw:
        log.warning("NCBI API 返回空响应")
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        log.error(f"JSON 解析失败: {e}")
        return []
    pmids = data.get("esearchresult", {}).get("idlist", [])
    log.info(f"搜索到 {len(pmids)} 篇 PMID")
    return pmids


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
        articles.extend(_parse_xml(raw))
        time.sleep(0.5)          # 礼貌性延迟
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
    title = _get_text(art, "ArticleTitle")
    # 去掉 XML 内嵌标签残留文字
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
        "pmid":        pmid,
        "title":       title,
        "doi":         doi,
        "journal":     journal,
        "pub_date":    pub_date,
        "authors":     author_str,
        "abstract":    abstract,
        "pub_types":   pub_types,
        "article_type": article_type,
        "mesh_terms":  mesh_terms,
        "keywords":    kw_list,
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
    if "benchmark" in txt or "comparison" in txt and "tool" in txt:
        return "Benchmark"
    if "clinical trial" in pts or "randomized" in pts:
        return "临床试验"
    if "case report" in pts or "case study" in pts:
        return "案例报告"
    if "journal article" in pts:
        return "研究论文"
    return "其他"


# ──────────────────────────── 主流程 ──────────────────────────────

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


def run(target_date: str = None, days_back: int = 1):
    """
    target_date: YYYY-MM-DD，默认今天
    days_back:   往前搜索多少天
    """
    DAILY_DIR.mkdir(parents=True, exist_ok=True)

    if not target_date:
        target_date = datetime.date.today().strftime("%Y-%m-%d")

    existing = load_existing_pmids()
    log.info(f"已有 {len(existing)} 篇文献记录，不再重复检索")

    # 支持跨多天搜索
    base_dt = datetime.datetime.strptime(target_date, "%Y-%m-%d").date()
    all_new = []

    for delta in range(days_back):
        day = base_dt - datetime.timedelta(days=delta)
        date_str = day.strftime("%Y/%m/%d")
        log.info(f"正在搜索 {date_str} 的新论文...")

        query = build_query(date_str)
        pmids = search_pmids(query)

        new_pmids = [p for p in pmids if p not in existing]
        log.info(f"  其中新增 {len(new_pmids)} 篇（过滤已有 {len(pmids)-len(new_pmids)} 篇）")

        if not new_pmids:
            continue

        details = fetch_details(new_pmids)

        # 步骤1: 内容过滤（关键词）
        after_content_filter = []
        content_excluded = 0
        for rec in details:
            excl, reason = should_exclude_article(rec)
            if excl:
                content_excluded += 1
                log.debug(f"  [内容过滤] PMID {rec.get('pmid')}: {reason}")
            else:
                after_content_filter.append(rec)

        # 步骤2: 期刊过滤（白名单 + food 排除）
        final_papers = []
        journal_excluded = 0
        for rec in after_content_filter:
            excl, reason = should_exclude_by_journal(rec)
            if excl:
                journal_excluded += 1
                log.debug(f"  [期刊过滤] PMID {rec.get('pmid')}: {reason}")
            else:
                final_papers.append(rec)
                existing.add(str(rec["pmid"]))

        # 给每条记录添加爬取日期（当天日期）
        for rec in final_papers:
            rec["fetch_date"] = target_date

        log.info(f"  内容过滤: 排除 {content_excluded} 篇，保留 {len(after_content_filter)} 篇")
        log.info(f"  期刊过滤: 排除 {journal_excluded} 篇，保留 {len(final_papers)} 篇")
        filtered_details = final_papers

        all_new.extend(filtered_details)

        time.sleep(1)

    if all_new:
        out_file = DAILY_DIR / f"{target_date}.json"
        # 若当天文件已存在则合并
        if out_file.exists():
            with open(out_file, encoding="utf-8") as fh:
                old_data = json.load(fh)
            existing_in_file = {r["pmid"] for r in old_data}
            merged = old_data + [r for r in all_new if r["pmid"] not in existing_in_file]
        else:
            merged = all_new

        with open(out_file, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, ensure_ascii=False, indent=2)
        log.info(f"已保存 {len(all_new)} 篇新论文 → {out_file}")
    else:
        log.info("今日无新增论文")

    return all_new


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PubMed 宏基因组文献每日抓取")
    parser.add_argument("--date",      default=None, help="目标日期 YYYY-MM-DD（默认今天）")
    parser.add_argument("--days-back", type=int, default=1, help="往前搜索天数（默认1）")
    args = parser.parse_args()
    run(target_date=args.date, days_back=args.days_back)
