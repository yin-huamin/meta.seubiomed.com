#!/usr/bin/env python3
"""
AI 论文摘要脚本
对 fetch_pubmed.py 抓取的论文调用 LLM，补全：
  summary_zh / innovation / limitation / study_object / disease / sample_size
"""

import os
import json
import time
import logging
import argparse
import urllib.request
import urllib.parse
from pathlib import Path

# ──────────────────────────── 配置区 ──────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DAILY_DIR = BASE_DIR / "data" / "daily"

# ── 加载 .env 文件 ──
dotenv_path = BASE_DIR / "config.env"
if dotenv_path.exists():
    with open(dotenv_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

# ── LLM 配置（优先读取环境变量）──
# 支持 OpenAI 兼容接口（如 OpenAI / DeepSeek / 本地 Ollama 等）
LLM_API_URL  = os.environ.get("LLM_API_URL",  "https://api.openai.com/v1/chat/completions")
LLM_API_KEY  = os.environ.get("LLM_API_KEY",  "")
LLM_MODEL    = os.environ.get("LLM_MODEL",    "gpt-4o-mini")
LLM_TIMEOUT  = int(os.environ.get("LLM_TIMEOUT", "60"))
BATCH_DELAY  = float(os.environ.get("LLM_DELAY", "1.5"))   # 每篇之间的间隔（秒）

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ──────────────────────────── Prompt ──────────────────────────────

SYSTEM_PROMPT = """你是宏基因组/微生物组论文信息抽取助手。

仅根据给定的英文标题和摘要抽取信息，不得使用摘要外信息，不得推测。
全部字段值使用中文。
只返回 1 个合法 JSON 对象，不要输出解释、markdown 或代码块。

规则：
- 未明确提及填“未描述”
- 未涉及疾病填“无”
- summary_zh：一句话概括研究目的、方法和结论，不超过60字
- innovation：1-3条，仅写摘要明确体现的创新，用“ | ”分隔
- limitation：1-2条，仅写摘要明确提及或可直接判断的限制；否则填“未描述”
- study_object：优先提取“宿主/环境 + 样本类型 + 技术类型”
- disease：仅填写摘要中明确出现的疾病、健康状态或宿主表型；否则填“无”
- sample_size：仅提取明确数字样本量，如“n=120”“3个队列共200例”；否则填“未描述”

返回：
{
  "summary_zh": "",
  "innovation": "",
  "limitation": "",
  "study_object": "",
  "disease": "",
  "sample_size": ""
}"""


def call_llm(title: str, abstract: str) -> dict:
    """调用 LLM，返回解析后的字段 dict；失败时返回占位 dict"""
    if not LLM_API_KEY:
        log.warning("未配置 LLM_API_KEY，跳过 AI 摘要")
        return _empty_ai()

    user_msg = f"Title: {title}\n\nAbstract: {abstract or '（无摘要）'}"

    payload = json.dumps({
        "model":    LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        "temperature": 0.2,
        "max_tokens":  600,
    }).encode("utf-8")

    req = urllib.request.Request(
        LLM_API_URL,
        data=payload,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {LLM_API_KEY}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
            body = json.loads(resp.read())
        content = body["choices"][0]["message"]["content"].strip()
        # 提取 JSON（有时模型会在前后加 ```json ... ```）
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        result = json.loads(content)
        return result
    except json.JSONDecodeError as e:
        log.warning(f"LLM 返回 JSON 解析失败: {e}")
        return _empty_ai()
    except Exception as e:
        log.warning(f"LLM 调用失败: {e}")
        return _empty_ai()


def _empty_ai() -> dict:
    return {
        "summary_zh":   "（待生成）",
        "innovation":   "（待生成）",
        "limitation":   "（待生成）",
        "study_object": "（待生成）",
        "disease":      "（待生成）",
        "sample_size":  "（待生成）",
    }


# ──────────────────────────── 主流程 ──────────────────────────────

def process_file(json_path: Path, force: bool = False):
    """处理单个 daily JSON 文件"""
    with open(json_path, encoding="utf-8") as fh:
        records = json.load(fh)

    updated = False
    for i, rec in enumerate(records):
        if rec.get("ai_done") and not force:
            continue

        log.info(f"  [{i+1}/{len(records)}] PMID {rec.get('pmid','?')} | {rec.get('title','')[:60]}")
        ai_result = call_llm(rec.get("title", ""), rec.get("abstract", ""))
        rec.update(ai_result)
        rec["ai_done"] = True
        updated = True
        time.sleep(BATCH_DELAY)

    if updated:
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(records, fh, ensure_ascii=False, indent=2)
        log.info(f"  ✓ 已更新 {json_path.name}")
    else:
        log.info(f"  ○ {json_path.name} 无需更新")


def run(target_date: str = None, all_files: bool = False, force: bool = False):
    files = []
    if all_files:
        files = sorted(DAILY_DIR.glob("*.json"))
    elif target_date:
        f = DAILY_DIR / f"{target_date}.json"
        if f.exists():
            files = [f]
        else:
            log.warning(f"文件不存在: {f}")
            return
    else:
        # 默认处理最新的文件
        candidates = sorted(DAILY_DIR.glob("*.json"), reverse=True)
        files = candidates[:1]

    log.info(f"共需处理 {len(files)} 个文件")
    for f in files:
        log.info(f"处理: {f.name}")
        process_file(f, force=force)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI 摘要：补全论文中文总结字段")
    parser.add_argument("--date",  default=None, help="目标日期 YYYY-MM-DD")
    parser.add_argument("--all",   action="store_true", help="处理所有 daily JSON 文件")
    parser.add_argument("--force", action="store_true", help="强制重新生成已有 AI 摘要")
    args = parser.parse_args()
    run(target_date=args.date, all_files=args.all, force=args.force)
