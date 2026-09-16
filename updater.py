# -*- coding: utf-8 -*-
"""自动更新 —— 对比 GitHub Releases，下载新版 exe 并自替换重启。

流程：/api/update → fetch_latest() 找到更新 → download_and_apply()
     下载新版到临时目录 → 写 update.bat（等待当前进程退出 → move 替换 → 重启）
     → server 1 秒后 os._exit(0) → bat 接管完成替换。
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.request

REPO = "liixnglinb/token-monitor"
EXE_NAME = "TokenMonitor.exe"
_UA = "TokenMonitor-Updater"


def _base():
    """返回 (只读资源目录, 可执行文件路径)。开发态可执行文件为 None。"""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS, sys.executable
    return os.path.dirname(os.path.abspath(__file__)), None


def local_version() -> str:
    base, _ = _base()
    try:
        with open(os.path.join(base, "version.txt"), encoding="utf-8") as f:
            return f.read().strip().lstrip("v") or "0.0.0"
    except OSError:
        return "0.0.0"


def _parse(v: str):
    return tuple(int(x) for x in v.strip().lstrip("v").split("."))


def is_newer(latest: str, local: str) -> bool:
    if not latest:
        return False
    try:
        return _parse(latest) > _parse(local)
    except ValueError:
        # 本地版本号非语义化（如开发构建 "dev"）：只要有正式发布就提示更新
        return local != latest


def fetch_latest(timeout: int = 8):
    """返回 (latest_version_without_v, assets)。404 时返回 ("", [])。"""
    url = f"https://api.github.com/repos/{REPO}/releases/latest"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", "User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            rel = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "", []
        raise
    return (rel.get("tag_name") or "").lstrip("v"), rel.get("assets") or []


def find_exe_asset(assets):
    for a in assets:
        if (a.get("name") or "").lower() == EXE_NAME.lower():
            return a
    return None


def _download(url: str, dest: str, timeout: int = 300):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)


def download_and_apply(asset: dict):
    """下载新版 exe → 写自替换脚本 → 启动脚本。当前进程由 server 侧退出。"""
    _, exe = _base()
    if not exe or not os.path.exists(exe):
        raise RuntimeError("仅打包版（PyInstaller exe）支持自更新")
    if (asset.get("size") or 0) > 500 * 1024 * 1024:
        raise RuntimeError("更新包异常过大，已中止")

    tmp = os.path.join(tempfile.gettempdir(), EXE_NAME + ".new")
    _download(asset["browser_download_url"], tmp)
    if os.path.getsize(tmp) < 1024 * 1024:
        raise RuntimeError("下载的更新包异常，已中止")

    pid = os.getpid()
    bat = os.path.join(tempfile.gettempdir(), "tokenmonitor-update.bat")
    # cmd 脚本用系统默认编码（GBK）写，避免中文路径乱码
    with open(bat, "w", encoding="gbk", errors="replace") as f:
        f.write(
            "@echo off\r\n"
            ":wait\r\n"
            f'tasklist /FI "PID eq {pid}" | find "{pid}" >nul\r\n'
            "if not errorlevel 1 (\r\n"
            "  timeout /t 1 /nobreak >nul\r\n"
            "  goto wait\r\n"
            ")\r\n"
            f'move /y "{tmp}" "{exe}" >nul\r\n'
            f'start "" "{exe}"\r\n'
            'del "%~f0"\r\n')
    subprocess.Popen(["cmd", "/c", bat], close_fds=True,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
