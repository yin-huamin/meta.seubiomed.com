#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_visitors.py — 从 nginx 访问日志生成真实访客分布数据 (web/visitors.json)

原理
----
nginx 已经在 access_log 中记录每个访客的真实 IP。本脚本解析 combined 格式的
日志，用 MaxMind GeoLite2-City 数据库把 IP 转成经纬度 / 国家，按坐标聚合成
"热点"，输出给前端 (web/index.html) 绘制真实访客地图。

特点
----
- 零额外常驻服务：cron 每日跑一次即可，前端直接 fetch 静态 JSON。
- 不依赖任何第三方统计服务（无 ClustrMaps / Google Analytics 之类外部请求）。
- geoip2 或 mmdb 缺失时优雅降级：--demo 可生成样例数据用于本地测试。

用法
----
  # 真实模式（服务器端）
  python scripts/gen_visitors.py \
      --log /var/log/nginx/meta.seubiomed.com.access.log \
      --mmdb /usr/share/GeoIP/GeoLite2-City.mmdb \
      --out web/visitors.json

  # 本地测试：生成样例数据
  python scripts/gen_visitors.py --demo --out web/visitors.json

依赖
----
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


def build_demo():
    """本地测试样例：若干主要城市 + 随机访问量。"""
    import random
    random.seed(20260724)
    cities = [
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
    points = {}
    countries = defaultdict(int)
    total = 0
    for iso, city, lat, lon, base in cities:
        cnt = max(1, int(base * (0.7 + random.random() * 0.6)))
        points[bucket_key(lat, lon)] = {
            "count": cnt, "country": iso, "city": city
        }
        countries[iso] += cnt
        total += cnt
    return points, countries, total


def to_json(points, countries, total):
    pts = [
        {"lat": k[0], "lon": k[1], "count": v["count"],
         "country": v["country"], "city": v["city"]}
        for k, v in points.items()
    ]
    # 按访问量降序，前端可优先绘制大点
    pts.sort(key=lambda p: p["count"], reverse=True)
    top_countries = sorted(
        ({"code": c, "count": n} for c, n in countries.items()),
        key=lambda x: x["count"], reverse=True
    )[:12]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "nginx-access-log",
        "total": total,
        "points": pts,
        "countries": top_countries,
    }


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
        sys.stderr.write("[info] demo 模式：生成样例访客数据\n")
        points, countries, total = build_demo()
    else:
        if not os.path.exists(args.log):
            sys.stderr.write(f"[error] 日志文件不存在: {args.log}\n")
            sys.exit(2)
        reader = make_geo(args.mmdb)
        sys.stderr.write(f"[info] 解析日志: {args.log}\n")
        points, countries, total = build_from_log(args.log, reader, since=since)
        if reader is not None:
            reader.close()

    data = to_json(points, countries, total)
    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    sys.stderr.write(
        f"[ok] 已写出 {args.out}：{total} 次访问，{len(data['points'])} 个热点\n"
    )


if __name__ == "__main__":
    main()
