#!/usr/bin/env python3
"""主题范围规则层：带词边界的预筛与 LLM 结果纠偏。

词表刻意回避过泛词（treatment/therapy/trial/immune/inflammation 等），
并用词边界解决 plant→implant、root→root canal、fish→Fisher 等误伤。
"""

import re

# ── 人类医学信号 ──
HUMAN_ANCHORS = [
    r"human", r"humans", r"patient", r"patients", r"clinical", r"clinician",
    r"hospital", r"cohort", r"participant", r"participants", r"volunteer",
    r"infant", r"infants", r"neonat\w*", r"preterm", r"newborn", r"child",
    r"children", r"adolescen\w*", r"adult", r"adults", r"elderly", r"pregnan\w*",
    r"mother", r"mothers", r"maternal",
    # 疾病与临床状态
    r"ibd", r"crohn", r"ulcerative colitis", r"colitis", r"colorectal",
    r"cancer", r"carcinoma", r"tumou?r", r"diabetes", r"diabetic", r"obesity",
    r"asthma", r"copd", r"alzheimer", r"parkinson", r"autism", r"sepsis",
    r"septic", r"hiv", r"hepatitis", r"cirrhosis", r"nafld", r"masld",
    r"chronic kidney", r"kidney transplant", r"psoriasis", r"eczema",
    r"atopic dermatitis", r"immunotherapy", r"chemotherapy", r"covid",
    r"sars-cov-2", r"influenza", r"tuberculosis", r"mrsa", r"bacteremia",
    r"bloodstream infection", r"urinary tract", r"intensive care", r"icu",
    r"nosocomial", r"hospital-acquired", r"clinical isolate", r"clinical strain",
    r"fecal microbiota transplant", r"faecal microbiota transplant", r"fmt",
    r"clostridioides difficile", r"c\. difficile",
    # 人体样本 / 人体微生态
    r"gut microb\w*", r"fecal", r"faecal", r"stool", r"oral microb\w*",
    r"skin microb\w*", r"vaginal microb\w*", r"lung microb\w*",
    r"respiratory microb\w*", r"nasal microb\w*", r"breast milk",
    r"human milk", r"saliva", r"urine", r"blood", r"plasma", r"serum",
    r"biopsy", r"human tissue",
    # 疾病模型
    r"mouse", r"mice", r"murine", r"rat model", r"xenograft", r"humanized",
    r"gnotobiotic", r"patient-derived", r"organoid", r"zebrafish",
    r"drosophila", r"c\. elegans",
]

# ── 生物信息学方法信号 ──
# 强信号：出现在标题里才允许把 LLM 的 non_medical 改判为 method
METHOD_STRONG = [
    r"tool", r"toolkit", r"software", r"algorithm", r"algorithms", r"pipeline",
    r"workflow", r"framework", r"database", r"benchmark", r"benchmarking",
    r"assembler", r"genome assembly", r"assembly graph", r"long-read assembly",
    r"hybrid assembly", r"binning", r"web server", r"resource", r"platform",
    r"k-mer", r"graph-based", r"metagenome-assembled", r"strain-resolved",
    r"deep learning", r"machine learning", r"neural network", r"classifier",
]
# 弱信号：仅用于预筛，不单独触发改判
METHOD_WEAK = [
    r"method", r"methods", r"protocol", r"mags?\b", r"resistome", r"annotation",
    r"plasmid", r"mobilome", r"integron", r"antimicrobial resistance",
    r"antibiotic resistance", r"amr\b",
]
METHOD_ANCHORS = METHOD_STRONG + METHOD_WEAK

# ── 明确非医学主题（标题命中即强信号）──
NONMED_STRONG = [
    # 植物 / 土壤 / 农业
    r"plant", r"plants", r"plant growth", r"plant pathogen", r"crop", r"crops",
    r"crop yield", r"rhizosphere", r"phyllosphere", r"soil", r"soils",
    r"soil-borne", r"soil microb\w*", r"agricultur\w*", r"farmland", r"paddy",
    r"rice", r"wheat", r"maize", r"corn", r"soybean", r"barley", r"sorghum",
    r"cotton", r"tobacco", r"sugarcane", r"forest", r"tree", r"trees",
    r"leaf", r"leaves", r"root-associated", r"root microbiome", r"root rot",
    r"seed", r"seeds", r"germination", r"greenhouse", r"horticultur\w*",
    r"fertilizer", r"compost", r"manure",
    # 畜牧 / 兽医 / 水产 / 昆虫
    r"livestock", r"cattle", r"dairy cow", r"cow", r"cows", r"calf", r"calves",
    r"pig", r"pigs", r"swine", r"porcine", r"poultry", r"chicken", r"broiler",
    r"laying hen", r"sheep", r"goat", r"rumen", r"ruminal", r"ruminant",
    r"feedlot", r"animal feed", r"growth performance", r"milk yield",
    r"egg production", r"aquaculture", r"fish farm", r"shrimp", r"oyster",
    r"honeybee", r"honey bee", r"bee", r"bees", r"mosquito", r"tick",
    r"insect", r"arthropod", r"nematode",
    # 食品发酵
    r"fermented food", r"food fermentation", r"cheese", r"yogurt", r"yoghurt",
    r"kefir", r"kimchi", r"sauerkraut", r"soy sauce", r"vinegar", r"beer",
    r"wine", r"bread", r"sourdough", r"dairy product", r"meat", r"sausage",
    r"food microbiota",
    # 环境
    r"wastewater", r"sewage", r"sludge", r"activated sludge", r"bioreactor",
    r"sediment", r"marine", r"ocean", r"seawater", r"freshwater", r"lake",
    r"river", r"wetland", r"mangrove", r"coral", r"permafrost", r"glacier",
    r"hot spring", r"groundwater", r"drinking water", r"environmental sample",
    r"environmental microb\w*", r"air microb\w*", r"built environment",
    r"indoor", r"bioremediation", r"heavy metal", r"microplastic",
    r"ecosystem", r"biodiversity", r"biogeochem\w*", r"nitrogen cycle",
    r"carbon cycle", r"phytoplankton", r"algae", r"cyanobacteria",
]

# ── 较弱的环境/农业信号（需要 ≥2 个才作为规则排除依据）──
NONMED_WEAK = [
    r"environment", r"environmental", r"ecolog\w*", r"veterinar\w*",
    r"animal", r"animals", r"ferment\w*", r"food", r"aquatic", r"terrestrial",
]


def _compile(patterns):
    compiled = []
    for pat in patterns:
        body = re.sub(r"\s+", r"\\s+", pat)
        compiled.append((re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])", re.I), pat))
    return compiled


_HUMAN_RE        = _compile(HUMAN_ANCHORS)
_METHOD_RE       = _compile(METHOD_ANCHORS)
_METHOD_STRONG_RE = _compile(METHOD_STRONG)
_STRONG_RE       = _compile(NONMED_STRONG)
_WEAK_RE         = _compile(NONMED_WEAK)


def _hits(text, compiled):
    return {label for regex, label in compiled if regex.search(text)}


def _text(rec: dict, with_abstract=True) -> tuple:
    title = str(rec.get("title") or "")
    parts = [title]
    if with_abstract and rec.get("abstract"):
        parts.append(str(rec["abstract"]))
    else:
        parts.extend(str(rec.get(k) or "") for k in
                     ("summary_zh", "study_object", "disease", "sample_size"))
    return title, " ".join(parts)


def scan(rec: dict) -> dict:
    title, body = _text(rec)
    strong_body = _hits(body, _STRONG_RE)
    weak_body = _hits(body, _WEAK_RE)
    return {
        "human": _hits(body, _HUMAN_RE),
        "human_title": _hits(title, _HUMAN_RE),
        "method": _hits(body, _METHOD_RE),
        "method_title": _hits(title, _METHOD_STRONG_RE),
        "strong_title": _hits(title, _STRONG_RE),
        "strong_body": strong_body,
        "weak_body": weak_body,
    }


def prefilter(rec: dict) -> dict:
    """明显非医学的记录直接排除，其余交给 LLM。"""
    signals = scan(rec)
    human, method = signals["human"], signals["method"]
    strong_body = signals["strong_body"] | signals["weak_body"]

    if signals["strong_title"] and not human and not method:
        return {
            "drop": True,
            "category": "non_medical",
            "confidence": 0.9,
            "reason": "标题命中非医学主题: " + ", ".join(sorted(signals["strong_title"])[:4]),
            "signals": signals,
            "method": "rule",
        }
    if len(strong_body) >= 2 and not human and not method:
        return {
            "drop": True,
            "category": "non_medical",
            "confidence": 0.85,
            "reason": "多个非医学主题信号: " + ", ".join(sorted(strong_body)[:4]),
            "signals": signals,
            "method": "rule",
        }
    return {"drop": False, "signals": signals}


def postprocess(rec: dict, llm: dict, signals: dict = None) -> dict:
    """对 LLM 结果做规则纠偏，返回附带 flags 的结果。"""
    signals = signals or scan(rec)
    human, human_title = signals["human"], signals["human_title"]
    method, method_title = signals["method"], signals["method_title"]
    strong = signals["strong_body"] | signals["weak_body"]
    category = llm.get("category") or "non_medical"
    confidence = float(llm.get("confidence") or 0)
    reason = str(llm.get("reason") or "")
    flags = []

    if category == "non_medical":
        if human_title and not signals["strong_title"]:
            category = "medical"
            flags.append("human_anchor_override")
            reason += " | rule: human title anchor"
        elif method_title and len(strong) < 2:
            category = "bioinformatics_method"
            flags.append("method_anchor_override")
            reason += " | rule: method title anchor"
        elif method_title and signals["strong_title"]:
            flags.append("method_subject_conflict")
    elif category == "medical":
        if not human and len(strong) >= 2 and not method:
            flags.append("weak_medical")
        if signals["strong_title"] and not human_title:
            flags.append("human_subject_conflict")
    elif category == "bioinformatics_method":
        if not method_title:
            flags.append("weak_method")

    return {
        "category": category,
        "confidence": confidence,
        "reason": reason,
        "flags": flags,
        "decision": "keep" if category in ("medical", "bioinformatics_method") else "exclude",
        "signals": {k: sorted(v) if isinstance(v, set) else v
                    for k, v in signals.items()},
    }
