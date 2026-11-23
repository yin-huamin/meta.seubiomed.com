# 宏基因组文献索引 (Meta-SeuBiomed)

> 本地每日更新宏基因组、耐药与基因组拼装文献，AI 生成中文摘要；更新后推送 GitHub 并通过 scp 部署到服务器。

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8+-blue.svg)]()

## 目录

- [项目简介](#项目简介)
- [功能特性](#功能特性)
- [项目结构](#项目结构)
- [安装配置](#安装配置)
- [设置搜索关键词](#设置搜索关键词)
- [Quick Start](#quick-start)
- [使用方法](#使用方法)
- [本地预览](#本地预览)
- [本地每日更新并发布](#本地每日更新并发布推荐)
- [GitHub Actions 已关闭](#github-actions-已关闭)
- [服务器部署](#服务器部署nginx)
- [高级用法](#高级用法)
- [开发记录](docs/WORKLOG.md)
- [许可证](#许可证)

---

## 项目简介

Meta-SeuBiomed 是一个面向人类医学研究的宏基因组文献索引。它能够：

- 从 PubMed、Europe PMC、OpenAlex、bioRxiv 与 medRxiv 汇总最新文献
- 用规则 + LLM 做医学口径分类，保留人类医学与生物信息学方法论文
- 使用 AI（支持 OpenAI / DeepSeek / 本地 Ollama）生成中文摘要
- 将数据整合为静态 JSON，供表格、卡片与交互式访客地图展示
- 在本地完成每日更新，随后推送 GitHub 并用 `scp` 部署到服务器

后端纯 Python 标准库实现，前端纯 HTML/CSS/JS，无框架依赖。

## 功能特性

- **多源采集**：PubMed + Europe PMC + OpenAlex + bioRxiv/medRxiv
- **医学口径**：规则预筛 + LLM 三分类 + 人工 overrides，排除植物/环境/食品发酵/畜牧生产
- **AI 摘要**：中文摘要、创新点、局限、研究对象、疾病、样本量
- **期刊指标**：IF、JCR 分区、中科院分区；预印本与重点期刊豁免质量过滤
- **本地发布**：`metaweb.py publish` 一条命令完成更新、Git 推送与服务器部署
- **静态前端**：响应式表格/卡片、来源筛选、年份覆盖轨道、深色模式
- **交互地图**：7/30/90/全部访客窗口、城市 tooltip、国家排名筛选、每日趋势
- **搜索高亮**：搜索关键词在结果中高亮显示

## 项目结构

```
meta-seubiomed/
├── metaweb.py                 # 统一命令行工具
├── publish.bat                # Windows 一键发布（更新 + GitHub + scp）
├── scripts/
│   ├── fetch_pubmed.py         # PubMed 抓取
│   ├── fetch_journals.py       # Europe PMC / OpenAlex 期刊抓取
│   ├── fetch_preprints.py      # bioRxiv / medRxiv 预印本
│   ├── summarize_papers.py     # AI 摘要
│   ├── classify_scope.py       # 医学主题三分类
│   ├── scope_rules.py          # 规则预筛
│   ├── scope_purge.py          # 排除项物理清除与审计
│   ├── build_data.py           # 数据整合与分片
│   ├── daily_update.py         # 每日更新编排
│   ├── publish.py              # 本地发布（Git + scp）
│   ├── gen_visitors.py         # 访客地图 JSON（7/30/90/全部窗口）
│   └── common.py               # uid / DOI / 排除清单共享工具
├── data/                       # daily 原始数据、分类状态、排除清单、DOI 映射
├── web/
│   ├── index.html              # 前端页面
│   ├── data/                   # 按年份拆分的数据
│   ├── fonts/                  # 自托管 STIX / IBM Plex 字体
│   ├── png/                    # 微信收款码
│   ├── logs/                   # 发布后的爬取日志
│   └── visitors.json           # 访客地图数据
├── .github/workflows/          # 已停用（.yml.disabled，仅作参考）
├── serve.py                    # 本地预览服务器
├── journal_info.tsv            # 期刊信息表（IF/JCR/中科院分区）
├── config.env.example          # 配置模板（含部署配置）
├── requirements.txt            # Python 依赖（无第三方依赖）
├── README.md
└── LICENSE
```

## 安装配置

### 1. 环境要求

- Python 3.8+（推荐 3.11+）
- 无需安装任何第三方 Python 库

### 2. 克隆项目

```bash
git clone https://github.com/yin-huamin/meta.seubiomed.com.git
cd meta-seubiomed
```

### 3. 配置 API Key

```bash
# 复制配置模板
cp config.env.example config.env

# 编辑 config.env，填写你的 API Key
# 必填：LLM_API_URL、LLM_API_KEY、LLM_MODEL
# 可选：NCBI_API_KEY（加速 PubMed 抓取）
vim config.env
```

#### LLM 配置示例

| 服务商 | API URL | 模型 | 备注 |
|--------|---------|------|------|
| OpenAI | `https://api.openai.com/v1/chat/completions` | `gpt-4o-mini` | 默认 |
| DeepSeek | `https://api.deepseek.com/v1/chat/completions` | `deepseek-chat` | 更便宜 |
| 本地 Ollama | `http://localhost:11434/v1/chat/completions` | `qwen2.5:7b` | 免费 |

## 设置搜索关键词

使用 `metaweb set` 命令管理搜索关键词，无需编辑代码。

### 查看当前关键词

```bash
python metaweb.py set --check
```

### 设置新关键词

```bash
# 设置关键词（空格分隔多个）
python metaweb.py set --term metagenome metagenomic microbiome

# 添加益生菌相关
python metaweb.py set --term metagenome metagenomic microbiome probiotics
```

关键词保存在 `config.env` 的 `SEARCH_KEYWORDS` 字段中，也可直接编辑该文件。

默认关键词：`metagenome`, `metagenomic`, `microbiome`

## Quick Start

配置好 `config.env` 后，即可一键运行：

### 自动抓取最近 7 天并整合

```bash
python metaweb.py auto --days 7
```

这条命令自动完成三件事：
1. **抓取**：从 PubMed 搜索最近 7 天的文献
2. **摘要**：调用 AI 为每篇论文生成中文摘要
3. **整合**：将数据合并到 `web/data.json`，供前端展示

### 本地更新并发布

```bash
python metaweb.py publish
```

推荐用于日常：抓取全部来源 → 分类/摘要/构建 → 提交推送 GitHub → scp 部署服务器。

### 按 PMID 抓取指定论文

```bash
python metaweb.py auto --pmid 38912345 38967890
```

### 本地预览

```bash
python serve.py
# 打开浏览器访问 http://localhost:8089
```

## 使用方法

本项目提供统一的命令行工具 `metaweb.py`，支持以下子命令：

### `python metaweb.py set` - 设置/查看关键词

```bash
python metaweb.py set --term keyword1 keyword2 ...   # 设置搜索关键词
python metaweb.py set --check                        # 查看当前关键词
```

### `python metaweb.py fetch` - 抓取文献

支持三种模式：按日期、按日期范围、按 PMID 号。

#### 按日期抓取

```bash
python metaweb.py fetch                    # 默认：抓取今天到昨天（1天）
python metaweb.py fetch --days 7           # 抓取最近 7 天
python metaweb.py fetch --date 2026-05-05  # 抓取指定日期往回 1 天
python metaweb.py fetch --date 2026-05-05 --days-back 14  # 指定日期往前 14 天
```

#### 按日期范围抓取

```bash
python metaweb.py fetch --start-date 2026-04-01 --end-date 2026-04-30  # 指定范围
python metaweb.py fetch --start-date 2026-04-01                        # 从指定日期到今天
```

#### 按 PMID 号抓取

```bash
python metaweb.py fetch --pmid 38912345                            # 抓取单篇
python metaweb.py fetch --pmid 38912345 38967890 38911111          # 抓取多篇
python metaweb.py fetch --pmid 38912345 --date 2026-05-01          # 保存到指定日期
```

#### fetch 参数一览

| 参数 | 说明 | 示例 |
|------|------|------|
| `--days N` | 从今天往前搜索 N 天 | `--days 7` |
| `--date YYYY-MM-DD` | 指定目标日期（默认今天） | `--date 2026-05-05` |
| `--days-back N` | 从目标日期往前搜索天数（默认 1） | `--days-back 14` |
| `--start-date YYYY-MM-DD` | 日期范围起始 | `--start-date 2026-04-01` |
| `--end-date YYYY-MM-DD` | 日期范围结束（默认今天） | `--end-date 2026-04-30` |
| `--pmid PMID [...]` | 按 PMID 号直接抓取（可多个） | `--pmid 38912345` |

> **优先级**：`--pmid` > `--start-date/--end-date` > `--date/--days-back` > `--days`

### `python metaweb.py summarize` - 生成 AI 摘要

```bash
python metaweb.py summarize                     # 为所有未生成摘要的论文生成摘要
python metaweb.py summarize --date 2026-05-05   # 为指定日期的论文生成摘要
python metaweb.py summarize --all               # 处理所有 daily JSON 文件
python metaweb.py summarize --all --force       # 强制重新生成所有摘要
```

### `python metaweb.py build` - 整合数据

```bash
python metaweb.py build    # 整合所有 daily JSON 到 web/data.json
```

### `python metaweb.py auto` - 自动运行（抓取 + 摘要 + 整合）

`auto` 命令支持与 `fetch` 相同的所有参数，自动执行完整流水线：

```bash
python metaweb.py auto --days 7                                          # 最近 7 天完整流程
python metaweb.py auto --start-date 2026-04-01 --end-date 2026-04-30    # 日期范围完整流程
python metaweb.py auto --pmid 38912345 38967890                          # 按 PMID 完整流程
python metaweb.py auto --days 7 --force                                  # 强制重新生成摘要
```

### `python metaweb.py daily` - 每日自动化运行

```bash
python metaweb.py daily    # 执行每日更新（自动检测缺失的日期并补全）
```

### `python metaweb.py publish` - 本地更新并发布

```bash
python metaweb.py publish              # 更新 + push GitHub + scp 服务器
python metaweb.py publish --no-update  # 只发布现有数据
python metaweb.py publish --dry-run    # 检查部署配置
```

完整说明见 [本地每日更新并发布](#本地每日更新并发布推荐)。

### `python metaweb.py fetch-journals` - 期刊最新论文

按 `data/journals_sources.tsv` 中的期刊名单，从 Europe PMC（主）和 OpenAlex（补量）抓取最新论文。

```bash
python metaweb.py fetch-journals --days 7              # 最近 7 天
python metaweb.py fetch-journals --start-date 2026-10-24 --end-date 2026-11-23
python metaweb.py fetch-journals --days 7 --dry-run    # 只看命中，不写文件
```

期刊名单格式（Tab 分隔，首行表头）：

```tsv
name	issn	eissn	preprint	enabled	priority	note
Nature	0028-0836	1476-4687	0	1	1	nature.com
```

### `python metaweb.py fetch-preprints` - 预印本

```bash
python metaweb.py fetch-preprints --days 3             # bioRxiv + medRxiv
python metaweb.py fetch-preprints --server biorxiv --days 7 --dry-run
```

预印本以 DOI 作为唯一标识，前端显示“预印本”标记并跳转 DOI；已有正式版的预印本默认不收录。

### `python metaweb.py classify-scope` - 医学主题范围分类

对文献做 `medical / bioinformatics_method / non_medical` 三分类，产出排除清单与复核表。

```bash
python metaweb.py classify-scope --all --workers 6     # 全量分类
python metaweb.py classify-scope --date 2026-11-23 --apply-daily
python metaweb.py classify-scope --materialize-only    # 复用缓存，只写排除清单
```

人工改判写入 `data/scope_overrides.json`，格式：

```json
{"pmid:123456": {"decision": "keep", "category": "medical", "reason": "人工复核"}}
```

### `python metaweb.py scope-purge` / `scope-audit` - 物理清除与审计

```bash
python metaweb.py scope-purge --dry-run                # 统计将删除多少
python metaweb.py scope-purge --apply --backup         # 从 web + daily 物理删除
python metaweb.py build
python metaweb.py scope-audit --verify                 # 断言 0 残留
```

### `python metaweb.py backfill-meta` - 回填 DOI

为历史 PubMed 记录回填 PMID→DOI 映射，写入 `data/pmid_doi_map.json`。

```bash
python metaweb.py backfill-meta --limit 100 --dry-run
python metaweb.py backfill-meta
```

## 本地预览

```bash
# 启动本地预览服务器（端口 8089）
python serve.py

# 在浏览器中打开
# http://localhost:8089
```

## 本地每日更新并发布（推荐）

服务器 IP 无法访问 PubMed 时，改为在本地完成抓取/摘要/构建，然后同时推送 GitHub 并用 `scp` 更新服务器。

### 一次性配置

1. **授权本地 SSH 公钥**（只需一次，会提示服务器密码）：

```bash
ssh-copy-id seubiomed
ssh seubiomed 'test -w /home/yinhm/web/meta.seubiomed.com/web && echo OK'
```

2. **在 `config.env` 中确认部署配置**（该文件已被 gitignore）：

```ini
DEPLOY_SSH_ALIAS=seubiomed
DEPLOY_PATH=/home/yinhm/web/meta.seubiomed.com/web
SITE_URL=https://meta.seubiomed.com/
```

如果不用 SSH 别名，也可以配置：

```ini
DEPLOY_HOST=seubiomed.com
DEPLOY_USER=yinhm
DEPLOY_PORT=22
DEPLOY_PATH=/home/yinhm/web/meta.seubiomed.com/web
```

### 每天运行

```bash
python metaweb.py publish
```

它按顺序执行：

1. `metaweb.py daily`：PubMed / 期刊 / 预印本抓取 → 分类 → 摘要 → 构建
2. `metaweb.py build`：发布 `web/logs/daily.log` 并重建前端数据
3. `metaweb.py scope-audit --verify`：确认排除项无残留
4. `git add --force` 每日数据 → commit → `fetch` → `rebase origin/main` → `push`
5. `scp -r web/. seubiomed:<DEPLOY_PATH>/`：更新服务器静态文件
6. 推送成功后才部署，避免 GitHub 与服务器版本不一致

可选参数：

| 参数 | 作用 |
|------|------|
| `--dry-run` | 只检查 SSH/部署配置，不执行更新与发布 |
| `--no-update` | 只发布现有数据，不重新抓取 |
| `--no-push` | 跳过 GitHub 推送 |
| `--no-deploy` | 跳过服务器 scp |
| `--message "..."` | 自定义 commit 信息 |

> `publish` 会拒绝工作区中的未提交代码改动；请先把代码改动单独提交，再运行每日发布。
> GitHub Actions 已关闭；访客数据不会自动刷新，需要时按下方“访客数据”手动生成。

### Windows 任务计划程序

项目根目录提供 `publish.bat`（自动 `cd` 到项目目录并运行 publish）：

```bat
schtasks /Create /F /TN "MetaLitPublish" /SC DAILY /ST 20:00 ^
  /TR "D:\project\meta-seubiomed\publish.bat"
```

也可以双击 `publish.bat` 手动发布。输出追加到 `logs\publish.log`。

注意：任务计划程序请使用与当前相同的 Windows 用户运行，确保 Git 凭据和 `~/.ssh/id_ed25519` 可用。

## GitHub Actions 已关闭

本项目不再使用 GitHub Actions 做日常更新。两个工作流已重命名并停用：

- `.github/workflows/daily.yml.disabled`
- `.github/workflows/visitors.yml.disabled`

原因：服务器 IP 无法访问 PubMed；每日更新改由本地 `metaweb.py publish` 完成，避免与 GitHub 定时任务重复提交。

### 访客数据

访客地图数据不再自动刷新，`web/visitors.json` 会保留最后一次生成的内容（当前为示例数据）。

如需真实数据，可在本地生成后发布：

```bash
pip install geoip2
python scripts/gen_visitors.py \
  --log /path/to/nginx/access.log \
  --mmdb /path/to/GeoLite2-City.mmdb \
  --days 90 \
  --out web/visitors.json
python metaweb.py publish --no-update --no-push
```

输出包含 7/30/90/全部四个时间窗口与每日访问序列。若想恢复 GitHub 上的访客工作流，将 `visitors.yml.disabled` 改回 `visitors.yml` 即可，但请注意它会与本地发布并行提交 `visitors.json`。

若要彻底关闭本仓库的 Actions 功能，可在 GitHub 仓库 **Settings → Actions → General → Disable actions** 中操作。

## 服务器部署（Nginx）

`web/` 是纯静态目录；`publish` 会用 `scp` 增量覆盖其中的文件。服务器上的 `web/logs` 是指向 `../logs` 的软链接，发布脚本只更新日志文件，不会替换该软链接。

#### Nginx 配置示例

```nginx
server {
    listen 80;
    server_name meta.seubiomed.com;

    root /home/yinhm/web/meta.seubiomed.com/web;
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }
}
```

## 高级用法

### 修改搜索关键词

```bash
# 推荐方式：使用命令行
python metaweb.py set --term keyword1 keyword2 keyword3

# 或直接编辑 config.env 中的 SEARCH_KEYWORDS 字段
# SEARCH_KEYWORDS=metagenome,metagenomic,microbiome
```

### 修改排除关键词

编辑 `scripts/fetch_pubmed.py` 中的 `EXCLUDE_KEYWORDS` 和 `SAFE_WORDS` 列表。

### 手动抓取历史数据

```bash
# 抓取指定月份的数据（用于补录历史数据）
python scripts/fetch_history_months.py --months 2026-01 2026-02
```

### 清理不匹配的期刊

```bash
# 删除期刊信息表中不存在的期刊的论文
python scripts/clean_unmatched_journals.py
```

## 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 贡献

欢迎提交 Issue 和 Pull Request！

## 联系方式

- 作者：yin-huamin
- 邮箱：yinhm17@126.com
- GitHub：https://github.com/yin-huamin/meta.seubiomed.com

---

**注意**：本项目的 `.gitignore` 已配置为不上传敏感信息（API Key 等）。Fork 或 Clone 后，请先创建自己的 `config.env` 文件。
