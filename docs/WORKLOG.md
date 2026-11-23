# 工作记录：2026-11-23 重构与升级

> 本文件记录本次数据口径、界面、访客地图与发布方式的完整改动。
> 下次修改或升级前，先读本文件与 `README.md`。

## 1. 背景

- 服务器 IP 无法访问 PubMed，原先依赖 GitHub Actions 每日抓取。
- 本次改为**本地每日更新**：抓取、分类、摘要、构建都在本地完成，随后：
  1. `git push` 到 GitHub
  2. `scp` 到服务器静态目录
- GitHub Actions 已关闭（两个 workflow 已改为 `.yml.disabled`，并在仓库 Settings 中 disable actions）。

## 2. 当前数据流水线

```
fetch_pubmed.py        PubMed
fetch_journals.py      Europe PMC + OpenAlex（重点期刊）
fetch_preprints.py     bioRxiv + medRxiv
        ↓ 统一写入 data/daily/YYYY-MM-DD.json
classify_scope.py      规则预筛 + LLM 三分类 + overrides
        ↓ 排除项写入 data/excluded_pmids.json，并从 daily 移除
summarize_papers.py    AI 中文摘要（支持并发）
        ↓
build_data.py          uid 合并、期刊指标、质量过滤、分卷
        ↓
web/data.json + web/data/YYYY.json + stats.json + visitors.json
```

### 统一身份

- `uid`：`pmid:<pmid>` / `doi:<doi>` / `title:<hash>`
- PDF：`data/pmid_doi_map.json` 保存历史 PMID→DOI，build 时回填
- 前端按 `uid` 去重，预印本用 DOI 链接

### 发布流水线

```
python metaweb.py publish
  metaweb daily
  metaweb build        # 发布 web/logs/daily.log
  scope-audit --verify
  git add --force 每日数据 → commit → fetch/rebase → push
  scp 显式文件列表 → 服务器
```

实现：`scripts/publish.py`；Windows 入口：`publish.bat`。

## 3. 当前规模与口径

| 指标 | 当前值 |
|---|---|
| 文献总量 | **4281** |
| 预印本 | 75（bioRxiv 59 / medRxiv 16） |
| 来源 | PubMed 4139 / Europe PMC 61 / bioRxiv 59 / medRxiv 16 / OpenAlex 6 |
| 年份 | 2015–2026，2026 年 1160 篇 |
| 排除清单 | 1157 篇 |
| 最新发表日期 | 2026-11-22 |

口径：仅人类医学相关研究；植物、环境、食品发酵、兽医/畜牧生产不收录。
方法、算法、软件、数据库、基准论文保留（`bioinformatics_method`）。

分类关键文件：

- `scripts/scope_rules.py`：带词边界规则预筛（修复 `plant`→`implant` 等误伤）
- `scripts/classify_scope.py`：LLM 批量分类、断点续跑、低置信度复核
- `data/scope_overrides.json`：人工改判（keep/exclude）
- `data/excluded_pmids.json`：物理清除依据；fetch/build/repair 三处都会读取

## 4. 前端设计与交互

- 主题：冷白 `#F7F8F6` / 墨色 `#0D1117` / 克莱因蓝 `#2547F4` / 青绿 `#0B8F8F` / 紫 `#7C4DFF`
- 字体（自托管，含 OFL 许可）：
  - `STIX Two Text`：标题与论文标题
  - `IBM Plex Sans`：界面
  - `IBM Plex Mono`：PMID / DOI / IF 等标识
- 页头：标题 + 年度覆盖轨道（440px，可点击筛选）+ 账本 + 120px 收款码
- 表格：表头 12.5px/600，论文标题衬线；来源色块、IF/Q1/CAS 文本指标
- 卡片：左侧来源色脊，样本卡式分区
- 深色模式：跟随 `prefers-color-scheme`，冷调深空色
- 移动端：390px 无横向溢出；表格切换为卡片
- 访客地图：
  - 时间窗口：7/30/90/全部
  - 城市 tooltip；点击圆点/国家排名筛选
  - 每日访问趋势条
  - 已移除不蒜子第三方统计

设计参考：官方 `frontend-design` skill（来源 `anthropics/skills`）。该 skill 安装在 `.agents/`，已 gitignore。

## 5. 访客数据

`web/visitors.json` 结构：

```json
{
  "source": "sample | nginx-access-log",
  "total": 5011,
  "points": [],
  "countries": [],
  "daily": [{"date": "2026-11-23", "total": 160}],
  "windows": {
    "7d": {"days": 7, "total": 0, "points": [], "countries": []},
    "30d": {},
    "90d": {},
    "all": {}
  }
}
```

生成：`scripts/gen_visitors.py --days 90`。真实模式需要 `geoip2` + GeoLite2-City.mmdb + nginx 日志。

当前本地 `visitors.json` 是**示例数据**（source=sample）。GitHub 访客 workflow 已停用；需要真实数据时按 README「访客数据」手动生成并发布，或恢复 `visitors.yml.disabled`。

## 6. 配置与部署

`config.env`（gitignore，勿提交）关键项：

```ini
LLM_API_URL=
LLM_API_KEY=
LLM_MODEL=
NCBI_API_KEY=
SCOPE_LLM_MODEL=deepseek-chat
SCOPE_WORKERS=4

DEPLOY_SSH_ALIAS=seubiomed
DEPLOY_PATH=/home/yinhm/web/meta.seubiomed.com/web
SITE_URL=https://meta.seubiomed.com/
```

服务器：

- SSH 别名：`seubiomed`（`~/.ssh/config`）
- 静态目录：`/home/yinhm/web/meta.seubiomed.com/web`
- `web/logs` 是 `../logs` 的软链接；`publish.py` 使用显式文件列表，避免覆盖软链接
- 本地 Windows 任务：`MetaLitPublish`，每天 20:00，运行 `publish.bat`；当前为 interactive-only

GitHub Actions：

- `.github/workflows/daily.yml.disabled`
- `.github/workflows/visitors.yml.disabled`
- `.github/workflows/README.md` 记录恢复方式
- 仓库 Settings → Actions 已由用户 disable

## 7. 常用命令

```bash
# 每日更新并发布（推荐）
python metaweb.py publish

# 只部署现有数据
python metaweb.py publish --no-update

# 检查 SSH/部署配置
python metaweb.py publish --dry-run

# 分类审计
python metaweb.py scope-audit --verify

# 单独抓取期刊/预印本
python metaweb.py fetch-journals --days 7
python metaweb.py fetch-preprints --days 7

# 重新分类（全量或某个 daily）
python metaweb.py classify-scope --all --workers 6
python metaweb.py classify-scope --date 2026-11-23 --apply-daily

# 查看/修改任务
schtasks /Query /TN "MetaLitPublish" /FO LIST
MSYS_NO_PATHCONV=1 schtasks /Change /TN "MetaLitPublish" /ST 21:00
```

## 8. 升级/修改指南

### 改代码

1. 修改代码并单独 commit（`publish` 会拒绝未提交代码改动）
2. 运行 `python metaweb.py publish --no-update` 验证推送/部署
3. 下次每日任务自动包含改动

### 改分类口径

- 规则：`scripts/scope_rules.py` 的词表
- Prompt：`scripts/classify_scope.py` 的 `SYSTEM_PROMPT`
- 人工改判：`data/scope_overrides.json`
- 改规则后建议 `classify-scope --all --force`，复核后 `scope-purge --apply` 或重新物化

### 改期刊名单

编辑 `data/journals_sources.tsv`，然后：

```bash
python metaweb.py fetch-journals --days 30 --dry-run
python metaweb.py publish
```

### 改部署目标

编辑 `config.env` 的 `DEPLOY_SSH_ALIAS` / `DEPLOY_PATH`，先 `publish --dry-run`，再 `publish --no-update`。

### 恢复访客自动更新

```bash
git mv .github/workflows/visitors.yml.disabled .github/workflows/visitors.yml
git commit -m "ci: 恢复访客地图工作流"
git push
```

需要 GitHub Secrets：`SSH_HOST`、`SSH_USER`、`SSH_PRIVATE_KEY`、`MAXMIND_LICENSE_KEY` 等（见 workflow 原文）。

## 9. 已知问题 / 后续可做

- `web/visitors.json` 当前为示例数据；真实数据需本地生成或恢复 visitors workflow。
- 预印本中仍可能出现 `WITHDRAWN:` / `RETRACTED:` / Correction 标题；建议在 `fetch_preprints.parse_item` 增加标题前缀过滤，并清理已有记录。
- OpenAlex 翻页偶尔 401（免费额度/权限限制）；Europe PMC 为主通道，OpenAlex 只做首页补量。
- 少数期刊 ahead-of-print 记录无摘要，已尝试 PubMed/OpenAlex 补全；仍无摘要的非综述会被新抓取逻辑丢弃。
- 表格在 1440px 宽度下仍可能横向滚动（12 列）；页面上有滚动提示。
- 本地任务为 interactive-only；注销后不会运行。

## 10. 验证清单

```bash
python metaweb.py publish --dry-run
python metaweb.py scope-audit --verify
ssh seubiomed 'test -w /home/yinhm/web/meta.seubiomed.com/web && echo OK'
curl -s https://meta.seubiomed.com/stats.json
schtasks /Query /TN "MetaLitPublish" /FO LIST
```

重点断言：

- `web/data.json` 总数 = 分片合计 = `stats.total`
- 排除项残留 0
- 本地与线上 `stats.total` 一致
- `web/logs` 服务器软链接未被替换

## 11. 关键提交（最近）

```
640dd28 docs: README 同步本地发布流程；停用全部 GitHub Actions
9d1cb42 feat: 新增本地发布流程（GitHub + scp），停用 GHA 每日定时
2ae2bb9 feat: 交互式访客地图与页面细节调整
a95c247 feat(ui): 切换冷白 · 克莱因蓝 · 青绿配色
83b57cd feat(ui): 重做视觉系统 — 革兰染色色板、测序覆盖轨道与学术排版
34c28fc feat: 医学主题清洗 + 期刊/预印本多源采集（文献库 5235→4280）
```

> 后续日常提交为 `chore: 本地每日更新 YYYY-MM-DD HH:MM`。
