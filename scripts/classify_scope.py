#!/usr/bin/env python3
"""文献主题范围分类：medical / bioinformatics_method / non_medical。

- 规则预筛明显非医学论文，其余交给 LLM 批量分类
- 断点续跑、并发、失败拆批、低置信度复核队列、人工 overrides
- 产出 data/excluded_pmids.json（物理清除的依据）
"""

import argparse
import json
import logging
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))

import common
import scope_rules

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

PROMPT_VERSION = "scope-v1"
VALID_CATEGORIES = {"medical", "bioinformatics_method", "non_medical"}

SYSTEM_PROMPT = """你是宏基因组文献库的主题审核员。判断每篇论文是否属于"人类医学相关"范围。

分类定义：
- medical：与人类健康、临床、人体微生态、人类疾病动物模型相关（患者/队列/医院/人体样本/疾病模型/临床耐药）。
- bioinformatics_method：主要贡献是宏基因组、微生物组、耐药或基因组拼装方向的工具、算法、软件、数据库、基准或分析流程；即使测试数据来自环境/植物也归此类。
- non_medical：植物、土壤、农业、环境、食品发酵、兽医、畜牧、水产、昆虫或纯生态研究，且既没有人类医学证据，也没有可复用的生物信息学方法贡献。

判定要点：
- 只依据输入，不推测。
- 把通用流程套用到某个生态问题的应用研究算 non_medical；只有提出新工具/算法/数据库/基准/软件才算 bioinformatics_method。
- 摘要/研究对象的语言可能是中文，可能缺失；以可用信息为准。
- 临床病原或人源耐药研究算 medical；污水/环境耐药监测算 non_medical，除非提出新检测方法。

只输出 JSON 数组，每个元素：
{"i": 输入序号, "category": "medical|bioinformatics_method|non_medical", "confidence": 0到1的小数, "reason": "简短中文理由"}
不要输出解释、markdown 或代码块。"""


# ──────────────────────────── LLM 调用 ────────────────────────────

def _llm_config():
    import summarize_papers as sp
    return {
        "url": sp.LLM_API_URL,
        "key": sp.LLM_API_KEY,
        "model": os.environ.get("SCOPE_LLM_MODEL") or sp.LLM_MODEL,
        "timeout": int(os.environ.get("SCOPE_LLM_TIMEOUT", sp.LLM_TIMEOUT)),
        "max_tokens": int(os.environ.get("SCOPE_LLM_MAX_TOKENS", "4096")),
    }


def _payload(rec: dict) -> dict:
    abstract = str(rec.get("abstract") or "")
    item = {
        "title": str(rec.get("title") or ""),
        "journal": str(rec.get("journal") or ""),
    }
    if abstract:
        item["abstract"] = abstract[:2500]
    else:
        item["summary"] = str(rec.get("summary_zh") or "")
        item["study_object"] = str(rec.get("study_object") or "")
        item["disease"] = str(rec.get("disease") or "")
        item["sample_size"] = str(rec.get("sample_size") or "")
    return item


def _extract_json_array(content: str):
    content = content.strip()
    if "```" in content:
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    start, end = content.find("["), content.rfind("]")
    if start != -1 and end > start:
        content = content[start:end + 1]
    return json.loads(content, strict=False)


def _call_batch(batch: list, cfg: dict) -> dict:
    """返回 {uid: {category, confidence, reason}}；失败抛异常。"""
    inputs = [{"i": i, **_payload(rec)} for i, (_, rec) in enumerate(batch)]
    payload = json.dumps({
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(inputs, ensure_ascii=False)},
        ],
        "temperature": 0.0,
        "max_tokens": cfg["max_tokens"],
    }).encode("utf-8")

    req = urllib.request.Request(
        cfg["url"], data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {cfg['key']}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
        body = json.loads(resp.read())
    message = body["choices"][0]["message"]
    content = (message.get("content") or "").strip()
    if not content:
        reasoning = message.get("reasoning_content") or ""
        raise ValueError(f"LLM 返回空内容（reasoning {len(reasoning)} 字符）")

    parsed = _extract_json_array(content)
    out = {}
    for item in parsed:
        try:
            idx = int(item.get("i"))
        except (TypeError, ValueError):
            continue
        if not (0 <= idx < len(batch)):
            continue
        category = str(item.get("category") or "").strip()
        if category not in VALID_CATEGORIES:
            continue
        confidence = item.get("confidence")
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.5
        out[batch[idx][0]] = {
            "category": category,
            "confidence": max(0.0, min(1.0, confidence)),
            "reason": str(item.get("reason") or "").strip(),
        }
    if not out:
        raise ValueError("LLM 返回的 JSON 数组无法解析")
    return out


def _call_batch_resilient(batch: list, cfg: dict, retries: int = 2) -> dict:
    """失败重试；仍失败则拆成更小批次，最终单条。"""
    last_err = None
    for attempt in range(retries):
        try:
            return _call_batch(batch, cfg)
        except Exception as exc:
            last_err = exc
            time.sleep(1.5 * (attempt + 1))
    if len(batch) > 1:
        mid = len(batch) // 2
        left = _call_batch_resilient(batch[:mid], cfg, retries=1)
        right = _call_batch_resilient(batch[mid:], cfg, retries=1)
        return {**left, **right}

    uid, rec = batch[0]
    log.error(f"分类失败 uid={uid}: {last_err}")
    return {uid: {
        "category": "medical",
        "confidence": 0.0,
        "reason": f"LLM 分类失败，默认保留: {last_err}",
        "llm_failed": True,
    }}


# ──────────────────────────── 记录收集 ────────────────────────────

def collect_records(target_date=None, source="all") -> list:
    merged = {}

    def add(rec):
        if not rec or not rec.get("title"):
            return
        uid = common.record_uid(rec)
        if not uid:
            return
        if uid in merged:
            common.merge_record(merged[uid], rec)
        else:
            merged[uid] = common.ensure_identity(dict(rec))

    if source in ("all", "web"):
        for rec in common.load_json(common.WEB_DIR / "data.json", []) or []:
            add(rec)
    if source in ("all", "daily"):
        pattern = f"{target_date}.json" if target_date else "*.json"
        for f in sorted(common.DAILY_DIR.glob(pattern)):
            for rec in common.load_json(f, []) or []:
                add(rec)
    return list(merged.values())


# ──────────────────────────── 状态 ────────────────────────────

def load_state() -> dict:
    data = common.load_json(common.SCOPE_STATE_FILE, {}) or {}
    data.setdefault("version", 1)
    data.setdefault("prompt_version", PROMPT_VERSION)
    data.setdefault("items", {})
    return data


def save_state(state: dict):
    state["updated"] = date.today().strftime("%Y-%m-%d")
    common.save_json(common.SCOPE_STATE_FILE, state)


def load_overrides() -> dict:
    return common.load_json(common.SCOPE_OVERRIDES_FILE, {}) or {}


def apply_overrides(results: dict, overrides: dict = None) -> dict:
    """把人工覆盖应用到已有分类结果（用于 --materialize-only）。"""
    overrides = overrides if overrides is not None else load_overrides()
    for uid, res in list(results.items()):
        ov = overrides.get(uid)
        if not ov:
            continue
        res = dict(res)
        res["category"] = ov.get("category") or res.get("category")
        res["decision"] = ov.get("decision") or (
            "keep" if res["category"] in ("medical", "bioinformatics_method") else "exclude")
        res["confidence"] = 1.0
        res["reason"] = ov.get("reason") or res.get("reason", "")
        res["method"] = "override"
        flags = list(res.get("flags") or [])
        if "override" not in flags:
            flags.append("override")
        res["flags"] = flags
        results[uid] = res
    return results


def _result_from_rule(pre: dict) -> dict:
    return {
        "category": pre["category"],
        "confidence": pre["confidence"],
        "reason": pre["reason"],
        "flags": [],
        "decision": "exclude",
        "method": "rule",
        "signals": {k: sorted(v) if isinstance(v, set) else v
                    for k, v in pre["signals"].items()},
    }


def _finalize_result(rec, llm: dict, overrides: dict, min_conf: float) -> dict:
    uid = common.record_uid(rec)
    signals = scope_rules.scan(rec)
    result = scope_rules.postprocess(rec, llm, signals)
    result["method"] = "llm"

    if uid in overrides:
        ov = overrides[uid]
        result["category"] = ov.get("category") or result["category"]
        result["decision"] = ov.get("decision") or (
            "keep" if result["category"] in ("medical", "bioinformatics_method") else "exclude")
        result["confidence"] = 1.0
        result["reason"] = ov.get("reason") or result["reason"]
        result["method"] = "override"
        result["flags"] = list(result.get("flags") or []) + ["override"]

    if llm.get("llm_failed"):
        result["category"] = "medical"
        result["decision"] = "keep"
        result["flags"] = list(result.get("flags") or []) + ["llm_failed"]

    if result["confidence"] < min_conf:
        result.setdefault("flags", []).append("low_confidence")

    result["title_hash"] = common.title_hash(rec.get("title"))
    result["classified_at"] = date.today().strftime("%Y-%m-%d")
    result["prompt_version"] = PROMPT_VERSION
    result["model"] = os.environ.get("SCOPE_LLM_MODEL") or ""
    return result


# ──────────────────────────── 分类主流程 ────────────────────────────

def classify_records(records: list, state: dict, workers: int = 4,
                     batch_size: int = 10, min_conf: float = 0.7,
                     force: bool = False) -> dict:
    cfg = _llm_config()
    overrides = load_overrides()
    items = state["items"]
    results = {}
    pending = []
    reused = rule_dropped = 0

    for rec in records:
        uid = common.record_uid(rec)
        th = common.title_hash(rec.get("title"))
        old = items.get(uid)
        if old and old.get("title_hash") == th and not force:
            results[uid] = old
            reused += 1
            continue

        pre = scope_rules.prefilter(rec)
        if pre["drop"]:
            result = _result_from_rule(pre)
            result.update({
                "title_hash": th,
                "classified_at": date.today().strftime("%Y-%m-%d"),
                "prompt_version": PROMPT_VERSION,
                "model": "rule",
            })
            results[uid] = result
            rule_dropped += 1
        else:
            pending.append((uid, rec, pre["signals"]))

    log.info(f"共 {len(records)} 篇：复用 {reused} 篇，规则排除 {rule_dropped} 篇，"
             f"待 LLM {len(pending)} 篇")

    if pending:
        batches = [pending[i:i + batch_size] for i in range(0, len(pending), batch_size)]
        log.info(f"LLM 批次数 {len(batches)}，并发 {workers}，模型 {cfg['model']}")

        def worker(batch):
            plain = [(uid, rec) for uid, rec, _ in batch]
            llm_map = _call_batch_resilient(plain, cfg)
            out = []
            for uid, rec, signals in batch:
                llm = llm_map.get(uid) or {
                    "category": "medical", "confidence": 0.0,
                    "reason": "LLM 未返回该条，默认保留", "llm_failed": True,
                }
                result = _finalize_result(rec, llm, overrides, min_conf)
                out.append((uid, result))
            return out

        done = 0
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = [pool.submit(worker, b) for b in batches]
            for fut in as_completed(futures):
                try:
                    for uid, result in fut.result():
                        results[uid] = result
                        items[uid] = result
                except Exception as exc:
                    log.error(f"批次处理失败: {exc}")
                done += 1
                if done % 10 == 0 or done == len(batches):
                    save_state(state)
                    log.info(f"进度 {done}/{len(batches)} 批，已完成 {len(results)} 篇")

    for uid, result in results.items():
        items[uid] = result
    save_state(state)
    return results


# ──────────────────────────── 产出排除清单 / 复核表 ────────────────────────────

def materialize(records: list, results: dict, min_conf: float = 0.7,
                merge: bool = False):
    """写排除清单与复核表；merge=True 时保留清单中本次未涉及的旧条目。"""
    by_uid = {common.record_uid(r): r for r in records}
    excluded_items = {}
    review_rows = []

    for uid, result in sorted(results.items()):
        rec = by_uid.get(uid) or {}
        if result.get("decision") == "exclude":
            excluded_items[uid] = {
                "uid": uid,
                "pmid": str(rec.get("pmid") or ""),
                "doi": common.normalize_doi(rec.get("doi")) or None,
                "title": rec.get("title") or "",
                "journal": rec.get("journal") or "",
                "pub_date": rec.get("pub_date") or "",
                "category": result.get("category"),
                "confidence": result.get("confidence"),
                "reason": result.get("reason") or "",
                "method": result.get("method") or "",
                "date": date.today().strftime("%Y-%m-%d"),
                "source": rec.get("source") or ("pubmed" if rec.get("pmid") else ""),
            }

        flags = result.get("flags") or []
        if flags or result.get("category") == "non_medical":
            review_rows.append([
                uid, str(rec.get("pmid") or ""), result.get("decision", ""),
                result.get("category", ""), f"{result.get('confidence', 0):.2f}",
                ",".join(flags), (rec.get("title") or "")[:140],
                (rec.get("journal") or "")[:40], (result.get("reason") or "")[:160],
            ])

    if merge:
        existing = common.load_excluded()["items"]
        existing.update(excluded_items)
        excluded_items = existing

    common.save_excluded(excluded_items)

    existing_uids = set()
    if merge and common.SCOPE_REVIEW_FILE.exists():
        with open(common.SCOPE_REVIEW_FILE, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    existing_uids.add(line.split("\t", 1)[0])
        review_rows = [row for row in review_rows if row[0] not in existing_uids]

    mode = "a" if merge else "w"
    with open(common.SCOPE_REVIEW_FILE, mode, encoding="utf-8", newline="") as fh:
        if not merge:
            fh.write("uid\tpmid\tdecision\tcategory\tconfidence\tflags\ttitle\tjournal\treason\n")
        for row in review_rows:
            fh.write("\t".join(str(x).replace("\t", " ") for x in row) + "\n")

    log.info(f"排除清单 {len(excluded_items)} 篇 -> {common.EXCLUDED_FILE}")
    log.info(f"复核队列 {len(review_rows)} 行 -> {common.SCOPE_REVIEW_FILE}")
    return common.load_excluded()


def apply_daily_removal(excluded: dict, target_date=None) -> int:
    """从 daily 文件移除排除项（用于每日流水线的新记录）。"""
    pattern = f"{target_date}.json" if target_date else "*.json"
    removed = 0
    for f in sorted(common.DAILY_DIR.glob(pattern)):
        data = common.load_json(f, []) or []
        kept = [r for r in data if not common.is_excluded(r, excluded)]
        if len(kept) != len(data):
            removed += len(data) - len(kept)
            common.save_json(f, kept)
    if removed:
        log.info(f"已从 daily 移除 {removed} 篇排除项")
    return removed


def print_summary(results: dict, limit: int = 20):
    from collections import Counter
    cats = Counter(r.get("category") for r in results.values())
    decisions = Counter(r.get("decision") for r in results.values())
    low = sum(1 for r in results.values() if "low_confidence" in (r.get("flags") or []))
    failed = sum(1 for r in results.values() if "llm_failed" in (r.get("flags") or []))
    overrides = sum(1 for r in results.values() if r.get("method") == "override")
    log.info(f"分类分布: {dict(cats)}")
    log.info(f"决策: {dict(decisions)} | 低置信度 {low} | LLM失败 {failed} | 人工覆盖 {overrides}")

    excluded = [(uid, r) for uid, r in results.items() if r.get("decision") == "exclude"]
    if excluded:
        log.info(f"排除样例（前 {min(limit, len(excluded))} 条）:")
        for uid, r in excluded[:limit]:
            log.info(f"  {uid} | {r.get('category')} {r.get('confidence', 0):.2f} | {r.get('reason','')[:100]}")


# ──────────────────────────── CLI ────────────────────────────

def run(target_date=None, all_records=False, source="all", workers=4,
        batch_size=10, limit=None, dry_run=False, force=False,
        materialize_only=False, min_conf=0.7, apply_daily=False):
    if materialize_only:
        state = load_state()
        records = collect_records(target_date, source)
        by_uid = {common.record_uid(r): r for r in records}
        results = {uid: r for uid, r in state["items"].items() if uid in by_uid}
        if not results:
            log.warning("没有可 materialize 的分类结果")
            return
        results = apply_overrides(results)
        print_summary(results)
        excluded = materialize(records, results, min_conf, merge=bool(target_date))
        if apply_daily:
            apply_daily_removal(excluded, target_date)
        return

    state = load_state()
    records = collect_records(target_date, source)
    if limit:
        records = records[:limit]
    log.info(f"待处理记录 {len(records)} 篇（source={source}, date={target_date or '全部'})")

    results = classify_records(records, state, workers=workers,
                               batch_size=batch_size, min_conf=min_conf,
                               force=force)
    results = apply_overrides(results)
    print_summary(results)

    if dry_run:
        log.info("dry-run：未写入排除清单/复核表（分类结果已缓存，可稍后 --materialize-only）")
        return

    excluded = materialize(records, results, min_conf, merge=bool(target_date))
    if apply_daily:
        apply_daily_removal(excluded, target_date)


def main():
    parser = argparse.ArgumentParser(description="文献主题范围分类")
    parser.add_argument("--date", default=None, help="只处理指定日期的 daily 文件")
    parser.add_argument("--all", action="store_true", help="处理全部记录（默认）")
    parser.add_argument("--source", choices=["all", "web", "daily"], default="all")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="分类但不写排除清单")
    parser.add_argument("--force", action="store_true", help="重新分类已完成记录")
    parser.add_argument("--materialize-only", action="store_true",
                        help="复用已缓存分类结果，只写排除清单/复核表")
    parser.add_argument("--min-confidence", type=float, default=0.7)
    parser.add_argument("--apply-daily", action="store_true",
                        help="把排除项从 daily 文件移除")
    args = parser.parse_args()

    run(target_date=args.date, all_records=True, source=args.source,
        workers=args.workers, batch_size=args.batch_size, limit=args.limit,
        dry_run=args.dry_run, force=args.force,
        materialize_only=args.materialize_only,
        min_conf=args.min_confidence, apply_daily=args.apply_daily)


if __name__ == "__main__":
    main()
