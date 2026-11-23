#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_visitors.py — 从 nginx 访问日志生成真实访客分布数据 (web/visitors.json)

原理
----
nginx 已经在 access_log 中记录每个访客的真实 IP。本脚本解析 combined 格式的
日志，用 MaxMind GeoLite2-City 数据库把 IP 转成经纬度 / 国家，按坐标聚合成
"热点"，输出给前端 (web/index.html) 绘制真实访客地图。

重要（部署约束）
----------------
为遵守"服务器不安装额外软件"的约定，**geoip2 + GeoLite2 数据库只装在
你的本地机器 / 开发机**，本脚本在本地运行，把输出的 `web/visitors.json`
提交进仓库即可。生产服务器只是静态托管这个 JSON 文件，**无需 pip install、
无需下载任何数据库、无需 cron**。

特点
----
- 服务器零安装：只需静态托管 web/visitors.json，不跑任何后端进程。
- 不依赖任何第三方统计服务（无 ClustrMaps / Google Analytics 之类外部请求）。
- geoip2 或 mmdb 缺失时优雅降级：--demo 可生成样例数据用于本地测试。

用法
----
  # 真实模式（在你本地机器 / 开发机运行，不在服务器）
  python scripts/gen_visitors.py \
      --log ~/meta.seubiomed.com.access.log \
      --mmdb ~/GeoLite2-City.mmdb \
      --out web/visitors.json
  git add web/visitors.json && git commit && git push   # 推到仓库即上线

  # 本地测试：生成样例数据（source 标记为 sample，前端会标注"示例数据"）
  python scripts/gen_visitors.py --demo --out web/visitors.json

依赖（仅本地需要，服务器不需要）
----------------------------------
  真实模式需要: pip install geoip2  +  下载 GeoLite2-City.mmdb (免费, 需 MaxMind 账号)
"""

import argparse
import gzip
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

# ── nginx combined 日志正则 ────────────────────────────────────────────────
# 示例: 1.2.3.4 - - [24/Jul/2026:15:14:27 +0800] "GET / HTTP/1.1" 200 1234 "..." "UA"
LOG_RE = re.compile(
    r'(?P<ip>\S+)\s+\S+\s+\S+\s+'
    r'\[(?P<time>[^\]]+)\]\s+'
    r'"(?P<method>\S+)\s+(?P<path>\S+)\s+(?P<proto>[^"]*)"\s+'
    r'(?P<status>\d+)\s+(?P<bytes>\S+)\s+'
    r'"(?P<ref>[^"]*)"\s+"(?P<ua>[^"]*)"'
)
TIME_FMT = "%d/%b/%Y:%H:%M:%S %z"

# 常见爬虫 UA 关键词（统计访客分布时尽量排除）
BOT_HINTS = ("bot", "crawler", "spider", "curl", "python", "go-http", "wget",
             "archive", "semrush", "ahrefs", "pingdom", "uptime", "zgrab")


def open_log(path):
    """支持普通文件与 .gz 压缩日志（nginx 轮转后常见）。"""
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="ignore")
    return open(path, "rt", encoding="utf-8", errors="ignore")


def parse_time(s):
    try:
        return datetime.strptime(s, TIME_FMT)
    except Exception:
        return None


def is_bot(ua):
    u = (ua or "").lower()
    return any(h in u for h in BOT_HINTS)


def make_geo(mmdb_path):
    """延迟加载 geoip2；缺失则返回 None（降级：无地理信息）。"""
    if not mmdb_path or not os.path.exists(mmdb_path):
        return None
    try:
        import geoip2.database
        return geoip2.database.Reader(mmdb_path)
    except Exception as e:
        sys.stderr.write(f"[warn] geoip2 不可用或 mmdb 缺失，地理信息将跳过: {e}\n")
        return None


def geo_lookup(reader, ip):
    if reader is None:
        return None
    try:
        r = reader.city(ip)
        if r.location is None or r.location.latitude is None:
            return None
        return (r.location.latitude, r.location.longitude,
                r.country.iso_code or "", r.city.name or "")
    except Exception:
        return None


def bucket_key(lat, lon):
    """坐标归约到 0.1° 网格（约 11km），同城访客聚为一处。"""
    return (round(lat, 1), round(lon, 1))


def build_from_log(log_path, reader, since=None):
    points = defaultdict(lambda: {"count": 0, "country": "", "city": ""})
    countries = defaultdict(int)
    total = 0
    skipped = 0
    with open_log(log_path) as fh:
        for line in fh:
            m = LOG_RE.search(line)
            if not m:
                continue
            # 只统计成功的页面请求
            if m.group("method") != "GET" or m.group("status") not in ("200", "304"):
                skipped += 1
                continue
            if is_bot(m.group("ua")):
                skipped += 1
                continue
            t = parse_time(m.group("time"))
            if t and since and t < since:
                continue
            ip = m.group("ip")
            g = geo_lookup(reader, ip)
            if not g:
                skipped += 1
                continue
            lat, lon, iso, city = g
            key = bucket_key(lat, lon)
            d = points[key]
            d["count"] += 1
            d["country"] = iso or d["country"]
            if not d["city"] and city:
                d["city"] = city
            if iso:
                countries[iso] += 1
            total += 1
    return points, countries, total


DEMO_CITIES = [
    ("CN", "Beijing", 39.9, 116.4, 900),
    ("CN", "Shanghai", 31.2, 121.5, 700),
    ("US", "New York", 40.7, -74.0, 520),
    ("GB", "London", 51.5, -0.1, 430),
    ("US", "San Francisco", 37.8, -122.4, 380),
    ("JP", "Tokyo", 35.7, 139.7, 350),
    ("DE", "Berlin", 52.5, 13.4, 240),
    ("AU", "Sydney", -33.8, 151.0, 210),
    ("SG", "Singapore", 1.35, 103.8, 190),
    ("FR", "Paris", 48.9, 2.35, 170),
    ("CA", "Toronto", 43.7, -79.4, 150),
    ("BR", "São Paulo", -23.5, -46.6, 120),
    ("IN", "Bangalore", 12.97, 77.59, 110),
    ("NL", "Amsterdam", 52.37, 4.9, 95),
    ("KR", "Seoul", 37.56, 126.97, 88),
]


def build_daily_from_log(log_path, reader, since=None):
    """单次解析日志，按 (日期, 坐标) / (日期, 国家) 聚合。"""
    daily_points = defaultdict(int)      # (date, lat, lon, iso, city) -> count
    daily_countries = defaultdict(int)   # (date, iso) -> count
    daily_totals = defaultdict(int)      # date -> count
    with open_log(log_path) as fh:
        for line in fh:
            m = LOG_RE.search(line)
            if not m:
                continue
            if m.group("method") != "GET" or m.group("status") not in ("200", "304"):
                continue
            if is_bot(m.group("ua")):
                continue
            t = parse_time(m.group("time"))
            if t is None:
                continue
            if since and t < since:
                continue
            g = geo_lookup(reader, m.group("ip"))
            if not g:
                continue
            lat, lon, iso, city = g
            lat, lon = bucket_key(lat, lon)
            date_str = t.date().isoformat()
            daily_points[(date_str, lat, lon, iso or "", city or "")] += 1
            if iso:
                daily_countries[(date_str, iso)] += 1
            daily_totals[date_str] += 1
    return daily_points, daily_countries, daily_totals


def build_demo_daily(days=90):
    """确定性样例：90 天 × 主要城市的每日访问量。"""
    import random
    random.seed(20260724)
    today = datetime.now(timezone.utc).date()
    daily_points = defaultdict(int)
    daily_countries = defaultdict(int)
    daily_totals = defaultdict(int)
    for offset in range(days):
        date_str = (today - timedelta(days=offset)).isoformat()
        for iso, city, lat, lon, base in DEMO_CITIES:
            daily_base = max(1, base // 30)
            cnt = max(0, int(daily_base * random.uniform(0.55, 1.45)))
            if random.random() < 0.12:
                cnt += int(daily_base * random.uniform(0.8, 2.2))
            if cnt <= 0:
                continue
            daily_points[(date_str, lat, lon, iso, city)] += cnt
            daily_countries[(date_str, iso)] += cnt
            daily_totals[date_str] += cnt
    return daily_points, daily_countries, daily_totals


def aggregate_window(daily_points, daily_countries, daily_totals, min_date=None):
    points = defaultdict(lambda: {"count": 0, "country": "", "city": ""})
    countries = defaultdict(int)
    total = 0
    for (date_str, lat, lon, iso, city), n in daily_points.items():
        if min_date and date_str < min_date:
            continue
        key = (lat, lon)
        d = points[key]
        d["count"] += n
        d["country"] = iso or d["country"]
        d["city"] = city or d["city"]
    for (date_str, iso), n in daily_countries.items():
        if min_date and date_str < min_date:
            continue
        countries[iso] += n
    for date_str, n in daily_totals.items():
        if min_date and date_str < min_date:
            continue
        total += n
    return points, countries, total


def _points_payload(points):
    pts = [
        {"lat": k[0], "lon": k[1], "count": v["count"],
         "country": v["country"], "city": v["city"]}
        for k, v in points.items()
    ]
    pts.sort(key=lambda p: p["count"], reverse=True)
    return pts


def _countries_payload(countries):
    return sorted(
        ({"code": c, "count": n} for c, n in countries.items()),
        key=lambda x: x["count"], reverse=True
    )[:12]


def _daily_payload(daily_totals, max_days=90):
    dates = sorted(daily_totals)[-max_days:]
    return [{"date": d, "total": daily_totals[d]} for d in dates]


def to_json(points, countries, total, source="nginx-access-log",
            windows=None, daily=None):
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "total": total,
        "points": _points_payload(points),
        "countries": _countries_payload(countries),
    }
    if windows:
        data["windows"] = windows
    if daily:
        data["daily"] = daily
    return data


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    default_out = os.path.join(repo_root, "web", "visitors.json")

    ap = argparse.ArgumentParser(description="生成真实访客分布 JSON")
    ap.add_argument("--log", default="/var/log/nginx/access.log",
                    help="nginx access_log 路径（支持 .gz）")
    ap.add_argument("--mmdb", default="/usr/share/GeoIP/GeoLite2-City.mmdb",
                    help="GeoLite2-City.mmdb 路径")
    ap.add_argument("--out", default=default_out, help="输出 JSON 路径")
    ap.add_argument("--days", type=int, default=0,
                    help="仅统计最近 N 天的访问（0=全部）")
    ap.add_argument("--demo", action="store_true",
                    help="生成样例数据（无需日志/geoip）")
    args = ap.parse_args()

    since = None
    if args.days > 0:
        since = datetime.now(timezone.utc) - timedelta(days=args.days)

    if args.demo:
        sys.stderr.write("[info] demo 模式：生成样例访客数据（source=sample）\n")
        demo_days = args.days or 90
        daily_points, daily_countries, daily_totals = build_demo_daily(demo_days)
        source = "sample"
    else:
        if not os.path.exists(args.log):
            sys.stderr.write(f"[error] 日志文件不存在: {args.log}\n")
            sys.exit(2)
        reader = make_geo(args.mmdb)
        sys.stderr.write(f"[info] 解析日志: {args.log}\n")
        daily_points, daily_countries, daily_totals = build_daily_from_log(
            args.log, reader, since=since)
        if reader is not None:
            reader.close()
        source = "nginx-access-log"

    today = datetime.now(timezone.utc).date()
    specs = [("7d", 7), ("30d", 30), ("90d", 90), ("all", None)]
    windows = {}
    default_window = None
    for key, days in specs:
        min_date = (today - timedelta(days=days - 1)).isoformat() if days else None
        p, c, t = aggregate_window(daily_points, daily_countries, daily_totals,
                                   min_date=min_date)
        if key == "30d":
            default_window = (p, c, t)
        windows[key] = {
            "days": days,
            "total": t,
            "points": _points_payload(p),
            "countries": _countries_payload(c),
        }

    p, c, t = default_window or aggregate_window(
        daily_points, daily_countries, daily_totals)
    data = to_json(p, c, t, source, windows=windows,
                   daily=_daily_payload(daily_totals, 90))
    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    sys.stderr.write(
        f"[ok] 已写出 {args.out}：30天 {windows['30d']['total']} 次访问，"
        f"{len(windows['30d']['points'])} 个热点，{len(windows)} 个时间窗口\n"
    )


if __name__ == "__main__":
    main()
