#!/usr/bin/env python3
"""
根据排除关键词清理已有文献数据（daily 文件）
使用与 fetch_pubmed.py 一致的过滤逻辑（EXCLUDE_KEYWORDS + SAFE_WORDS）
"""

import os
import json
import argparse
import logging
from pathlib import Path
from datetime import datetime

# ──────────────────────────── 配置区 ──────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DAILY_DIR = DATA_DIR / "daily"
WEB_DIR = BASE_DIR / "web"

# 排除关键词（与 fetch_pubmed.py 完全一致）
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
    "瘤胃", "反刍", "奶牛", "肉牛", "小牛", "羔羊", "山羊", "绵羊", "育肥猪", "仔猪", "牧场",
    "蛋鸡", "肉鸡", "家禽", "禽类", "鸡舍", "鸭肉", "鹅肉", "孵化",
    "蜜蜂", "蜂群", "授粉", "蜂箱", "蜂巢", "养蜂",
    "蚊子", "蜱虫", "白蛉", "螨虫", "昆虫媒介",
    "奶酪", "酸奶", "发酵食品", "咖啡豆", "可可豆", "面包", "乳制品", "泡菜", "酱油", "味噌",
    "植物", "土壤", "根系", "根际", "叶子", "叶片", "作物", "稻田", "农业", "菜地",
    "污水处理", "工业废水", "生物反应器", "甲烷", "硫磺", "污泥",
    "生态系统", "生物多样性", "沿海", "沉积物", "水库", "湿地", "红树林", "珊瑚礁", "藻类", "浮游植物", "海草", "海带"
]

# 安全词列表（与 fetch_pubmed.py 完全一致）
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

# 含 food 字样的期刊一律排除
EXCLUDE_JOURNAL_KEYWORDS = ["food"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def should_exclude_by_content(paper: dict) -> tuple[bool, str]:
    """
    检查论文内容是否应该被排除（关键词过滤）
    返回: (是否排除, 匹配的关键词)
    """
    text_fields = [
        paper.get("title", ""),
        paper.get("abstract", ""),
    ]
    full_text = " ".join(text_fields).lower()

    # 先检查安全词 → 有安全词则不排除
    has_safe = any(safe.lower() in full_text for safe in SAFE_WORDS)
    if has_safe:
        return False, ""

    # 检查是否包含任何排除关键词
    for keyword in EXCLUDE_KEYWORDS:
        if keyword.lower() in full_text:
            return True, f"内容含排除词: {keyword}"

    return False, ""


def should_exclude_by_journal(paper: dict) -> tuple[bool, str]:
    """
    检查文章期刊是否应该被排除：
    1. 期刊名含 food 字样 → 排除
    2. 期刊不在白名单 → 排除（非Q1/Q2高质量期刊）
    返回 (bool, reason)
    """
    journal = paper.get("journal", "").lower().strip()

    # 1. 排除含 food 的期刊
    for excl_kw in EXCLUDE_JOURNAL_KEYWORDS:
        if excl_kw in journal:
            return True, f"期刊含排除词: {excl_kw} ({paper.get('journal')})"

    # 2. 不在白名单中 → 排除
    # 使用模糊匹配：白名单中任意一项是期刊名的子串，或期刊名是白名单项的子串
    for wl_journal in JOURNAL_WHITELIST:
        if wl_journal in journal or journal in wl_journal:
            return False, ""

    return True, f"期刊不在Q1/Q2白名单: {paper.get('journal')}"


def filter_daily_file(file_path: Path, dry_run: bool = True, filter_journal: bool = True) -> tuple[int, int, list]:
    """
    过滤单个 daily 文件
    返回: (原始数量, 过滤后数量, 被排除的论文列表)
    """
    if not file_path.exists():
        return 0, 0, []

    with open(file_path, "r", encoding="utf-8") as f:
        papers = json.load(f)

    original_count = len(papers)
    excluded_papers = []
    
    # 步骤1: 内容过滤
    after_content_filter = []
    for paper in papers:
        exclude, reason = should_exclude_by_content(paper)
        if exclude:
            excluded_papers.append({
                "pmid": paper.get("pmid"),
                "title": paper.get("title", "")[:80],
                "reason": reason,
                "journal": paper.get("journal", "")
            })
        else:
            after_content_filter.append(paper)
    
    # 步骤2: 期刊过滤（可选）
    filtered_papers = []
    if filter_journal:
        for paper in after_content_filter:
            exclude, reason = should_exclude_by_journal(paper)
            if exclude:
                excluded_papers.append({
                    "pmid": paper.get("pmid"),
                    "title": paper.get("title", "")[:80],
                    "reason": reason,
                    "journal": paper.get("journal", "")
                })
            else:
                filtered_papers.append(paper)
    else:
        filtered_papers = after_content_filter

    # 如果不是 dry_run，则写入文件
    if not dry_run and len(filtered_papers) < original_count:
        # 备份原文件
        backup_path = file_path.with_suffix(".json.prefilter_bak")
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(papers, f, ensure_ascii=False, indent=2)
        log.info(f"  备份原文件到: {backup_path}")

        # 写入过滤后的数据
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(filtered_papers, f, ensure_ascii=False, indent=2)
        log.info(f"  已更新: {file_path.name}")

    return original_count, len(filtered_papers), excluded_papers


def main():
    parser = argparse.ArgumentParser(description="根据排除关键词清理已有文献数据")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际修改文件")
    parser.add_argument("--file", type=str, help="指定单个文件处理（如 2026-03-30.json）")
    parser.add_argument("--all", action="store_true", help="处理所有 daily 文件（跳过 .bak/.backup）")
    parser.add_argument("--rebuild", action="store_true", help="过滤后重新构建 data.json")
    parser.add_argument("--no-journal-filter", action="store_true", help="跳过期刊白名单过滤（仅内容过滤）")
    args = parser.parse_args()

    if args.dry_run:
        log.info("🔍 预览模式（不会修改文件）")
    else:
        log.info("⚠️  实际执行模式（将修改文件）")
    
    filter_journal = not args.no_journal_filter
    if filter_journal:
        log.info(f"📚 期刊白名单过滤: 启用（共 {len(JOURNAL_WHITELIST)} 个白名单项）")
    else:
        log.info("📚 期刊白名单过滤: 已跳过")

    # 确定要处理的文件（排除 .bak 和 .backup）
    files_to_process = []

    if args.file:
        file_path = DAILY_DIR / args.file
        if file_path.exists():
            files_to_process.append(file_path)
        else:
            log.error(f"文件不存在: {file_path}")
            return
    elif args.all:
        for f in sorted(DAILY_DIR.glob("*.json")):
            if ".bak" in f.name or ".backup" in f.name:
                continue
            files_to_process.append(f)
    else:
        log.error("请指定 --file <文件名> 或 --all")
        return

    # 处理每个文件
    total_original = 0
    total_filtered = 0
    all_excluded = []

    for file_path in files_to_process:
        original, filtered, excluded = filter_daily_file(file_path, dry_run=args.dry_run, filter_journal=filter_journal)

        if original == 0:
            continue

        total_original += original
        total_filtered += filtered

        if excluded:
            log.info(f"{file_path.name}: {original} → {filtered}（排除 {len(excluded)} 篇）")
            for paper in excluded:
                log.info(f"  [{paper['reason']}] PMID {paper['pmid']} | {paper['title']}")
        else:
            log.info(f"{file_path.name}: {original} 篇，无需排除")

        all_excluded.extend(excluded)

    # 汇总统计
    log.info(f"\n{'='*60}")
    log.info("汇总统计")
    log.info(f"{'='*60}")
    log.info(f"处理文件数: {len(files_to_process)}")
    log.info(f"原始论文数: {total_original}")
    log.info(f"过滤后论文数: {total_filtered}")
    log.info(f"排除论文数: {total_original - total_filtered}")

    if total_original > 0:
        exclude_rate = (total_original - total_filtered) / total_original * 100
        log.info(f"排除比例: {exclude_rate:.1f}%")

    # 如果需要重新构建 data.json
    if args.rebuild and not args.dry_run:
        log.info("\n重新构建 data.json...")
        build_script = BASE_DIR / "scripts" / "build_data.py"
        if build_script.exists():
            os.system(f'python "{build_script}"')
        else:
            log.warning("未找到 build_data.py，请手动运行")


if __name__ == "__main__":
    main()
