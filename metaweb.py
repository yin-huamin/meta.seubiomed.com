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
    from datetime import datetime

    # PMID 模式：最高优先级
    pmid_list = None
    if args.pmid:
        pmid_list = [p.strip() for p in args.pmid if p.strip()]

    # 优先级：pmid > start_date/end_date > date/days-back > days
    target_date = args.date
    days_back = args.days_back
    start_date = args.start_date
    end_date = args.end_date

    # --days 快捷方式：从今天往前N天
    if args.days and not start_date and not pmid_list:
        if not target_date:
            target_date = datetime.today().strftime("%Y-%m-%d")
        days_back = args.days

    log.info("▶ 开始抓取文献...")
    fetch_pubmed.run(
        target_date=target_date,
        days_back=days_back,
        start_date=start_date,
        end_date=end_date,
        pmids=pmid_list,
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
    from datetime import datetime

    log.info("▶ 开始自动运行流程...")

    # 确定 fetch 参数（与 cmd_fetch 保持一致的逻辑）
    pmid_list = None
    if args.pmid:
        pmid_list = [p.strip() for p in args.pmid if p.strip()]

    target_date = args.date
    days_back = args.days_back
    start_date = args.start_date
    end_date = args.end_date

    if args.days and not start_date and not pmid_list:
        if not target_date:
            target_date = datetime.today().strftime("%Y-%m-%d")
        days_back = args.days
    elif not pmid_list and not start_date:
        if not target_date:
            target_date = datetime.today().strftime("%Y-%m-%d")
        days_back = days_back or 1

    # 1. 抓取
    log.info("=" * 50)
    log.info("步骤 1/3: 抓取文献")
    log.info("=" * 50)
    fetch_pubmed.run(
        target_date=target_date,
        days_back=days_back,
        start_date=start_date,
        end_date=end_date,
        pmids=pmid_list,
    )

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


def cmd_set(args):
    """设置/查看搜索关键词"""
    config_path = BASE_DIR / "config.env"
    example_path = BASE_DIR / "config.env.example"

    # --check: 查看当前关键词
    if args.check:
        keywords = _read_config_value(config_path, "SEARCH_KEYWORDS")
        if keywords:
            kw_list = [kw.strip() for kw in keywords.split(",") if kw.strip()]
            print(f"当前搜索关键词（{len(kw_list)} 个）:")
            for i, kw in enumerate(kw_list, 1):
                print(f"  {i}. {kw}")
        else:
            print("未配置自定义关键词，使用默认值:")
            for i, kw in enumerate(["metagenome", "metagenomic", "microbiome"], 1):
                print(f"  {i}. {kw}")
            print("\n提示: 使用 python metaweb.py set --term 来自定义关键词")
        return

    # --term: 设置搜索关键词
    if args.term:
        terms = [t.strip() for t in args.term if t.strip()]
        if not terms:
            print("错误: 请提供至少一个搜索关键词")
            sys.exit(1)

        # 更新 config.env（如不存在则从 example 复制）
        if not config_path.exists() and example_path.exists():
            import shutil
            shutil.copy2(example_path, config_path)
            print(f"已从 config.env.example 创建 config.env")

        _set_config_value(config_path, "SEARCH_KEYWORDS", ", ".join(terms))
        print(f"搜索关键词已更新为（{len(terms)} 个）:")
        for i, t in enumerate(terms, 1):
            print(f"  {i}. {t}")
        return

    # 无参数: 显示帮助
    print("用法:")
    print("  python metaweb.py set --term keyword1 keyword2 ...   # 设置搜索关键词")
    print("  python metaweb.py set --check                       # 查看当前关键词")


def _read_config_value(config_path: Path, key: str) -> str:
    """从 config.env 读取指定配置值"""
    if not config_path.exists():
        return ""
    with open(config_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.strip() == key:
                    return v.strip()
    return ""


def _set_config_value(config_path: Path, key: str, value: str):
    """在 config.env 中设置指定配置值（不存在则追加）"""
    lines = []
    found = False

    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            lines = f.readlines()

    # 查找并替换已有的 key
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, _ = stripped.split("=", 1)
            if k.strip() == key:
                new_lines.append(f"{key}={value}\n")
                found = True
                continue
        new_lines.append(line)

    # 如果没找到，追加到文件末尾
    if not found:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines.append("\n")
        new_lines.append(f"{key}={value}\n")

    with open(config_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def main():
    parser = argparse.ArgumentParser(
        description="Meta-SeuBiomed 宏基因组文献追踪系统 - 统一命令行工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python metaweb set --term metagenome microbiome     # 设置搜索关键词
  python metaweb set --check                          # 查看当前关键词
  python metaweb fetch                                # 抓取今天到昨天（默认1天）
  python metaweb fetch --days 7                       # 抓取最近7天
  python metaweb fetch --pmid 38912345 38967890       # 按PMID号抓取
  python metaweb fetch --start-date 2026-04-01 --end-date 2026-04-30  # 日期范围
  python metaweb auto --days 7                        # 自动抓取最近7天并整合
  python metaweb auto --pmid 38912345                 # 按PMID自动流水线
  python metaweb summarize                            # 为所有论文生成摘要
  python metaweb build                                # 整合数据到 web/data.json
  python metaweb daily                                # 每日自动化运行
"""
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # ── fetch 命令 ──
    parser_fetch = subparsers.add_parser("fetch", help="抓取PubMed文献")
    parser_fetch.add_argument("--date", default=None, help="目标日期 YYYY-MM-DD（默认今天）")
    parser_fetch.add_argument("--days-back", type=int, default=1, help="往前搜索天数（默认1）")
    parser_fetch.add_argument("--days", type=int, default=None, help="快捷方式：从今天往前搜索N天（同 --days-back）")
    parser_fetch.add_argument("--start-date", default=None, help="日期范围起始 YYYY-MM-DD")
    parser_fetch.add_argument("--end-date", default=None, help="日期范围结束 YYYY-MM-DD（默认今天）")
    parser_fetch.add_argument("--pmid", nargs="+", default=None, metavar="PMID",
                              help="按 PMID 号直接抓取（可多个，空格分隔）")
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
    parser_auto.add_argument("--date", default=None, help="目标日期 YYYY-MM-DD（默认今天）")
    parser_auto.add_argument("--days", type=int, default=None, help="快捷方式：从今天往前搜索N天")
    parser_auto.add_argument("--days-back", type=int, default=None, help="往前搜索天数（同 --days）")
    parser_auto.add_argument("--start-date", default=None, help="日期范围起始 YYYY-MM-DD")
    parser_auto.add_argument("--end-date", default=None, help="日期范围结束 YYYY-MM-DD（默认今天）")
    parser_auto.add_argument("--pmid", nargs="+", default=None, metavar="PMID",
                             help="按 PMID 号直接抓取（可多个，空格分隔）")
    parser_auto.add_argument("--force", action="store_true", help="强制重新生成摘要")
    parser_auto.set_defaults(func=cmd_auto)

    # ── daily 命令 ──
    parser_daily = subparsers.add_parser("daily", help="每日自动化运行")
    parser_daily.set_defaults(func=cmd_daily)

    # ── set 命令 ──
    parser_set = subparsers.add_parser("set", help="设置/查看搜索关键词")
    parser_set.add_argument("--term", nargs="+", default=None, metavar="KEYWORD",
                            help="设置搜索关键词（可多个，空格分隔）")
    parser_set.add_argument("--check", action="store_true", help="查看当前搜索关键词")
    parser_set.set_defaults(func=cmd_set)

    # 解析参数
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
