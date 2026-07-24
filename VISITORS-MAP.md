# 真实访客地图部署说明

首页"全球访客分布"地图的数据来自 **nginx 访问日志 + MaxMind GeoIP**，
由 `scripts/gen_visitors.py` 聚合生成 `web/visitors.json`，前端 `web/index.html`
直接 `fetch` 该静态文件绘制真实热点。

## ⚠️ 核心约定：服务器零安装

**生产服务器只负责静态托管 `web/visitors.json`，不安装任何额外软件、不下载数据库、不跑 cron。**

`geoip2` 和 `GeoLite2` 数据库**只在你的本地机器 / 开发机**上准备一次，
本脚本在本地运行后把 `web/visitors.json` 提交进仓库即可上线。
这样完全避免了"在服务器上下载软件"的问题。

---

## 1. 推荐：GitHub Actions 自动刷新（日常零手动）

已内置工作流 `.github/workflows/visitors.yml`：每天北京时间 02:10 自动运行，
在 **GitHub Runner** 内 `scp` 拉取服务器 nginx 日志 → 用 geoip2 + GeoLite2 处理 →
提交 `web/visitors.json` → 推送。**服务器只做 `git pull` 同步，不装任何软件。**

### 一次性操作（只需做一次）

**A. 服务器（唯一需要碰服务器的地方，零软件安装）**
生成一对专供 Actions 使用的 SSH 密钥，把公钥加进服务器 `authorized_keys`：

```bash
# 在你本地任意机器执行
ssh-keygen -t ed25519 -N "" -f github_actions_key
# 把公钥装到服务器（SSH_USER 需能读取 nginx 日志，通常是 root）
ssh-copy-id -i github_actions_key.pub root@你的服务器
# 或手动：cat github_actions_key.pub >> ~/.ssh/authorized_keys
```

> 仅添加一行公钥，服务器不安装任何程序。日志路径：
> `/var/log/nginx/meta.seubiomed.com.access.log`（SSH_USER 须有读权限，
> 若用非 root 账号，请把该用户加入 `adm` 组或放宽日志文件权限）。

**B. GitHub 仓库 Secrets**（仓库 Settings → Secrets and variables → Actions → New repository secret）

| Secret 名             | 值                                        |
|-----------------------|-------------------------------------------|
| `SSH_HOST`            | 服务器 IP 或域名                           |
| `SSH_USER`            | 可读取 nginx 日志的账号（如 `root`）       |
| `SSH_PORT`            | SSH 端口（默认 `22`，可省略）              |
| `SSH_PRIVATE_KEY`     | 上面生成的 `github_actions_key` 私钥全文   |
| `MAXMIND_LICENSE_KEY` | 你的 MaxMind License Key（本地已用过）     |

> 设置完即永久生效，之后每天自动跑，无需任何手动操作。
> 想立即验证？到 Actions 页面手动 `Run workflow` 触发一次即可。

### 原理
- geoip2、GeoLite2 数据库都装在 GitHub Runner（别人的机器），不在你的服务器。
- 与现有 `daily.yml`（PubMed 每日更新）同一模式：Runner 算完 → `git push` → 服务器 `git pull` 同步静态站。
- 如需停止自动刷新：在 Actions 页面 Disable 该 workflow 即可。

---

## 2. 本地手动（备选方案）

若不想用 GitHub Actions（如服务器 SSH 对 GitHub IP 不可达），可改回本地手动：

### 2.1 本地一次性准备（不在服务器）

```bash
# 本地 Python 环境
pip install geoip2

# 下载 GeoLite2 City 数据库（免费，需 MaxMind 账号）
#   https://www.maxmind.com/ → 注册 → 下载 GeoLite2 City (mmdb)
#   保存到本地，例如 ~/GeoLite2-City.mmdb
```

> 只需在本地做一次。之后每次刷新地图，复用这个环境即可。

### 2.2 本地生成并推送（日常刷新流程）

```bash
# 1) 把服务器上的访问日志取到本地（任选其一）
scp root@你的服务器:/var/log/nginx/meta.seubiomed.com.access.log ~/meta.access.log
#   或登录服务器后打包下载；支持 .gz 压缩日志

# 2) 在本地仓库目录运行生成脚本
python scripts/gen_visitors.py \
    --log ~/meta.access.log \
    --mmdb ~/GeoLite2-City.mmdb \
    --out web/visitors.json
#   仅统计最近 30 天：追加  --days 30

# 3) 提交并推送（服务器下一次拉取即生效，无需任何服务器操作）
git add web/visitors.json
git commit -m "update: 刷新访客地图数据"
git push
```

`web/visitors.json` 已被纳入 git 跟踪（已从 `.gitignore` 移除），
所以上述 `git add` 即可纳入版本控制。

---

## 3. 本地预览（无需服务器）

```bash
python serve.py            # http://localhost:8089
# 先生成样例数据看效果（source 标记为 sample，前端标注"示例数据"）：
python scripts/gen_visitors.py --demo --out web/visitors.json
```

---

## 4. 输出格式

```json
{
  "generated_at": "2026-07-24T...",
  "source": "nginx-access-log",
  "total": 5174,
  "points": [ {"lat":39.9,"lon":116.4,"count":1150,"country":"CN","city":"Beijing"} ],
  "countries": [ {"code":"CN","count":2055} ]
}
```

- `source` 取值：`nginx-access-log`（真实日志）或 `sample`（--demo 样例）。
  前端据此区分标注"基于访问日志"还是"示例数据"。
- `points` 为聚合热点，圆点半径 / 透明度随 `count` 缩放；鼠标悬停显示"城市 国家 · N 次访问"。
- 文件缺失 / 为空时，前端自动回退到装饰性点阵，地图不空白。

---

## 5. nginx 日志格式（无需改动，仅说明）

脚本解析标准 **combined** 格式（你现有的配置已是此格式，无需修改）：

```
log_format main '$remote_addr - $remote_user [$time_local] '
                '"$request" $status $body_bytes_sent '
                '"$http_referer" "$http_user_agent"';
```

- 直连服务器：`$remote_addr` 即真实访客 IP，无需改动。
- 若日后接入 Cloudflare / 反代：`$remote_addr` 会变上游 IP，需在 nginx 用
  `set_real_ip_from` + `real_ip_header X-Forwarded-For` 还原真实 IP
  （纯配置改动，不涉及下载软件）。

---

## 6. 过滤规则

脚本已内置基础过滤，保证地图反映"真实人类访客"：

- 仅统计 `GET` 且状态码 `200/304` 的请求
- 排除常见爬虫 UA（bot / crawler / spider / curl / python / go-http / wget / 各 SEO 工具等）
- IP 无法解析地理位置时跳过（不计入）

如需更精细（排除内网 IP、特定 UA 等），修改 `scripts/gen_visitors.py` 中的
`BOT_HINTS` / `is_bot()` / `build_from_log()` 即可。

---

## 7. （可选增强）彻底免数据库：走 Cloudflare

若日后把站点接入 **Cloudflare**，其会注入 `CF-IPCountry` 请求头（国家 ISO 码），
无需任何 GeoIP 数据库即可拿到国家级数据（连本地 geoip2 都不用装）：

1. nginx 日志增加该头字段（纯配置改动，无下载）：
   ```
   log_format main '$remote_addr - $remote_user [$time_local] '
                   '"$request" $status $body_bytes_sent '
                   '"$http_referer" "$http_user_agent" $http_cf_ipcountry';
   ```
2. 改用一个"按国家码聚合"的生成模式（纯标准库，不依赖 geoip2 / mmdb）。

> 当前站点未接 Cloudflare，此增强暂未实现；如需我可补充对应脚本模式。
> 在此之前，"本地 geoip2 生成 + 提交"已满足"服务器零安装"的要求。
