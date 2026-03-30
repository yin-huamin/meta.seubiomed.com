#!/usr/bin/env python3
"""
每日自动运行主入口
流程：fetch → summarize → build
支持断网恢复：自动检测当天及前7天是否已有结果
"""

import sys
import logging
import datetime
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))

import fetch_pubmed
import summarize_papers
import build_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def check_data_exists(date_str: str) -> bool:
    """检查指定日期的数据文件是否存在且包含论文"""
    data_file = BASE_DIR / "data" / "daily" / f"{date_str}.json"
    if not data_file.exists():
        return False
    try:
        with open(data_file, encoding="utf-8") as f:
            data = json.load(f)
        return len(data) > 0
    except:
        return False


if __name__ == "__main__":
    today = datetime.date.today().strftime("%Y-%m-%d")
    log.info(f"===== 开始每日更新 {today} =====")

    # 计算需要检查的日期范围（当天及前7天）
    base_dt = datetime.datetime.strptime(today, "%Y-%m-%d").date()
    dates_to_check = [
        (base_dt - datetime.timedelta(days=d)).strftime("%Y-%m-%d")
        for d in range(7)
    ]

    # 检查哪些日期缺少数据
    missing_dates = []
    for date_str in dates_to_check:
        if not check_data_exists(date_str):
            missing_dates.append(date_str)
            log.warning(f"检测到缺少数据: {date_str}")

    if not missing_dates:
        log.info("✅ 今天及前7天数据完整，无需重新抓取")
        # 仍然需要整合数据（确保网页更新）
        log.info("Step: 整合数据到网页")
        stats = build_data.run()
        log.info(f"===== 完成！共 {stats['total']} 篇文献 =====")
        sys.exit(0)

    log.info(f"需要补全数据: {missing_dates}")

    # 按日期顺序抓取缺失的数据
    for date_str in reversed(missing_dates):  # 从最早的日期开始
        log.info(f"\n{'='*50}")
        log.info(f"开始抓取 {date_str} 的论文")
        log.info(f"{'='*50}")

        # 1. 抓取指定日期的论文
        log.info("Step 1: 抓取 PubMed 新论文")
        fetch_pubmed.run(target_date=date_str, days_back=1)

        # 2. AI 摘要生成（仅处理该日期的文件）
        log.info("Step 2: AI 摘要生成")
        try:
            summarize_papers.run(target_date=date_str)
        except Exception as e:
            log.error(f"AI 摘要生成失败: {e}")
            log.warning("继续处理下一个日期...")

    # 3. 整合所有数据 → web/data.json
    log.info("\nStep 3: 整合数据")
    stats = build_data.run()

    log.info(f"\n{'='*50}")
    log.info(f"===== 完成！共 {stats['total']} 篇文献 =====")
    log.info(f"已补全 {len(missing_dates)} 天的数据")
    log.info(f"{'='*50}")
