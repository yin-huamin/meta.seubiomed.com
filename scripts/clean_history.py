#!/usr/bin/env python3
"""
清理已有的历史数据，根据关键词过滤掉不需要的文献
"""

import json
import logging
from pathlib import Path

# 配置
BASE_DIR = Path(__file__).resolve().parent.parent
DAILY_DIR = BASE_DIR / "data" / "daily"

# 需要排除的关键词
EXCLUDE_KEYWORDS = [
    # 英文
    "plant", "plants", "rhizosphere", "soil", "leaf", "root", "crop",
    "factory", "industrial", "wastewater", "sewage", "effluent",
    # 中文
    "植物", "土壤", "根系", "根际", "叶子", "叶片", "作物",
    "工厂", "污水", "废水", "污泥"
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def should_exclude(article_data: dict) -> bool:
    """检查文章是否应该被排除"""
    text_fields = [
        article_data.get("title", ""),
        article_data.get("abstract", ""),
        article_data.get("journal", "")
    ]
    full_text = " ".join(text_fields).lower()

    for keyword in EXCLUDE_KEYWORDS:
        if keyword.lower() in full_text:
            return True
    return False


def clean_daily_file(file_path: Path):
    """清理单个每日文件"""
    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)

        original_count = len(data)
        filtered = [rec for rec in data if not should_exclude(rec)]
        removed = original_count - len(filtered)

        if removed > 0:
            # 备份原文件
            backup_path = file_path.with_suffix('.json.backup')
            with open(backup_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            log.info(f"  已备份原文件 → {backup_path.name}")

            # 保存过滤后的数据
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(filtered, f, ensure_ascii=False, indent=2)

            log.info(f"  {file_path.name}: 原有 {original_count} 篇，保留 {len(filtered)} 篇，删除 {removed} 篇")
            return removed
        else:
            log.info(f"  {file_path.name}: 无需过滤（{original_count} 篇）")
            return 0

    except Exception as e:
        log.error(f"  处理 {file_path.name} 失败: {e}")
        return 0


def main():
    """主流程"""
    if not DAILY_DIR.exists():
        log.error(f"目录不存在: {DAILY_DIR}")
        return

    log.info(f"开始清理历史数据...")
    log.info(f"排除关键词: {', '.join(EXCLUDE_KEYWORDS)}")
    log.info("")

    json_files = sorted(DAILY_DIR.glob("*.json"))
    if not json_files:
        log.warning("未找到任何 JSON 文件")
        return

    total_original = 0
    total_removed = 0

    for file_path in json_files:
        if file_path.name.endswith('.backup'):
            continue

        log.info(f"处理: {file_path.name}")
        total_original += 1

        # 读取文件统计原数量
        try:
            with open(file_path, encoding="utf-8") as f:
                original_count = len(json.load(f))
        except:
            original_count = 0

        removed = clean_daily_file(file_path)
        total_removed += removed

        log.info("")

    log.info("=" * 60)
    log.info(f"清理完成！")
    log.info(f"处理文件数: {total_original}")
    log.info(f"删除文献数: {total_removed}")
    log.info("=" * 60)
    log.info("")
    log.info("💡 提示: 所有原文件已备份为 *.json.backup")
    log.info("💡 如需恢复，删除 .json 文件，将 .backup 文件重命名回去")
    log.info("")
    log.info("下一步: 运行 python scripts/build_data.py 重新整合数据")


if __name__ == "__main__":
    main()
