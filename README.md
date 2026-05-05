# 宏基因组文献追踪系统 (Meta-SeuBiomed)

> 每日自动从 PubMed 抓取宏基因组/微生物组相关文献，AI 生成中文摘要，静态网页展示。

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
- [自动化部署](#自动化部署)
- [高级用法](#高级用法)
- [许可证](#许可证)

---

## 项目简介

Meta-SeuBiomed 是一个自动化的宏基因组/微生物组文献追踪系统。它能够：

- 每日自动从 PubMed 搜索最新的宏基因组/微生物组相关文献
- 使用 AI（支持 OpenAI / DeepSeek / 本地 Ollama）生成中文摘要
- 将文献数据整合为静态 JSON 文件，供前端展示
- 提供简洁的 Web 界面，支持搜索、筛选、排序等功能

本项目纯 Python 标准库实现，**无任何第三方依赖**，轻量、易部署。

## 功能特性

- **自动抓取**：基于 PubMed E-utilities API，支持按日期、日期范围、PMID 抓取
- **AI 摘要**：调用 LLM 生成中文摘要、创新点、局限性等字段
- **期刊过滤**：基于期刊影响因子（IF）、JCR 分区、中科院分区自动过滤低质量期刊
- **内容过滤**：自动排除家畜、家禽、食品发酵、环境工程等非医学相关文献
- **关键词自定义**：通过命令行快速修改搜索关键词，无需编辑代码
- **静态前端**：纯 HTML+CSS+JS 实现，无框架依赖，可直接部署到任何 Web 服务器
- **双视图**：支持表格视图（桌面端）和卡片视图（移动端）
- **搜索高亮**：搜索关键词在结果中高亮显示

## 项目结构

```
meta-seubiomed/
├── metaweb.py              # 统一命令行工具
├── scripts/
│   ├── fetch_pubmed.py      # PubMed 搜索（核心）
│   ├── summarize_papers.py  # AI 摘要生成（核心）
│   ├── build_data.py        # 数据整合（核心）
│   ├── daily_update.py      # 每日更新入口
│   └── auto_build_listener.py # 自动构建监听器
├── web/
│   ├── index.html           # 前端页面
│   └── assets/             # 资源目录（微信支付二维码等）
├── serve.py                 # 本地预览服务器
├── journal_info.tsv         # 期刊信息表（IF/JCR/中科院分区）
├── config.env.example       # 配置文件模板
├── requirements.txt         # Python 依赖（无第三方依赖）
├── README.md                # 项目文档
└── LICENSE                  # MIT 许可证
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

## 本地预览

```bash
# 启动本地预览服务器（端口 8089）
python serve.py

# 在浏览器中打开
# http://localhost:8089
```

## 自动化部署

### Linux/macOS - 使用 crontab

```bash
# 编辑 crontab
crontab -e

# 添加以下行（每天早 8:00 运行）
0 8 * * * cd /path/to/meta-seubiomed && python metaweb.py daily >> logs/daily.log 2>&1
```

### Windows - 使用任务计划程序

```powershell
$action = New-ScheduledTaskAction `
    -Execute "python" `
    -Argument "d:\project\meta-seubiomed\metaweb.py daily" `
    -WorkingDirectory "d:\project\meta-seubiomed"

$trigger = New-ScheduledTaskTrigger -Daily -At "08:00"

Register-ScheduledTask -TaskName "MetaLitDaily" -Action $action -Trigger $trigger
```

### 部署到 Web 服务器

1. 将 `web/` 目录部署到 Web 服务器（如 Nginx）
2. 配置 `metaweb.py daily` 为定时任务
3. 每次定时任务运行后，`web/data.json` 会自动更新

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
