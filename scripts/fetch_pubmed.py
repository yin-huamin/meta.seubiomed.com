#!/usr/bin/env python3
"""
PubMed 三代测序+表观遗传学论文每日搜索脚本
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

# 三代测序关键词（至少包含一个）
LONG_READ_KEYWORDS = ["nanopore", "pacbio", "ont", "long-read sequencing", "third-generation sequencing"]
# 表观遗传学关键词（至少包含一个）
EPIGENETIC_KEYWORDS = ["epigenetic", "methylation", "5-methylcytosine", "5mc", "DNA methylation", "epigenomics"]
NCBI_EMAIL = "yinhm17@126.com"          # NCBI要求提供联系邮箱
NCBI_API_KEY = ""  # NCBI API Key
MAX_RESULTS = 200                       # 每次最多取回论文数

# 需要排除的关键词（植物、土壤、工厂、污水等）
EXCLUDE_KEYWORDS = [
    # 英文
    "plant", "plants", "rhizosphere", "soil", "leaf", "root", "crop",
    "factory", "industrial", "wastewater", "sewage", "effluent",
    # 中文
    "植物", "土壤", "根系", "根际", "叶子", "叶片", "作物",
    "工厂", "污水", "废水", "污泥"
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
    
    # 添加浏览器User-Agent以避免被封锁
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    for attempt in range(retries):
        try:
            req = urllib.request.Request(full_url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
                if not data:
                    log.warning(f"响应为空 ({attempt+1}/{retries})")
                    if attempt < retries - 1:
                        wait = delay * (attempt + 1)
                        time.sleep(wait)
                        continue
                return data
        except Exception as exc:
            wait = delay * (attempt + 1)
            log.warning(f"请求失败 ({attempt+1}/{retries}): {exc}，等待 {wait:.1f}s 重试...")
            time.sleep(wait)
    
    # 最后一次重试失败时，记录调试信息
    log.error(f"请求URL: {full_url[:200]}...")
    raise RuntimeError(f"无法访问 {url}，已重试 {retries} 次")


def build_query(date_str: str) -> str:
    """构建 PubMed 查询字符串，date_str 格式 YYYY/MM/DD
    
    查询逻辑：(三代测序关键词 OR) AND (表观遗传学关键词 OR) AND 日期
    """
    # 构建三代测序部分（OR 逻辑）
    long_read_part = " OR ".join(f'"{kw}"[Title/Abstract]' for kw in LONG_READ_KEYWORDS)
    
    # 构建表观遗传学部分（OR 逻辑）
    epigenetic_part = " OR ".join(f'"{kw}"[Title/Abstract]' for kw in EPIGENETIC_KEYWORDS)
    
    # 组合查询：必须同时包含两类关键词
    return f"({long_read_part}) AND ({epigenetic_part}) AND {date_str}[Date - Publication]"


def should_exclude_article(article_data: dict) -> bool:
    """检查文章是否应该被排除（根据关键词过滤）"""
    # 收集所有文本内容用于匹配
    text_fields = [
        article_data.get("title", ""),
        article_data.get("abstract", ""),
        article_data.get("journal", "")
    ]
    full_text = " ".join(text_fields).lower()

    # 检查是否包含任何排除关键词
    for keyword in EXCLUDE_KEYWORDS:
        if keyword.lower() in full_text:
            return True
    return False


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
    
    # 检查返回数据是否有效
    if not raw or len(raw) < 10:
        log.warning(f"API返回数据异常: {raw[:200] if raw else '(空)'}")
        return []
    
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        log.error(f"JSON解析失败: {e}")
        log.error(f"原始数据: {raw[:500]}")
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

        # 过滤掉不需要的文献（植物、土壤、工厂、污水等）
        filtered_details = []
        for rec in details:
            if should_exclude_article(rec):
                log.info(f"  [过滤] PMID {rec.get('pmid')} | {rec.get('title', '')[:50]}...")
            else:
                filtered_details.append(rec)
                existing.add(str(rec["pmid"]))

        log.info(f"  过滤后保留 {len(filtered_details)} 篇（排除 {len(details) - len(filtered_details)} 篇）")

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
    parser = argparse.ArgumentParser(description="PubMed 三代测序+表观遗传学文献每日抓取")
    parser.add_argument("--date",      default=None, help="目标日期 YYYY-MM-DD（默认今天）")
    parser.add_argument("--days-back", type=int, default=1, help="往前搜索天数（默认1）")
    args = parser.parse_args()
    run(target_date=args.date, days_back=args.days_back)
