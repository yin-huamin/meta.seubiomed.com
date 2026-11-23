#!/usr/bin/env python3
"""物理清除排除清单中的论文，并审计 web / 分片 / daily 是否仍有残留。"""

import argparse
import logging
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))

import common

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def backup() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BASE_DIR / "backups" / f"pre-purge-{stamp}"
    dest.mkdir(parents=True, exist_ok=True)
    web = common.WEB_DIR / "data.json"
    if web.exists():
        shutil.copy2(web, dest / "data.json")
    daily = common.DAILY_DIR
    if daily.exists():
        shutil.copytree(daily, dest / "daily", dirs_exist_ok=True)
    log.info(f"已备份到 {dest}")
    return dest


def purge_web(excluded: dict, apply: bool = True):
    path = common.WEB_DIR / "data.json"
    records = common.load_json(path, []) or []
    kept = [r for r in records if not common.is_excluded(r, excluded)]
    removed = len(records) - len(kept)
    log.info(f"web/data.json: {len(records)} -> {len(kept)}（移除 {removed}）")
    if apply and removed:
        common.save_json(path, kept, indent=None)
    return removed, len(kept)


def purge_daily(excluded: dict, apply: bool = True):
    removed_total = 0
    emptied = []
    for f in sorted(common.DAILY_DIR.glob("*.json")):
        data = common.load_json(f, []) or []
        kept = [r for r in data if not common.is_excluded(r, excluded)]
        removed = len(data) - len(kept)
        if removed:
            log.info(f"  {f.name}: {len(data)} -> {len(kept)}（移除 {removed}）")
            removed_total += removed
            if apply:
                common.save_json(f, kept, indent=2)
        if data and not kept:
            emptied.append(f.stem)
    log.info(f"daily: 共移除 {removed_total} 条，清空日期 {emptied}")
    return removed_total, emptied


def write_purge_state(emptied: list):
    state = common.load_purge_state()
    old = set(state.get("purged_dates") or [])
    state["cutoff_date"] = date.today().strftime("%Y-%m-%d")
    state["purged_dates"] = sorted(old | set(emptied))
    state["updated"] = date.today().strftime("%Y-%m-%d")
    common.save_purge_state(state)
    log.info(f"purge_state: {state['purged_dates']}")


def verify(strict: bool = True) -> bool:
    ex = common.load_excluded()
    if not ex["items"]:
        log.warning("排除清单为空，跳过残留检查")
        return True

    ok = True

    def check_file(path: Path):
        nonlocal ok
        data = common.load_json(path, []) or []
        bad = [r for r in data if common.is_excluded(r, ex)]
        if bad:
            ok = False
            log.error(f"残留 {len(bad)} 条: {path}")
            for r in bad[:3]:
                log.error(f"  {r.get('pmid') or r.get('uid')} | {(r.get('title') or '')[:70]}")

    web_path = common.WEB_DIR / "data.json"
    check_file(web_path)
    for f in sorted((common.WEB_DIR / "data").glob("*.json")):
        if f.name != "index.json":
            check_file(f)
    for f in sorted(common.DAILY_DIR.glob("*.json")):
        check_file(f)

    web = common.load_json(web_path, []) or []
    shards = {}
    for f in sorted((common.WEB_DIR / "data").glob("*.json")):
        if f.name == "index.json":
            continue
        shards[f.stem] = len(common.load_json(f, []) or [])

    stats = common.load_json(common.WEB_DIR / "stats.json", {}) or {}
    index = common.load_json(common.WEB_DIR / "data" / "index.json", []) or []
    shard_total = sum(shards.values())

    if web and shard_total != len(web):
        ok = False
        log.error(f"分片合计 {shard_total} != data.json {len(web)}")
    if stats.get("total") not in (None, 0) and stats.get("total") != len(web):
        ok = False
        log.error(f"stats.total {stats.get('total')} != data.json {len(web)}")
    for item in index:
        y = str(item.get("year"))
        if shards.get(y, 0) != item.get("count"):
            ok = False
            log.error(f"index {y}: count={item.get('count')} 分片={shards.get(y, 0)}")
        if shards.get(y, 0) == 0:
            ok = False
            log.error(f"index 包含空年份 {y}")
    for y, n in shards.items():
        if n == 0 and y in {str(i.get("year")) for i in index}:
            ok = False
            log.error(f"空分片仍在 index: {y}")

    log.info(f"审计: web={len(web)} 分片合计={shard_total} stats={stats.get('total')}")
    log.info("✅ 未发现排除项残留" if ok else "❌ 审计失败")
    return ok


def run(dry_run=True, apply=False, do_backup=False, verify_only=False):
    if verify_only:
        return 0 if verify() else 1

    ex = common.load_excluded()
    log.info(f"排除清单 {len(ex['items'])} 篇")
    if not ex["items"]:
        log.warning("排除清单为空，先运行 python metaweb.py classify-scope --all")
        return 1

    if do_backup and apply:
        backup()

    purge_web(ex, apply=apply and not dry_run)
    _, emptied = purge_daily(ex, apply=apply and not dry_run)

    if apply and not dry_run:
        write_purge_state(emptied)

    if dry_run:
        log.info("dry-run：未写入任何文件")
    else:
        log.info("清除完成，下一步: python metaweb.py build && python metaweb.py scope-audit --verify")
    return 0


def main():
    parser = argparse.ArgumentParser(description="物理清除排除清单中的论文")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写入")
    parser.add_argument("--apply", action="store_true", help="执行清除")
    parser.add_argument("--backup", action="store_true", help="清除前备份到 backups/")
    parser.add_argument("--verify", action="store_true", help="只做残留审计")
    args = parser.parse_args()

    if not (args.apply or args.verify or args.dry_run):
        args.dry_run = True
    sys.exit(run(dry_run=args.dry_run, apply=args.apply,
                 do_backup=args.backup, verify_only=args.verify))


if __name__ == "__main__":
    main()
