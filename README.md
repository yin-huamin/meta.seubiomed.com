# 宏基因组文献追踪系统

> 每日自动从 PubMed 抓取宏基因组/微生物组相关文献，AI 生成中文摘要，静态网页展示。

## 项目结构

```
meta-seubiomed/
├── scripts/
│   ├── fetch_pubmed.py      # PubMed 搜索 & 下载
│   ├── summarize_papers.py  # AI 中文摘要生成
│   ├── build_data.py        # 整合 → web/data.json
│   ├── daily_update.py      # 每日一键更新（fetch+summarize+build）
│   └── init_history.py      # 一次性拉取历史数据
├── data/
│   └── daily/               # 按日期存储的 JSON 文件（YYYY-MM-DD.json）
├── web/
│   ├── index.html           # 前端页面（极简风格）
│   └── data.json            # 整合后的前端数据（自动生成）
├── serve.py                 # 本地预览服务器
├── config.env.example       # 配置文件模板
└── README.md
```

## 快速开始

### 1. 配置环境变量

```bash
cp config.env.example config.env
# 编辑 config.env，填写 LLM_API_KEY
```

Windows PowerShell:
```powershell
$env:LLM_API_KEY = "sk-your-key-here"
$env:LLM_MODEL   = "gpt-4o-mini"
# 如用 DeepSeek：
# $env:LLM_API_URL = "https://api.deepseek.com/v1/chat/completions"
# $env:LLM_MODEL   = "deepseek-chat"
```

### 2. 初始化历史数据（首次运行）

```bash
python scripts/init_history.py --days 7
```

### 3. 本地预览

```bash
python serve.py
# 打开 http://localhost:8088
```

### 4. 每日手动更新

```bash
python scripts/daily_update.py
```

## 自动化设置

### Windows 任务计划程序（每天早 8:00）

```powershell
$action  = New-ScheduledTaskAction -Execute "python" -Argument "d:\project\meta-seubiomed\scripts\daily_update.py" -WorkingDirectory "d:\project\meta-seubiomed"
$trigger = New-ScheduledTaskTrigger -Daily -At "08:00"
Register-ScheduledTask -TaskName "MetaLitDaily" -Action $action -Trigger $trigger -RunLevel Highest
```

### Linux/macOS crontab

```cron
0 8 * * * cd /path/to/meta-seubiomed && LLM_API_KEY=sk-xxx python scripts/daily_update.py >> logs/daily.log 2>&1
```

## LLM 配置说明

| 服务 | API URL | 模型 | 备注 |
|------|---------|------|------|
| OpenAI | `https://api.openai.com/v1/chat/completions` | `gpt-4o-mini` | 默认 |
| DeepSeek | `https://api.deepseek.com/v1/chat/completions` | `deepseek-chat` | 更便宜 |
| 本地 Ollama | `http://localhost:11434/v1/chat/completions` | `qwen2.5` | 免费 |

## 关键词

目前使用三个关键词：`metagenome`, `metagenomic`, `microbiom`（自动匹配 microbiome/microbiomics）

修改方式：编辑 `scripts/fetch_pubmed.py` 中的 `KEYWORDS` 列表。

## 许可

MIT License
