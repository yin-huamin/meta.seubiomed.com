#!/usr/bin/env python3
"""
测试 LLM API 连接
"""

import os
import json
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# 加载 .env
dotenv_path = BASE_DIR / "config.env"
if dotenv_path.exists():
    with open(dotenv_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

LLM_API_URL = os.environ.get("LLM_API_URL", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "")

print("[*] 配置信息：")
print(f"   API URL: {LLM_API_URL}")
print(f"   Model: {LLM_MODEL}")
print(f"   API Key: {LLM_API_KEY[:10]}..." if LLM_API_KEY else "   [!] API Key 未配置！")
print()

if not LLM_API_KEY:
    print("[X] 错误：LLM_API_KEY 环境变量未设置")
    print()
    print("请选择一种方式配置：")
    print()
    print("方式1：编辑 config.env 文件")
    print("  LLM_API_URL=https://api.openai.com/v1/chat/completions")
    print("  LLM_API_KEY=sk-你的key")
    print("  LLM_MODEL=gpt-4o-mini")
    print()
    print("方式2：使用环境变量（PowerShell）")
    print("  $env:LLM_API_KEY = 'sk-你的key'")
    print("  $env:LLM_MODEL = 'gpt-4o-mini'")
    exit(1)

print("[*] 测试 API 连接...")
print()

payload = json.dumps({
    "model": LLM_MODEL,
    "messages": [
        {"role": "system", "content": "你是一个测试助手。"},
        {"role": "user", "content": "请回复 'API 连接成功！'（不要其他文字）"},
    ],
    "max_tokens": 20,
    "temperature": 0.1,
}).encode("utf-8")

req = urllib.request.Request(
    LLM_API_URL,
    data=payload,
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}",
    },
    method="POST",
)

try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read())
    reply = body["choices"][0]["message"]["content"].strip()
    print(f"[OK] {reply}")
    print()
    print(f"消耗 token: {body.get('usage', {}).get('total_tokens', 'N/A')}")
except Exception as e:
    print(f"[ERROR] API 调用失败: {e}")
    print()
    print("请检查：")
    print("1. API URL 是否正确（确保包含 /v1/chat/completions）")
    print("2. API Key 是否有效")
    print("3. 模型名称是否正确")
    exit(1)
