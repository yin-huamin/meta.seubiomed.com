#!/usr/bin/env python3
"""
PubMed 宏基因组领域论文每日搜索脚本
使用 NCBI E-utilities API 搜索最新论文
"""

import os
import re
import json
import time
import datetime
import argparse
import logging
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

# ──────────────────────────── 日期工具 ──────────────────────────────
MONTH_TO_NUM = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
    "january":   "01", "february": "02", "march":    "03",
    "april":    "04", "june":     "06", "july":     "07",
    "august":   "08", "september":"09", "october":  "10",
    "november": "11", "december": "12",
}

def _month_to_num(month_str: str) -> str:
    """将英文月份转为两位数字字符串；已是数字则直接补零。"""
    if not month_str:
        return ""
    s = month_str.strip().lower()
    if s.isdigit():
        return s.zfill(2)
    return MONTH_TO_NUM.get(s, "")


def _format_pub_date(year: str, month: str, day: str) -> str:
    """将年/月/日部件格式化为 YYYY-MM-DD / YYYY-MM / YYYY，月份为数字。"""
    m = _month_to_num(month)
    if year and m and day:
        return f"{year}-{m}-{day.zfill(2)}"
    if year and m:
        return f"{year}-{m}"
    if year:
        return year
    return ""


def _parse_date_node(node) -> str:
    """解析 PubMed 日期 XML 节点（含 Year/Month/Day），返回格式化字符串。"""
    if node is None:
        return ""
    y_node = node.find("Year")
    m_node = node.find("Month")
    d_node = node.find("Day")
    y = (y_node.text or "") if y_node is not None else ""
    m = (m_node.text or "") if m_node is not None else ""
    d = (d_node.text or "") if d_node is not None else ""
    return _format_pub_date(y, m, d)


def _is_future(date_str: str) -> bool:
    """判断日期字符串（YYYY / YYYY-MM / YYYY-MM-DD）是否在未来。"""
    if not date_str:
        return False
    try:
        parts = date_str.split("-")
        if len(parts) == 3:
            dt = datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
        elif len(parts) == 2:
            dt = datetime.date(int(parts[0]), int(parts[1]), 1)
        else:
            dt = datetime.date(int(parts[0]), 1, 1)
        return dt > datetime.date.today()
    except Exception:
        return False

# ──────────────────────────── 配置区 ──────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DAILY_DIR = DATA_DIR / "daily"

KEYWORDS = ["metagenome", "metagenomic", "microbiom"]
NCBI_EMAIL = "yinhm17@126.com"          # NCBI要求提供联系邮箱
NCBI_API_KEY = "ce30363de49e75a27b8c1fdf66a48f2f8108"                       # 可选：NCBI API Key（提速用）
MAX_RESULTS = 200                       # 每次最多取回论文数
JOURNAL_TABLE_PATH = BASE_DIR / "journal_info.tsv"   # 期刊过滤表（TSV格式）

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
    "plant", "plants", "rhizosphere", "soil", "leaf", "root", "crop", "rice", "wheat", "corn", "maize",
    "soybean", "barley", "vegetable", "fruit ", "forest", "tree", "wood", "agricultural",
    
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

# ──────────────────────────── 期刊过滤（基于 journal_info.tsv）────────────────────────────
# 从 TSV 文件加载期刊列表，支持按期刊名或 ISSN/eISSN 匹配
# TSV 格式：期刊名称 \t IF \t JCR分区 \t Category \t ISSN \t eISSN \t 中科院分区

def load_journal_table() -> dict:
    """
    加载 journal_info.tsv，返回包含期刊信息和分区数据的字典：
        {
            "name_to_info": {name_lower: {"jcr": ..., "cas": ...}},
            "issn_to_info": {issn_no_dash: {"jcr": ..., "cas": ...}},
            "norm_to_info": {norm_name: {"jcr": ..., "cas": ...}},
        }
    TSV 格式：期刊名称 \t IF \t JCR分区 \t Category \t ISSN \t eISSN \t 中科院分区
    排除规则：JCR Q3/Q4 或中科院分区 3/4 或 IF < 5.0 → 不加载（直接过滤）
    """
    name_to_info = {}
    issn_to_info = {}
    norm_to_info = {}

    if not JOURNAL_TABLE_PATH.exists():
        log.warning(f"期刊过滤表不存在: {JOURNAL_TABLE_PATH}，将跳过期刊过滤")
        return {"name_to_info": {}, "issn_to_info": {}, "norm_to_info": {}}

    with open(JOURNAL_TABLE_PATH, encoding="utf-8") as fh:
        fh.readline()  # 跳过表头
        for line in fh:
            parts = line.strip().split("\t")
            if len(parts) < 7:
                continue
            name_raw = parts[0].strip()
            try:
                if_val = float(parts[1].strip())
            except (ValueError, IndexError):
                continue
            jcr = (parts[2] or "").strip()
            cas = (parts[6] or "").strip()
            issn_raw = parts[4].strip()
            eissn_raw = parts[5].strip()

            # 跳过 JCR Q3/Q4、中科院 3/4 区、IF < 5 的期刊
            if jcr in ("Q3", "Q4"):
                continue
            if cas in ("3", "4"):
                continue
            if if_val < 5.0:
                continue
            if jcr not in ("Q1", "Q2"):
                continue
            if cas not in ("1", "2"):
                continue

            info = {"if": if_val, "jcr": jcr, "cas": cas}
            name_lower = name_raw.lower()

            name_to_info[name_lower] = info
            norm = _normalize_journal_name(name_raw)
            if norm:
                norm_to_info[norm] = info

            if issn_raw and issn_raw != "N/A":
                issn_key = issn_raw.replace("-", "").lower()
                issn_to_info[issn_key] = info
            if eissn_raw and eissn_raw != "N/A":
                eissn_key = eissn_raw.replace("-", "").lower()
                issn_to_info[eissn_key] = info

    total = len(name_to_info)
    log.info(f"已加载期刊过滤表: {total} 个期刊（IF>=5 + JCR Q1/Q2 + 中科院1/2区，来自 {JOURNAL_TABLE_PATH.name}）")
    return {
        "name_to_info": name_to_info,
        "issn_to_info": issn_to_info,
        "norm_to_info": norm_to_info,
    }


def _normalize_journal_name(name: str) -> str:
    """标准化期刊名：去前缀The、去括号、去冒号后缀、去等号后缀等"""
    s = name.strip().lower()
    if s.startswith("the "):
        s = s[4:]
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"\s*:\s*.*$", "", s)
    s = re.sub(r"\s*=\s*.*$", "", s)
    # Only strip trailing ". xxx" if it starts with common note words
    dot_match = re.search(r"\.\s+(?=[a-z])", s)
    if dot_match:
        rest = s[dot_match.end():]
        first_word = rest.split()[0] if rest.split() else ""
        if first_word in ("a", "an", "the", "vol", "ed", "ser", "edition", "series",
                          "rev", "journal", "official", "international"):
            s = s[:dot_match.start()]
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"[,.\-:;\"'()]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def should_exclude_by_journal(article_data: dict, journal_table: dict) -> tuple[bool, str]:
    """
    检查文章期刊是否应该被排除：
    1. 不在 journal_info.tsv 中（按期刊名或 ISSN 匹配）→ 排除
    2. JCR 分区为 Q3 或 Q4 → 排除
    3. 中科院分区为 4 → 排除
    4. 其他 → 保留
    journal_table: {"name_to_info": ..., "issn_to_info": ..., "norm_to_info": ...}
    返回 (bool, reason)
    """
    name_to_info = journal_table.get("name_to_info", {})
    issn_to_info = journal_table.get("issn_to_info", {})
    norm_to_info = journal_table.get("norm_to_info", {})

    if not name_to_info:
        return False, ""

    journal = (article_data.get("journal") or "").strip()
    issn    = (article_data.get("issn") or "").replace("-", "").strip()

    if not journal:
        return True, "无期刊信息"

    journal_lower = journal.lower()
    journal_norm = _normalize_journal_name(journal)

    info = None

    # 1) 精确名称匹配（忽略大小写）
    if journal_lower in name_to_info:
        info = name_to_info[journal_lower]

    # 2) ISSN 匹配（去横杠）
    if info is None and issn and issn in issn_to_info:
        info = issn_to_info[issn]

    # 3) 标准化名称精确匹配
    if info is None and journal_norm and journal_norm in norm_to_info:
        info = norm_to_info[journal_norm]

    # 4) 严格子串匹配（≥60% 覆盖率，两名称均 ≥10 字符）
    if info is None and journal_norm and len(journal_norm) >= 10:
        for tnorm, tinfo in norm_to_info.items():
            if len(tnorm) < 10:
                continue
            if tnorm in journal_norm or journal_norm in tnorm:
                shorter = min(len(tnorm), len(journal_norm))
                longer  = max(len(tnorm), len(journal_norm))
                ratio   = shorter / longer
                if ratio >= 0.6:
                    info = tinfo
                    break

    if info is None:
        return True, f"期刊不在 journal_info.tsv 中: {journal}"

    # ── 分区/IF 过滤 ──
    jcr = (info.get("jcr") or "").strip()
    cas = (info.get("cas") or "").strip()
    if_val = info.get("if", 0)

    if jcr in ("Q3", "Q4"):
        return True, f"期刊 JCR 分区为 {jcr}，已排除: {journal}"
    if cas in ("3", "4"):
        return True, f"期刊中科院分区为 {cas}，已排除: {journal}"
    if if_val < 5.0:
        return True, f"期刊 IF={if_val}<5，已排除: {journal}"

    return False, ""

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


def build_query(start_date: str, end_date: str = None) -> str:
    """
    构建 PubMed 查询字符串
    start_date: YYYY/MM/DD
    end_date:   YYYY/MM/DD（可选，若提供则使用日期范围）
    """
    kw_part = " OR ".join(f'"{kw}"[Title/Abstract]' for kw in KEYWORDS)
    if end_date and end_date != start_date:
        date_range = f"{start_date}:{end_date}[Date - Publication]"
    else:
        date_range = f"{start_date}[Date - Publication]"
    return f"({kw_part}) AND {date_range}"


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
    # 优先使用 ArticleDate（电子版日期，通常更精确）
    # 回退到 Journal/JournalIssue/PubDate
    # 若最终日期在未来，尝试从 PubMed 历史记录获取正确日期
    today = datetime.date.today()

    def _try_parse(node):
        """解析单个日期节点，返回格式化字符串。"""
        return _parse_date_node(node)

    article_date_node = art.find(".//ArticleDate")
    article_date = _try_parse(article_date_node)

    pub_date_node = art.find(".//Journal/JournalIssue/PubDate")
    pub_date = _try_parse(pub_date_node)

    # 若 PubDate 在未来，优先使用 ArticleDate
    if _is_future(pub_date) and article_date and not _is_future(article_date):
        pub_date = article_date
    # 若 PubDate 只有年份，而 ArticleDate 更精确，则使用后者
    elif pub_date and "-" not in pub_date and article_date and "-" in article_date:
        pub_date = article_date

    # 若最终日期仍在未来，尝试从 PubMed 历史记录获取
    if _is_future(pub_date):
        for pmd in article.findall(".//PubMedPubDate"):
            if pmd.get("PubStatus") in ("pubmed", "medline", "entrez"):
                candidate = _parse_date_node(pmd)
                if candidate and not _is_future(candidate):
                    pub_date = candidate
                    break

    # ── DOI（不再保存，DOI与PMID经常错位） ──
    # doi = ""  # 已禁用，统一使用 PMID 链接

    # ── 期刊 ──
    journal = _get_text(art, "Journal/Title")

    # ── ISSN ──
    issn_node = art.find("Journal/ISSN")
    issn = (issn_node.text or "").strip() if issn_node is not None else ""

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
        "doi":         None,
        "journal":     journal,
        "issn":        issn,
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


def run(target_date: str = None, days_back: int = 1,
        start_date: str = None, end_date: str = None):
    """
    两种模式：
    1. 日期范围模式（优先）：start_date [+ end_date]
    2. 逐日模式（向后兼容）：target_date + days_back
    """
    DAILY_DIR.mkdir(parents=True, exist_ok=True)

    existing = load_existing_pmids()
    journal_table = load_journal_table()
    log.info(f"已有 {len(existing)} 篇文献记录，不再重复检索")

    # ── 模式1：日期范围 ──
    if start_date:
        start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt   = (datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
                     if end_date else datetime.date.today())

        start_str = start_dt.strftime("%Y/%m/%d")
        end_str   = end_dt.strftime("%Y/%m/%d")
        out_date  = end_dt.strftime("%Y-%m-%d")

        log.info(f"📅 日期范围模式: {start_str} ~ {end_str}")

        query  = build_query(start_str, end_str)
        pmids  = search_pmids(query)
        log.info(f"  日期范围查询到 {len(pmids)} 篇 PMID")

        new_pmids = [p for p in pmids if p not in existing]
        log.info(f"  其中新增 {len(new_pmids)} 篇（过滤已有 {len(pmids)-len(new_pmids)} 篇）")

        if not new_pmids:
            log.info("无新增论文")
            return []

        details = fetch_details(new_pmids)

        # 步骤1: 内容过滤
        after_content = []
        content_excl = 0
        content_list = []
        for rec in details:
            excl, reason = should_exclude_article(rec)
            if excl:
                content_excl += 1
                content_list.append((rec, reason))
            else:
                after_content.append(rec)

        # 步骤2: 期刊过滤
        final = []
        journal_excl = 0
        journal_list = []
        for rec in after_content:
            excl, reason = should_exclude_by_journal(rec, journal_table)
            if excl:
                journal_excl += 1
                journal_list.append((rec, reason))
            else:
                final.append(rec)
                existing.add(str(rec["pmid"]))

        for rec in final:
            rec["fetch_date"] = out_date

        log.info(f"  内容过滤: 排除 {content_excl} 篇，保留 {len(after_content)} 篇")
        log.info(f"  期刊过滤: 排除 {journal_excl} 篇，保留 {len(final)} 篇")

        # 论文汇总展示
        log.info("")
        log.info("=" * 80)
        log.info(f"  📋 本次搜索论文汇总（共 {len(details)} 篇）")
        log.info("=" * 80)
        if final:
            log.info(f"  ✅ 已收录 ({len(final)} 篇):")
            for i, rec in enumerate(final, 1):
                log.info(f"    [{i}] PMID {rec.get('pmid')} | {rec.get('journal', 'N/A')}")
                log.info(f"        {rec.get('title', 'N/A')}")
        if content_list:
            log.info(f"  🚫 内容过滤排除 ({len(content_list)} 篇):")
            for i, (rec, reason) in enumerate(content_list, 1):
                log.info(f"    [{i}] PMID {rec.get('pmid')} | {rec.get('journal', 'N/A')}")
                log.info(f"        {rec.get('title', 'N/A')}")
                log.info(f"        原因: {reason}")
        if journal_list:
            log.info(f"  📵 期刊过滤排除 ({len(journal_list)} 篇):")
            for i, (rec, reason) in enumerate(journal_list, 1):
                log.info(f"    [{i}] PMID {rec.get('pmid')} | {rec.get('journal', 'N/A')}")
                log.info(f"        {rec.get('title', 'N/A')}")
                log.info(f"        原因: {reason}")
        log.info("=" * 80)
        log.info("")

        # 保存
        out_file = DAILY_DIR / f"{out_date}.json"
        if out_file.exists():
            with open(out_file, encoding="utf-8") as fh:
                old_data = json.load(fh)
            existing_in_file = {r["pmid"] for r in old_data}
            merged = old_data + [r for r in final if r["pmid"] not in existing_in_file]
        else:
            merged = final

        with open(out_file, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, ensure_ascii=False, indent=2)
        log.info(f"已保存 {len(final)} 篇新论文 → {out_file}")

        return final

    # ── 模式2：逐日（向后兼容）──
    else:
        if not target_date:
            target_date = datetime.date.today().strftime("%Y-%m-%d")

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

            # 内容过滤
            after_content = []
            content_excl = 0
            content_list = []
            for rec in details:
                excl, reason = should_exclude_article(rec)
                if excl:
                    content_excl += 1
                    content_list.append((rec, reason))
                else:
                    after_content.append(rec)

            # 期刊过滤
            final = []
            journal_excl = 0
            journal_list = []
            for rec in after_content:
                excl, reason = should_exclude_by_journal(rec, journal_table)
                if excl:
                    journal_excl += 1
                    journal_list.append((rec, reason))
                else:
                    final.append(rec)
                    existing.add(str(rec["pmid"]))

            for rec in final:
                rec["fetch_date"] = target_date

            log.info(f"  内容过滤: 排除 {content_excl} 篇，保留 {len(after_content)} 篇")
            log.info(f"  期刊过滤: 排除 {journal_excl} 篇，保留 {len(final)} 篇")

            # 论文汇总展示
            log.info("")
            log.info("=" * 80)
            log.info(f"  📋 本次搜索论文汇总（共 {len(details)} 篇）")
            log.info("=" * 80)
            if final:
                log.info(f"  ✅ 已收录 ({len(final)} 篇):")
                for i, rec in enumerate(final, 1):
                    log.info(f"    [{i}] PMID {rec.get('pmid')} | {rec.get('journal', 'N/A')}")
                    log.info(f"        {rec.get('title', 'N/A')}")
            if content_list:
                log.info(f"  🚫 内容过滤排除 ({len(content_list)} 篇):")
                for i, (rec, reason) in enumerate(content_list, 1):
                    log.info(f"    [{i}] PMID {rec.get('pmid')} | {rec.get('journal', 'N/A')}")
                    log.info(f"        {rec.get('title', 'N/A')}")
                    log.info(f"        原因: {reason}")
            if journal_list:
                log.info(f"  📵 期刊过滤排除 ({len(journal_list)} 篇):")
                for i, (rec, reason) in enumerate(journal_list, 1):
                    log.info(f"    [{i}] PMID {rec.get('pmid')} | {rec.get('journal', 'N/A')}")
                    log.info(f"        {rec.get('title', 'N/A')}")
                    log.info(f"        原因: {reason}")
            log.info("=" * 80)
            log.info("")

            all_new.extend(final)
            time.sleep(1)

        if all_new:
            out_file = DAILY_DIR / f"{target_date}.json"
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
    parser.add_argument("--date",       default=None, help="目标日期 YYYY-MM-DD（默认今天）")
    parser.add_argument("--days-back",  type=int, default=1, help="往前搜索天数（默认1）")
    parser.add_argument("--start-date", default=None, help="日期范围起始 YYYY-MM-DD（优先）")
    parser.add_argument("--end-date",   default=None, help="日期范围结束 YYYY-MM-DD（默认今天）")
    args = parser.parse_args()
    run(target_date=args.date, days_back=args.days_back,
        start_date=args.start_date, end_date=args.end_date)
