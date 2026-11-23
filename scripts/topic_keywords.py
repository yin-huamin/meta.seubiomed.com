#!/usr/bin/env python3
"""期刊/预印本采集的主题关键词（宏基因组、耐药、基因组拼装）。"""

import re

TOPIC_PATTERNS = [
    r"metagenom\w*", r"metatranscriptom\w*", r"microbiom\w*", r"microbiota",
    r"microbial community", r"microbial communities",
    r"resistome", r"resistomes", r"antimicrobial resistance",
    r"antibiotic resistance", r"drug resistance",
    r"antibiotic resistance genes?", r"args?\b", r"amr\b",
    r"genome assembly", r"genome assembler", r"assembly graph",
    r"metagenome-assembled", r"metagenome assembled", r"mags?\b",
    r"binning", r"long-read assembly", r"hybrid assembly",
    r"strain-resolved", r"strain-level", r"plasmidome", r"mobilome",
    r"integron", r"genomic epidemiology", r"whole-genome sequencing",
    r"shotgun metagenomic", r"16s rrna", r"amplicon sequencing",
    r"metagenomic next-generation", r"mngs",
]

_COMPILED = []
for _pattern in TOPIC_PATTERNS:
    _body = re.sub(r"\s+", r"\\s+", _pattern)
    _COMPILED.append((
        re.compile(rf"(?<![a-z0-9]){_body}(?![a-z0-9])", re.I),
        _pattern,
    ))


def record_text(rec: dict) -> str:
    parts = [str(rec.get("title") or ""), str(rec.get("abstract") or "")]
    kw = rec.get("keywords")
    if isinstance(kw, list):
        parts.extend(str(x) for x in kw)
    elif kw:
        parts.append(str(kw))
    return " ".join(parts)


def matches(text: str) -> tuple:
    hits = {label for regex, label in _COMPILED if regex.search(text or "")}
    return bool(hits), sorted(hits)
