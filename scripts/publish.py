#!/usr/bin/env python3
"""本地发布：每日更新 → 提交推送 GitHub → scp 到服务器。

用法：
    python metaweb.py publish                 # 更新 + push + scp
    python metaweb.py publish --no-update     # 只发布现有数据
    python metaweb.py publish --dry-run       # 只检查配置，不执行
    python metaweb.py publish --no-push       # 跳过 GitHub
    python metaweb.py publish --no-deploy     # 跳过服务器

SSH 配置（config.env，勿提交）：
    DEPLOY_SSH_ALIAS=seubiomed
    DEPLOY_PATH=/home/yinhm/web/meta.seubiomed.com/web
    # 或者不用 alias：
    # DEPLOY_HOST=seubiomed.com
    # DEPLOY_USER=yinhm
    # DEPLOY_PORT=22
"""

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))

import common

common.load_env()

GENERATED_ROOTS = (
    "data/",
    "web/data/",
    "web/logs/",
    "web/stats.json",
    "web/memory.json",
    "logs/daily.log",
)
ADD_PATHS = [
    "data/daily",
    "data/excluded_pmids.json",
    "data/scope_classification.json",
    "data/scope_overrides.json",
    "data/scope_review.tsv",
    "data/purge_state.json",
    "data/journals_sources.tsv",
    "data/pmid_doi_map.json",
    "logs/daily.log",
    "web/data.json",
    "web/data",
    "web/logs",
    "web/memory.json",
    "web/stats.json",
]


def log(msg: str):
    print(f"[publish] {msg}", flush=True)


def run(cmd, check=True, capture=False):
    kwargs = dict(cwd=BASE_DIR, text=True, encoding="utf-8", errors="replace")
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.STDOUT
    result = subprocess.run(cmd, **kwargs)
    if check and result.returncode != 0:
        raise RuntimeError(f"命令失败 ({result.returncode}): {' '.join(cmd)}")
    return result


def run_logged(cmd, log_path: Path, mode="w"):
    """同时输出到控制台并写入日志文件。"""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, mode, encoding="utf-8") as fh:
        proc = subprocess.Popen(
            cmd, cwd=BASE_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace")
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="", flush=True)
            fh.write(line)
            fh.flush()
        return proc.wait()


def git(*args, check=True, capture=False):
    return run(["git", *args], check=check, capture=capture)


def _paths_from_status():
    out = git("status", "--porcelain", capture=True).stdout or ""
    for line in out.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        yield path


def ensure_clean_code():
    """除生成数据外，工作区必须干净；代码改动请先单独提交。"""
    allowed = tuple(GENERATED_ROOTS)
    dirty = [p for p in _paths_from_status()
             if not p.startswith(allowed) and not p.endswith(".log")]
    if dirty:
        log("检测到未提交的代码/文件改动：")
        for p in dirty:
            log(f"  - {p}")
        raise RuntimeError("请先提交这些改动，再运行 publish（避免发布与代码不一致）")
    for marker in (".git/rebase-merge", ".git/rebase-apply", ".git/MERGE_HEAD"):
        if (BASE_DIR / marker).exists():
            raise RuntimeError(f"仓库正处于合并/变基状态：{marker}，请先处理")


def check_branch():
    branch = git("branch", "--show-current", capture=True).stdout.strip()
    if branch != "main":
        raise RuntimeError(f"当前分支是 {branch or '(detached)'}，请切换到 main")


def update():
    log("步骤 1/4：本地每日更新")
    log_file = BASE_DIR / "logs" / "daily.log"
    code = run_logged([sys.executable, str(BASE_DIR / "metaweb.py"), "daily"],
                      log_file, mode="w")
    if code != 0:
        raise RuntimeError(f"metaweb.py daily 退出码 {code}")

    log("重新构建并发布爬取日志")
    code = run_logged([sys.executable, str(BASE_DIR / "metaweb.py"), "build"],
                      log_file, mode="a")
    if code != 0:
        raise RuntimeError(f"metaweb.py build 退出码 {code}")

    log("审计排除项")
    code = run_logged([sys.executable, str(BASE_DIR / "metaweb.py"),
                       "scope-audit", "--verify"], log_file, mode="a")
    if code != 0:
        raise RuntimeError("排除项审计失败，已停止发布")


def stage_and_commit(message: str) -> bool:
    log("步骤 2/4：提交每日数据")
    staged_any = False
    for rel in ADD_PATHS:
        path = BASE_DIR / rel
        if not path.exists():
            continue
        git("add", "--force", "--", rel)
        staged_any = True
    if not staged_any:
        log("没有可提交的数据文件")
        return False

    diff = git("diff", "--cached", "--quiet", check=False)
    if diff.returncode == 0:
        log("数据无变化，跳过提交")
        return False

    git("commit", "-m", message)
    log(f"已提交：{message}")
    return True


def sync_and_push():
    log("步骤 3/4：同步远程并推送 GitHub")
    git("fetch", "origin", "main")
    behind = int(git("rev-list", "--count", "HEAD..origin/main",
                     capture=True).stdout.strip() or "0")
    if behind:
        log(f"远程领先 {behind} 个提交，执行 rebase")
        result = git("rebase", "origin/main", check=False)
        if result.returncode != 0:
            git("rebase", "--abort", check=False)
            raise RuntimeError("rebase 冲突，已中止；请手动解决后重试")
    git("push", "origin", "main")
    log("GitHub 已更新")


def deploy_spec():
    alias = os.environ.get("DEPLOY_SSH_ALIAS", "").strip()
    path = os.environ.get("DEPLOY_PATH", "").strip()
    host = os.environ.get("DEPLOY_HOST", "").strip()
    user = os.environ.get("DEPLOY_USER", "").strip()
    port = os.environ.get("DEPLOY_PORT", "").strip()

    if not path:
        raise RuntimeError("config.env 缺少 DEPLOY_PATH")
    if alias:
        return alias, None, path
    if host:
        target = f"{user}@{host}" if user else host
        return target, (port or None), path
    raise RuntimeError("config.env 需要 DEPLOY_SSH_ALIAS 或 DEPLOY_HOST/DEPLOY_USER")


def deploy():
    log("步骤 4/4：scp 部署到服务器")
    target, port, remote_path = deploy_spec()
    ssh_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]
    if port:
        ssh_cmd += ["-p", port]
    ssh_cmd += [target, f"test -d {remote_path} && test -w {remote_path}"]
    result = subprocess.run(ssh_cmd, cwd=BASE_DIR)
    if result.returncode != 0:
        raise RuntimeError(
            "SSH 无法写入远程目录。请确认公钥已加入服务器，且 DEPLOY_PATH 正确。\n"
            "  一次授权：ssh-copy-id seubiomed\n"
            f"  检查路径：ssh seubiomed 'ls -ld {remote_path}'")

    scp_cmd = ["scp", "-r"]
    if port:
        scp_cmd += ["-P", port]
    scp_cmd += ["web/.", f"{target}:{remote_path}/"]
    result = subprocess.run(scp_cmd, cwd=BASE_DIR)
    if result.returncode != 0:
        raise RuntimeError("scp 部署失败")
    site = os.environ.get("SITE_URL", "https://meta.seubiomed.com/")
    log(f"服务器已更新：{site}")


def execute(no_update=False, no_push=False, no_deploy=False,
            dry_run=False, message=None):
    if dry_run:
        target, port, remote_path = deploy_spec()
        log(f"SSH 目标：{target}（端口 {port or '默认'}）")
        log(f"远程目录：{remote_path}")
        log("将执行：metaweb daily → build → audit → git commit/push → scp web/")
        return 0

    ensure_clean_code()
    check_branch()

    if not no_update:
        update()

    message = message or f"chore: 本地每日更新 {datetime.now():%Y-%m-%d %H:%M}"
    stage_and_commit(message)

    if not no_push:
        sync_and_push()

    if not no_deploy:
        deploy()

    log("全部完成")
    return 0


def main():
    parser = argparse.ArgumentParser(description="本地每日更新并发布到 GitHub 与服务器")
    parser.add_argument("--no-update", action="store_true", help="跳过每日抓取/摘要")
    parser.add_argument("--no-push", action="store_true", help="跳过 GitHub 推送")
    parser.add_argument("--no-deploy", action="store_true", help="跳过 scp 部署")
    parser.add_argument("--dry-run", action="store_true", help="只检查配置并打印步骤")
    parser.add_argument("--message", default=None, help="提交信息")
    args = parser.parse_args()
    return execute(args.no_update, args.no_push, args.no_deploy,
                   args.dry_run, args.message)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"失败：{exc}")
        sys.exit(1)
