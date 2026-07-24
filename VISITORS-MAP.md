# 真实访客地图部署说明

首页"全球访客分布"地图的数据来自 **nginx 访问日志 + MaxMind GeoIP**，
由 `scripts/gen_visitors.py` 每日聚合生成 `web/visitors.json`，前端 `web/index.html`
直接 `fetch` 该静态文件绘制真实热点。**零额外常驻服务、不依赖任何第三方统计平台。**

---

## 1. 安装依赖

```bash
# 在服务器上（项目 venv 或系统 Python）
pip install geoip2
```

GeoLite2 数据库（免费，需 MaxMind 账号）：

1. 注册 https://www.maxmind.com/ 免费账号
2. 下载 **GeoLite2 City** 数据库（mmdb 格式）
3. 解压到服务器，例如 `/usr/share/GeoIP/GeoLite2-City.mmdb`

> 建议用 MaxMind 官方的 `geoipupdate` 工具或简单 cron 每月拉取一次新版，保持库新鲜。

---

## 2. 确认 nginx 日志格式

脚本解析标准 **combined** 格式：

```
log_format main '$remote_addr - $remote_user [$time_local] '
                '"$request" $status $body_bytes_sent '
                '"$http_referer" "$http_user_agent"';
```

关键点：

- **直连服务器（无 CDN）**：`$remote_addr` 就是真实访客 IP，无需改动。
- **若站点是 Cloudflare / 反代**：`$remote_addr` 会是上游 IP。请改用真实访客 IP 字段，例如：

  ```
  # Cloudflare
  set_real_ip_from 103.21.244.0/22;   # 见 Cloudflare 官方 IP 段
  real_ip_header X-Forwarded-For;
  real_ip_recursive on;
  # 此时 $remote_addr 即为访客真实 IP
  ```

脚本默认读取 `/var/log/nginx/access.log`，请用 `--log` 指定你站点的实际路径
（如 `/var/log/nginx/meta.seubiomed.com.access.log`）。支持 `.gz` 压缩日志（nginx 轮转后常见）。

---

## 3. 生成数据

```bash
# 真实模式
python scripts/gen_visitors.py \
    --log /var/log/nginx/meta.seubiomed.com.access.log \
    --mmdb /usr/share/GeoIP/GeoLite2-City.mmdb \
    --out web/visitors.json

# 仅统计最近 30 天
python scripts/gen_visitors.py --log <日志> --mmdb <库> --out web/visitors.json --days 30

# 本地测试（无需日志/GeoIP，生成样例城市数据）
python scripts/gen_visitors.py --demo --out web/visitors.json
```

输出 `web/visitors.json` 结构：

```json
{
  "generated_at": "2026-07-24T...",
  "source": "nginx-access-log",
  "total": 5174,
  "points": [ {"lat":39.9,"lon":116.4,"count":1150,"country":"CN","city":"Beijing"} ],
  "countries": [ {"code":"CN","count":2055} ]
}
```

---

## 4. 配置定时任务（cron）

```bash
# 每日 02:10 重新聚合
10 2 * * *  cd /home/yinhm/web/meta.seubiomed.com && /usr/bin/python3 scripts/gen_visitors.py --log /var/log/nginx/meta.seubiomed.com.access.log --mmdb /usr/share/GeoIP/GeoLite2-City.mmdb --out web/visitors.json >> logs/visitors.log 2>&1
```

注意：

- cron 用户需能**读取** nginx 日志（通常 root，或加入 `adm` 组）。
- `web/visitors.json` 已加入 `.gitignore`，**不会被 git 提交**——它由服务器 cron 生成，请勿手动提交。

---

## 5. 过滤规则

脚本已内置基础过滤，保证地图反映"真实人类访客"：

- 仅统计 `GET` 且状态码 `200/304` 的请求
- 排除常见爬虫 UA（bot / crawler / spider / curl / python / go-http / wget / 各 SEO 工具等）
- IP 无法解析地理位置时跳过（不计入）

如需更精细（如排除内网 IP、特定 UA），修改 `scripts/gen_visitors.py` 中的
`BOT_HINTS` / `is_bot()` / `build_from_log()` 即可。

---

## 6. 前端行为

`web/index.html` 底部脚本：

- 加载时 `fetch('visitors.json')` 获取真实热点，按经纬度投影绘制圆点
  （**半径与透明度随访问量缩放**，鼠标悬停显示"城市 + 国家 + 次数"）
- 若文件缺失 / 为空（如刚部署、cron 尚未跑），自动回退到装饰性点阵，地图不空白
- 说明文字：有数据时显示"访客分布（基于访问日志）"，无数据时显示"访客分布（暂无数据）"

---

## 7. 本地预览

```bash
python serve.py            # http://localhost:8089
# 先生成样例数据看效果：
python scripts/gen_visitors.py --demo --out web/visitors.json
```
