#!/usr/bin/env python3
"""
Meta-SeuBiomed 统一命令行工具

用法:
    python metaweb fetch   [选项]    # 抓取文献
    python metaweb summarize [选项]    # 生成AI摘要
    python metaweb build              # 整合数据
    python metaweb auto    [选项]    # 自动运行（抓取+摘要+整合）
    python metaweb daily             # 每日自动化运行
"""

import argparse
import logging
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "scripts"))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def cmd_fetch(args):
    """抓取文献命令"""
    import fetch_pubmed

    log.info("▶ 开始抓取文献...")
    fetch_pubmed.run(
        target_date=args.date,
        days_back=args.days_back,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    log.info("✓ 抓取完成")


def cmd_summarize(args):
    """生成AI摘要命令"""
    import summarize_papers

    log.info("▶ 开始生成AI摘要...")
    summarize_papers.run(
        target_date=args.date,
        all_files=args.all,
        force=args.force,
    )
    log.info("✓ 摘要生成完成")


def cmd_build(args):
    """整合数据命令"""
    import build_data

    log.info("▶ 开始整合数据...")
    stats = build_data.run()
    log.info(f"✓ 整合完成！共 {stats.get('total', '?')} 篇文献")
    return stats


def cmd_auto(args):
    """自动运行命令（抓取+摘要+整合）"""
    import fetch_pubmed
    import summarize_papers
    import build_data
    from datetime import datetime, timedelta

    log.info("▶ 开始自动运行流程...")

    # 确定日期范围
    if args.date:
        target_date = args.date
        days_back = args.days_back or 1
    elif args.days:
        target_date = datetime.today().strftime("%Y-%m-%d")
        days_back = args.days
    else:
        target_date = datetime.today().strftime("%Y-%m-%d")
        days_back = 1

    # 1. 抓取
    log.info("=" * 50)
    log.info("步骤 1/3: 抓取文献")
    log.info("=" * 50)
    fetch_pubmed.run(target_date=target_date, days_back=days_back)

    # 2. 生成摘要
    log.info("=" * 50)
    log.info("步骤 2/3: 生成AI摘要")
    log.info("=" * 50)
    summarize_papers.run(target_date=target_date, all_files=False, force=args.force)

    # 3. 整合
    log.info("=" * 50)
    log.info("步骤 3/3: 整合数据")
    log.info("=" * 50)
    stats = build_data.run()

    log.info("=" * 50)
    log.info(f"✓ 自动运行完成！共 {stats.get('total', '?')} 篇文献")
    log.info("=" * 50)


def cmd_daily(args):
    """每日自动化运行命令"""
    import daily_update

    log.info("▶ 开始每日更新...")
    daily_update.main()
    log.info("✓ 每日更新完成")


def main():
    parser = argparse.ArgumentParser(
        description="Meta-SeuBiomed 宏基因组文献追踪系统 - 统一命令行工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python metaweb fetch --date 2026-05-05       # 抓取指定日期
  python metaweb fetch --days 7                 # 抓取最近7天
  python metaweb summarize                      # 为所有论文生成摘要
  python metaweb build                          # 整合数据到 web/data.json
  python metaweb auto --days 7                 # 自动抓取最近7天并整合
  python metaweb daily                         # 每日自动化运行
"""
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # ── fetch 命令 ──
    parser_fetch = subparsers.add_parser("fetch", help="抓取PubMed文献")
    parser_fetch.add_argument("--date", default=None, help="目标日期 YYYY-MM-DD（默认今天）")
    parser_fetch.add_argument("--days-back", type=int, default=1, help="往前搜索天数（默认1）")
    parser_fetch.add_argument("--start-date", default=None, help="日期范围起始 YYYY-MM-DD")
    parser_fetch.add_argument("--end-date", default=None, help="日期范围结束 YYYY-MM-DD")
    parser_fetch.set_defaults(func=cmd_fetch)

    # ── summarize 命令 ──
    parser_summarize = subparsers.add_parser("summarize", help="生成AI摘要")
    parser_summarize.add_argument("--date", default=None, help="目标日期 YYYY-MM-DD")
    parser_summarize.add_argument("--all", action="store_true", help="处理所有 daily JSON 文件")
    parser_summarize.add_argument("--force", action="store_true", help="强制重新生成已有AI摘要")
    parser_summarize.set_defaults(func=cmd_summarize)

    # ── build 命令 ──
    parser_build = subparsers.add_parser("build", help="整合数据到 web/data.json")
    parser_build.set_defaults(func=cmd_build)

    # ── auto 命令 ──
    parser_auto = subparsers.add_parser("auto", help="自动运行（抓取+摘要+整合）")
    parser_auto.add_argument("--date", default=None, help="目标日期 YYYY-MM-DD")
    parser_auto.add_argument("--days", type=int, default=None, help="抓取最近N天")
    parser_auto.add_argument("--days-back", type=int, default=None, help="往前搜索天数（同 --days）")
    parser_auto.add_argument("--force", action="store_true", help="强制重新生成摘要")
    parser_auto.set_defaults(func=cmd_auto)

    # ── daily 命令 ──
    parser_daily = subparsers.add_parser("daily", help="每日自动化运行")
    parser_daily.set_defaults(func=cmd_daily)

    # 解析参数
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
