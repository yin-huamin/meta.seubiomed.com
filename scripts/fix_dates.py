#!/usr/bin/env python3
"""
修复 pub_date：对 YYYY-MM 格式的文章，从 NCBI 拉取 PubMedPubDate（epub 日期）补全。
"""

import json, os, sys, time, urllib.request, urllib.error
from pathlib import Path
import xml.etree.ElementTree as ET

BASE_DIR = Path(__file__).resolve().parent.parent  # 项目根目录
DATA_DIR = BASE_DIR / "data"
DAILY_DIR = DATA_DIR / "daily"
WEB_DIR = BASE_DIR / "web"

# 加载 config.env 中的 NCBI 配置
dotenv_path = BASE_DIR / "config.env"
if dotenv_path.exists():
    with open(dotenv_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")
NCBI_EMAIL = os.environ.get("NCBI_EMAIL", "yinhm17@126.com")


MONTH_TO_NUM = {
    "jan": "01", "january": "01",
    "feb": "02", "february": "02",
    "mar": "03", "march": "03",
    "apr": "04", "april": "04",
    "may": "05",
    "jun": "06", "june": "06",
    "jul": "07", "july": "07",
    "aug": "08", "august": "08",
    "sep": "09", "september": "09",
    "oct": "10", "october": "10",
    "nov": "11", "november": "11",
    "dec": "12", "december": "12",
}

def month_to_num(m: str) -> str:
    if m.isdigit():
        return m.zfill(2)
    return MONTH_TO_NUM.get(m.strip().lower(), "")

def fetch_pubmed_dates(pmids: list) -> dict:
    """批量从 NCBI 获取文章的 PubMedPubDate，返回 {pmid: YYYY-MM-DD}"""
    result = {}
    # 分批请求（每批 50 个 PMID）
    batch_size = 50
    for i in range(0, len(pmids), batch_size):
        batch = pmids[i:i+batch_size]
        pmid_str = ",".join(batch)
        url = (
            f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
            f"?db=pubmed&id={pmid_str}&retmode=xml"
        )
        if NCBI_API_KEY:
            url += f"&api_key={NCBI_API_KEY}"
        if NCBI_EMAIL:
            url += f"&email={NCBI_EMAIL}"

        print(f"  请求 {i+1}-{i+len(batch)} / {len(pmids)}...")
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "MetaSeuBiomed/1.0")
            with urllib.request.urlopen(req, timeout=30) as resp:
                xml_data = resp.read().decode("utf-8")
        except Exception as e:
            print(f"  ❌ 请求失败: {e}")
            time.sleep(3)
            continue

        root = ET.fromstring(xml_data)
        for art in root.findall(".//PubmedArticle"):
            pmid_node = art.find(".//PMID")
            pmid = pmid_node.text.strip() if pmid_node is not None else ""
            if not pmid:
                continue

            # 优先使用 PubMedPubDate (PubStatus="pubmed")
            best_date = ""
            for pmd in art.findall(".//PubMedPubDate"):
                pub_status = pmd.get("PubStatus", "")
                if pub_status in ("pubmed", "entrez"):
                    y = pmd.findtext("Year", "")
                    m = pmd.findtext("Month", "")
                    d = pmd.findtext("Day", "")
                    if y and m and d:
                        candidate = f"{y}-{month_to_num(m)}-{d.zfill(2)}"
                        if not best_date or pub_status == "pubmed":
                            best_date = candidate

            if best_date:
                result[pmid] = best_date

        time.sleep(0.5)  # NCBI 限流

    return result


def main():
    # 1. 从 web/data.json 找所有 YYYY-MM 的文章
    web_data_path = WEB_DIR / "data.json"
    if not web_data_path.exists():
        print("web/data.json 不存在")
        sys.exit(1)

    with open(web_data_path, encoding="utf-8") as f:
        all_records = json.load(f)

    # pmid -> record index
    bad_pmids = []
    for rec in all_records:
        d = rec.get("pub_date", "") or ""
        if len(d) == 7 and d.count("-") == 1:
            bad_pmids.append(str(rec.get("pmid", "")))

    print(f"待修复 {len(bad_pmids)} 篇")

    if not bad_pmids:
        print("没有需要修复的文章")
        return

    # 2. 从 NCBI 获取 epub 日期
    print("从 NCBI 获取 PubMedPubDate...")
    epub_dates = fetch_pubmed_dates(bad_pmids)
    print(f"获取到 {len(epub_dates)} 篇的 epub 日期")

    if not epub_dates:
        print("未获取到任何 epub 日期，退出")
        return

    # 3. 更新 web/data.json
    fixed = 0
    for rec in all_records:
        pmid = str(rec.get("pmid", ""))
        if pmid in epub_dates:
            old = rec["pub_date"]
            rec["pub_date"] = epub_dates[pmid]
            fixed += 1

    with open(web_data_path, "w", encoding="utf-8") as f:
        json.dump(all_records, f, ensure_ascii=False, separators=(",", ":"))
    print(f"已更新 web/data.json: {fixed} 篇")

    # 4. 更新 web/data/YYYY.json 分年文件
    from collections import defaultdict
    by_year = defaultdict(list)
    for rec in all_records:
        y = (rec.get("pub_date") or "")[:4]
        if y and len(y) == 4:
            by_year[y].append(rec)

    data_dir = WEB_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    index = []
    for y in sorted(by_year):
        out = data_dir / f"{y}.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(by_year[y], f, ensure_ascii=False, separators=(",", ":"))
        index.append({"year": y, "count": len(by_year[y]), "file": f"data/{y}.json"})

    idx_path = data_dir / "index.json"
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f"已更新 {len(by_year)} 个年份分文件")

    # 5. 更新 daily JSON
    daily_fixed = 0
    for f in sorted(DAILY_DIR.glob("*.json")):
        changed = False
        with open(f, encoding="utf-8") as fh:
            records = json.load(fh)
        for rec in records:
            pmid = str(rec.get("pmid", ""))
            if pmid in epub_dates:
                rec["pub_date"] = epub_dates[pmid]
                changed = True
                daily_fixed += 1
        if changed:
            with open(f, "w", encoding="utf-8") as fh:
                json.dump(records, fh, ensure_ascii=False, indent=2)

    print(f"已更新 daily JSON: {daily_fixed} 篇")
    print(f"✅ 完成！共修复 {fixed} 篇")


if __name__ == "__main__":
    main()
