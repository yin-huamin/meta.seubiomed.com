# 宏基因组文献追踪系统 - 一次性初始化脚本
# 运行本脚本拉取近7天论文并构建前端数据
# 用法: python scripts/init_history.py [--days N]

import sys
import argparse
import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))

import fetch_pubmed
import summarize_papers
import build_data
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

parser = argparse.ArgumentParser(description="初始化：拉取近N天文献")
parser.add_argument("--days", type=int, default=7, help="拉取最近N天（默认7）")
parser.add_argument("--skip-ai", action="store_true", help="跳过AI摘要（节省API费用）")
args = parser.parse_args()

log.info(f"开始拉取最近 {args.days} 天的文献...")
today = datetime.date.today()

for i in range(args.days):
    day = today - datetime.timedelta(days=i)
    date_str = day.strftime("%Y-%m-%d")
    log.info(f"=== {date_str} ===")
    fetch_pubmed.run(target_date=date_str, days_back=1)

if not args.skip_ai:
    log.info("开始 AI 摘要（所有文件）...")
    summarize_papers.run(all_files=True)
else:
    log.info("已跳过 AI 摘要")

log.info("构建前端数据...")
stats = build_data.run()
log.info(f"完成！共 {stats['total']} 篇文献")
