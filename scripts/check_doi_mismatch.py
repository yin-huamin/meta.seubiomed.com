#!/usr/bin/env python3
"""检查 DOI 和期刊是否匹配
通过 DOI 前缀判断期刊是否匹配
"""
import json
import re

# DOI 前缀和期刊的对应关系（常见出版社）
DOI_PREFIX_MAP = {
    '10.1016': ['cell', 'lancet', 'elsevier'],
    '10.1038': ['nature'],
    '10.1126': ['science'],
    '10.1093': ['oxford', 'nar', 'nar ', 'nucleic acids'],
    '10.1021': ['acs', 'american chemical'],
    '10.1002': ['wiley', 'john wiley'],
    '10.1080': ['taylor', 'francis'],
    '10.3389': ['frontiers'],
    '10.1186': ['biomed central', 'bmc'],
    '10.1371': ['plos'],
    '10.1128': ['asm', 'american society for microbiology', 'mra', 'mcb', 'iai'],
    '10.1111': ['wiley'],
    '10.1053': ['elsevier', 'academic press'],
    '10.1007': ['springer'],
    '10.1015': ['karger'],
    '10.3201': ['cdc', 'emerging infectious diseases'],
    '10.4161': ['taylor & francis', 'landes bioscience'],
    '10.2147': ['dove press'],
    '10.18632': ['aging us'],
    '10.7717': ['peerj'],
    '10.3390': ['mdpi'],
}

# 期刊关键词和 DOI 前缀的对应
JOURNAL_DOI_HINTS = {
    'nature': ['10.1038'],
    'science': ['10.1126'],
    'cell': ['10.1016/j.cell', '10.1016/s0092'],
    'lancet': ['10.1016/s0140', '10.1016/j.lan'],
    'nar': ['10.1093/nar'],
    'nucleic acids research': ['10.1093/nar'],
    'bioresource technology': ['10.1016/j.biortech'],
    'microbial pathogenesis': ['10.1016/j.micpath'],
    'faseb': ['10.1096/faseb', '10.1096/fj'],
    'metabolomics': ['10.1007/s11306', '10.1021/acs.analchem'],  # Springer 或 ACS
    'clinical infectious diseases': ['10.1093/cid'],
    'nature biotechnology': ['10.1038/s41587', '10.1038/nbt'],
    'future microbiology': ['10.2217/fmb', '10.2217/fmb.'],
}

def check_doi_journal_match(doi, journal):
    """检查 DOI 和期刊是否可能匹配"""
    if not doi or not journal:
        return True, "No DOI or journal"
    
    doi_lower = doi.lower()
    journal_lower = journal.lower()
    
    # 获取 DOI 前缀
    prefix_match = re.match(r'(10\.\d{4,})', doi_lower)
    if not prefix_match:
        return True, "Invalid DOI format"
    
    prefix = prefix_match.group(1)
    
    # 检查期刊关键词和 DOI 是否匹配
    for journal_key, doi_patterns in JOURNAL_DOI_HINTS.items():
        if journal_key in journal_lower:
            # 这个期刊应该有特定的 DOI 模式
            matched = any(pattern in doi_lower for pattern in doi_patterns)
            if not matched:
                return False, f"Journal '{journal}' expects DOI patterns like {doi_patterns}, got {doi[:30]}..."
            return True, "Matched"
    
    return True, "No specific rule"


with open('web/data.json', encoding='utf-8') as f:
    data = json.load(f)

print(f"Total papers: {len(data)}\n")

mismatches = []
for p in data:
    doi = p.get('doi', '')
    journal = p.get('journal', '')
    pmid = p.get('pmid', '')
    
    is_match, reason = check_doi_journal_match(doi, journal)
    if not is_match:
        mismatches.append({
            'pmid': pmid,
            'doi': doi,
            'journal': journal,
            'title': p.get('title', '')[:50],
            'reason': reason
        })

print(f"Found {len(mismatches)} potential mismatches out of {len(data)} papers")
print(f"Mismatch rate: {len(mismatches)/len(data)*100:.1f}%\n")

if mismatches:
    print("First 10 mismatches:")
    for m in mismatches[:10]:
        print(f"\nPMID: {m['pmid']}")
        print(f"  Journal: {m['journal']}")
        print(f"  DOI: {m['doi']}")
        print(f"  Title: {m['title']}...")
        print(f"  Issue: {m['reason']}")
