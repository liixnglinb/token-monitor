# -*- coding: utf-8 -*-
"""查询 GitHub Actions 运行状态与 Release 产物（走 gh CLI，避开被阻断的 git 443）。

用法：python check_ci.py [owner/repo]
"""
from __future__ import annotations

import subprocess
import sys

repo = sys.argv[1] if len(sys.argv) > 1 else "liixnglinb/token-monitor"


def gh(*args: str) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    return (result.stdout or result.stderr or "").strip()


print("== 最近 workflow 运行 ==")
print(gh("api", f"repos/{repo}/actions/runs?per_page=3",
         "--jq", r'.workflow_runs[] | "\(.name) | \(.head_branch) | \(.status) | \(.conclusion // "-") | \(.created_at)"'))

print("\n== 最近 release ==")
print(gh("api", f"repos/{repo}/releases?per_page=3",
         "--jq", r'.[] | "\(.tag_name) | \(.published_at // "未发布") | assets=\(.assets | length)"'))

print("\n== v1.9.13 产物 ==")
print(gh("api", f"repos/{repo}/releases/tags/v1.9.13",
         "--jq", r'.assets[]? | "\(.name)  \(.size) bytes"') or "（还没有产物）")

print("\n== 最新 tag ==")
print(gh("api", f"repos/{repo}/tags?per_page=3", "--jq", ".[].name"))
