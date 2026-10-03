# -*- coding: utf-8 -*-
"""比对"本机已安装的 exe"与"CI 发布的官方 exe"是否字节一致。

用法：python tools/compare_release_exe.py [tag]
"""
from __future__ import annotations

import hashlib
import pathlib
import subprocess
import sys
import tempfile
import urllib.request

REPO = "liixnglinb/token-monitor"
TAG = sys.argv[1] if len(sys.argv) > 1 else "v1.9.13"
INSTALLED = pathlib.Path(r"C:\Users\李星历\Desktop\token 统计\TokenMonitor\TokenMonitor.exe")


def gh(*args: str) -> str:
    out = subprocess.run(["gh", *args], capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    return out.strip()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


jq = '.assets[] | select(.name=="TokenMonitor.exe") | .browser_download_url'
url = gh("api", f"repos/{REPO}/releases/tags/{TAG}", "--jq", jq)
print("官方下载地址:", url)

tmp = pathlib.Path(tempfile.gettempdir()) / f"tm-official-{TAG}.exe"
with urllib.request.urlopen(url, timeout=600) as response, open(tmp, "wb") as handle:
    handle.write(response.read())
official = tmp.read_bytes()
installed = INSTALLED.read_bytes()

published = gh("api", f"repos/{REPO}/releases/tags/{TAG}",
               "--jq", '.assets[] | select(.name=="TokenMonitor.exe.sha256") | .browser_download_url')
if published:
    with urllib.request.urlopen(published, timeout=60) as response:
        print("发布的校验文件:", response.read().decode("utf-8", "replace").strip())

print(f"官方   {sha256(official)}  {len(official):,} 字节")
print(f"已安装 {sha256(installed)}  {len(installed):,} 字节")
print("结论：", "字节完全一致（本机装的就是 CI 官方包）" if official == installed else "不一致（本机是本地自建版本）")
