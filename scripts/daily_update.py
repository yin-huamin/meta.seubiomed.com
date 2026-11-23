#!/usr/bin/env python3
"""每日自动运行主入口

流程：
1. PubMed 补抓最近 7 天缺失日期
2. 期刊（Europe PMC/OpenAlex）与预印本（bioRxiv/medRxiv）抓取
3. 主题范围分类 → 排除项从 daily 移除
4. AI 摘要（仅保留记录）
5. 构建 web 数据 + 排除项审计
"""

import sys
import logging
import datetime
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))

import common
import fetch_pubmed
import summarize_papers
import build_data
import classify_scope
import fetch_journals
import fetch_preprints
import scope_purge

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

common.load_env()


def _env_bool(name: str, default: bool = True) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def check_data_exists(date_str: str) -> bool:
    """检查指定日期的数据文件是否存在且包含论文（有意清空的日期除外）。"""
    purge_state = common.load_purge_state()
    if date_str in (purge_state.get("purged_dates") or []):
        return True
    data_file = BASE_DIR / "data" / "daily" / f"{date_str}.json"
    if not data_file.exists():
        return False
    try:
        with open(data_file, encoding="utf-8") as f:
            data = json.load(f)
        return len(data) > 0
    except Exception:
        return False


def _run_scope(date_str: str):
    if not _env_bool("SCOPE_ENFORCE", True):
        return
    try:
        classify_scope.run(
            target_date=date_str, source="daily",
            workers=_env_int("SCOPE_WORKERS", 4),
            batch_size=_env_int("SCOPE_BATCH_SIZE", 10),
            min_conf=float(os.environ.get("SCOPE_MIN_CONFIDENCE", "0.7")),
            apply_daily=True,
        )
    except Exception as exc:
        log.error(f"主题分类失败 {date_str}: {exc}")
        if os.environ.get("SCOPE_FAIL_MODE", "fallback").strip().lower() == "abort":
            raise


def _run_summarize(date_str: str):
    try:
        summarize_papers.run(target_date=date_str)
    except Exception as exc:
        log.error(f"AI 摘要失败 {date_str}: {exc}")


def _run_channels(today: str):
    """期刊/预印本抓取每天都要跑，不能只在 PubMed 缺日时执行。"""
    if _env_bool("ENABLE_JOURNAL_FETCH", True):
        try:
            fetch_journals.run(days=_env_int("JOURNAL_FETCH_DAYS", 3))
        except Exception as exc:
            log.error(f"期刊抓取失败: {exc}")
    if _env_bool("ENABLE_PREPRINT_FETCH", True):
        try:
            fetch_preprints.run(days=_env_int("PREPRINT_FETCH_DAYS", 3))
        except Exception as exc:
            log.error(f"预印本抓取失败: {exc}")


def main():
    today = datetime.date.today().strftime("%Y-%m-%d")
    log.info(f"===== 开始每日更新 {today} =====")

    base_dt = datetime.date.today()
    dates_to_check = [
        (base_dt - datetime.timedelta(days=d)).strftime("%Y-%m-%d")
        for d in range(7)
    ]
    missing_dates = [d for d in dates_to_check if not check_data_exists(d)]
    if missing_dates:
        log.info(f"需要补全 PubMed 数据: {missing_dates}")
    else:
        log.info("✅ 今天及前7天 PubMed 数据完整")

    touched = set()
    for date_str in reversed(missing_dates):
        log.info(f"\n{'='*50}\n抓取 PubMed {date_str}\n{'='*50}")
        try:
            fetch_pubmed.run(target_date=date_str, days_back=1)
            touched.add(date_str)
        except Exception as exc:
            log.error(f"PubMed 抓取失败 {date_str}: {exc}")

    log.info(f"\n{'='*50}\n期刊与预印本抓取\n{'='*50}")
    _run_channels(today)
    touched.add(today)

    for date_str in sorted(touched):
        daily_file = common.DAILY_DIR / f"{date_str}.json"
        if not daily_file.exists():
            continue
        log.info(f"\n{'='*50}\n处理 {date_str}：主题分类 + AI 摘要\n{'='*50}")
        _run_scope(date_str)
        _run_summarize(date_str)

    log.info("\nStep: 整合数据")
    stats = build_data.run()

    try:
        if not scope_purge.verify():
            log.error("排除项残留审计失败，请检查 web/data 与 daily")
    except Exception as exc:
        log.warning(f"审计执行失败: {exc}")

    log.info(f"\n{'='*50}")
    log.info(f"===== 完成！共 {stats['total']} 篇文献 =====")
    if missing_dates:
        log.info(f"已补全 {len(missing_dates)} 天的 PubMed 数据")
    log.info(f"{'='*50}")


if __name__ == "__main__":
    main()
