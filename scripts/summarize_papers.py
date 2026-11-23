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
from concurrent.futures import ThreadPoolExecutor, as_completed
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
                # 不覆盖显式传入的环境变量（便于临时切换模型/参数）
                os.environ.setdefault(k.strip(), v.strip())

# ── LLM 配置（优先读取环境变量）──
# 支持 OpenAI 兼容接口（如 OpenAI / DeepSeek / 本地 Ollama 等）
LLM_API_URL  = os.environ.get("LLM_API_URL",  "https://api.openai.com/v1/chat/completions")
LLM_API_KEY  = os.environ.get("LLM_API_KEY",  "")
LLM_MODEL    = os.environ.get("LLM_MODEL",    "gpt-4o-mini")
LLM_TIMEOUT  = int(os.environ.get("LLM_TIMEOUT", "60"))
# 推理模型会先消耗 reasoning tokens，预算过小会导致 content 为空
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "4096"))
BATCH_DELAY  = float(os.environ.get("LLM_DELAY", "1.5"))   # 每篇之间的间隔（秒）

AI_FIELDS  = ["summary_zh", "innovation", "limitation",
              "study_object", "disease", "sample_size"]
PENDING_MARK = "（待生成）"

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
    """调用 LLM，返回解析后的字段 dict；失败时抛出异常，由调用方决定是否重试。"""
    if not LLM_API_KEY:
        raise RuntimeError("未配置 LLM_API_KEY")

    user_msg = f"Title: {title}\n\nAbstract: {abstract or '（无摘要）'}"

    payload = json.dumps({
        "model":    LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        "temperature": 0.2,
        "max_tokens":  LLM_MAX_TOKENS,
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

    with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
        body = json.loads(resp.read())

    message = body["choices"][0]["message"]
    content = (message.get("content") or "").strip()
    if not content:
        reasoning = message.get("reasoning_content") or ""
        raise ValueError(
            f"LLM 返回空内容（reasoning {len(reasoning)} 字符，"
            f"可能 max_tokens={LLM_MAX_TOKENS} 不足）"
        )

    # 提取 JSON（有时模型会在前后加 ```json ... ``` 或说明文字）
    if "```" in content:
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    start, end = content.find("{"), content.rfind("}")
    if start != -1 and end > start:
        content = content[start:end + 1]

    # strict=False：容忍字符串内未转义的控制字符（模型偶尔产生换行）
    result = json.loads(content, strict=False)
    missing = [f for f in AI_FIELDS if not str(result.get(f) or "").strip()]
    if missing:
        raise ValueError(f"LLM 返回缺少字段: {', '.join(missing)}")
    return {f: str(result[f]).strip() for f in AI_FIELDS}


def _empty_ai() -> dict:
    return {f: PENDING_MARK for f in AI_FIELDS}


def _is_annotated(rec: dict) -> bool:
    """AI 字段全部非空且非占位符，才算真正注释完成。

    历史上调用失败也会写入 ai_done=True + 占位符，因此不能只看该标记。
    """
    if not rec.get("ai_done"):
        return False
    return all(
        str(rec.get(f) or "").strip() and PENDING_MARK not in str(rec.get(f))
        for f in AI_FIELDS
    )


# ──────────────────────────── 主流程 ──────────────────────────────

def process_file(json_path: Path, force: bool = False, workers: int = 1):
    """处理单个 daily JSON 文件，每批处理后立即保存"""
    with open(json_path, encoding="utf-8") as fh:
        records = json.load(fh)

    def save():
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(records, fh, ensure_ascii=False, indent=2)

    pending = [
        i for i, rec in enumerate(records)
        if (force or not _is_annotated(rec))
        and rec.get("scope_decision") != "exclude"
    ]
    if not pending:
        log.info(f"  ○ {json_path.name} 无需更新")
        return

    def annotate(i: int):
        rec = records[i]
        log.info(f"  [{i+1}/{len(records)}] PMID {rec.get('pmid','?')} | {rec.get('title','')[:60]}")
        return i, call_llm(rec.get("title", ""), rec.get("abstract", ""))

    def apply(i: int, ai_result: dict):
        records[i].update(ai_result)
        records[i]["ai_done"] = True

    def apply_error(i: int, exc: Exception):
        # 失败时保持 ai_done=False，下次运行会继续重试
        log.error(f"  处理 PMID {records[i].get('pmid','?')} 出错: {exc}")
        records[i].update(_empty_ai())
        records[i]["ai_done"] = False

    if workers <= 1:
        for i in pending:
            try:
                _, ai_result = annotate(i)
                apply(i, ai_result)
            except Exception as exc:
                apply_error(i, exc)
            save()
            time.sleep(BATCH_DELAY)
    else:
        log.info(f"  并发 {workers} 线程处理 {len(pending)} 篇待注释记录")
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(annotate, i): i for i in pending}
            for fut in as_completed(futures):
                i = futures[fut]
                try:
                    _, ai_result = fut.result()
                    apply(i, ai_result)
                except Exception as exc:
                    apply_error(i, exc)
                done += 1
                if done % 20 == 0 or done == len(pending):
                    save()
                    log.info(f"  进度 {done}/{len(pending)}")

    save()
    log.info(f"  ✓ 已更新 {json_path.name}（共 {len(records)} 篇，本次处理 {len(pending)} 篇）")


def run(target_date: str = None, all_files: bool = False,
        force: bool = False, workers: int = 1):
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
        process_file(f, force=force, workers=workers)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI 摘要：补全论文中文总结字段")
    parser.add_argument("--date",  default=None, help="目标日期 YYYY-MM-DD")
    parser.add_argument("--all",   action="store_true", help="处理所有 daily JSON 文件")
    parser.add_argument("--force", action="store_true", help="强制重新生成已有 AI 摘要")
    parser.add_argument("--workers", type=int, default=1,
                        help="并发线程数（默认 1；批量修复建议 6-8）")
    args = parser.parse_args()
    run(target_date=args.date, all_files=args.all, force=args.force,
        workers=args.workers)
