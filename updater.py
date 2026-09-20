# -*- coding: utf-8 -*-
"""自动更新 —— 对比 GitHub Releases，下载新版 exe 并自替换重启。

流程：/api/update → fetch_latest() 找到更新 → download_and_apply()
     下载新版到临时目录 → 优先用 .sha256 资产做 SHA256 完整性校验
     （校验失败立即中止，防止镜像返回截断/被篡改的包变砖）
     → 无校验资产时退回「体积 ≥ 1MB」兜底 → 写 update.bat
     （等待当前进程退出 → move 替换 → 重启）
     → server 1 秒后 os._exit(0) → bat 接管完成替换。
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

# 64 位十六进制哈希（SHA256 摘要串）
_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

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
    """返回 (latest_version_without_v, assets, info)。info 含 body/date 供浮层展示；
    404 时 ("", [], {})。"""
    url = f"https://api.github.com/repos/{REPO}/releases/latest"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", "User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            rel = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "", [], {}
        raise
    info = {"body": (rel.get("body") or "").strip(),
            "date": ((rel.get("published_at") or "")[:10])}
    return (rel.get("tag_name") or "").lstrip("v"), rel.get("assets") or [], info


def find_exe_asset(assets):
    for a in assets:
        if (a.get("name") or "").lower() == EXE_NAME.lower():
            return a
    return None


def find_sum_asset(assets):
    """找 exe 对应的 sha256 校验文件资产（name == EXE_NAME + '.sha256'）。无则返回 None。"""
    target = EXE_NAME + ".sha256"
    for a in assets:
        if (a.get("name") or "") == target:
            return a
    return None


def _sha256_of(path: str) -> str:
    """流式计算文件 SHA256，返回小写十六进制摘要（避免大文件一次性读入内存）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fetch_sha256(asset, timeout: int = 30):
    """下载 .sha256 校验文件并用现有三级镜像回退，返回期望哈希（小写 64 位十六进制）。

    解析规则：取文件首行第一个空白分隔 token 并小写化；不是合法 SHA256 则视为
    不可用，返回 None（交给 download_and_apply 的体积校验兜底，不卡死更新流程）。
    """
    url = asset.get("browser_download_url") if isinstance(asset, dict) else None
    if not url:
        return None
    tmp = os.path.join(tempfile.gettempdir(), EXE_NAME + ".sha256.tmp")
    # 校验文件极小，min_size=0 绕过 _download 的「≥1MB」检查
    try:
        _download(url, tmp, timeout=timeout, min_size=0)
    except Exception:
        return None
    try:
        with open(tmp, "r", encoding="utf-8", errors="replace") as f:
            line = f.readline()
        token = line.split()[0].strip().lower() if line.strip() else ""
        if _HEX_RE.match(token) and len(token) == 64:
            return token
        return None
    except Exception:
        return None
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# 下载源顺序：官方直连优先，失败自动回退国内镜像。
# 实测：国内网络下 github.com 直连常 WinError 10060 超时（release 资产走
# objects.githubusercontent.com，同样会受影响），没有回退会导致更新彻底失败。
_MIRRORS = ("", "https://gh-proxy.com/", "https://ghproxy.net/")


def _download(url: str, dest: str, timeout: int = 300, min_size: int = 1024 * 1024):
    last_err = None
    for pre in _MIRRORS:
        target = (pre + url) if pre else url
        try:
            req = urllib.request.Request(target, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    f.write(chunk)
            size = os.path.getsize(dest)
            if size >= min_size:
                return                      # 成功
            last_err = RuntimeError("下载内容异常（%d 字节）" % size)
        except Exception as e:              # 超时 / 连接失败 / HTTP 错误 → 换下一个源
            last_err = e
            continue
    raise last_err or RuntimeError("所有下载源均失败")


# 已下载待安装的更新包：download_staged 暂存，apply_staged 消费。
# 拆成两段是为了复刻 ZCode 的「已下载，重启即可安装」确认态——
# 下载完成不立即重启，等用户点左下角胶囊再替换。
STAGED = {}


def download_staged(asset: dict, checksum_asset=None, version: str = None) -> str:
    """第一段：下载新版到临时目录并校验完整性，暂存等待确认安装。返回暂存路径。

    完整性校验优先级：
      1) checksum_asset 不为 None 时，先下载对应 .sha256 并比对 SHA256，不一致直接中止；
      2) 无 .sha256 资产（checksum_asset 为 None）或校验文件不可用时，退回「体积 ≥ 1MB」
         兜底检查（兼容 v1.2.x 及更早没有 .sha256 资产的 Release，老用户升级不被卡死）。
    """
    _, exe = _base()
    if not exe or not os.path.exists(exe):
        raise RuntimeError("仅打包版（PyInstaller exe）支持自更新")
    if (asset.get("size") or 0) > 500 * 1024 * 1024:
        raise RuntimeError("更新包异常过大，已中止")

    tmp = os.path.join(tempfile.gettempdir(), EXE_NAME + ".new")
    _download(asset["browser_download_url"], tmp)

    # SHA256 完整性校验（优先）：防镜像返回截断/被篡改的包导致变砖
    if checksum_asset is not None:
        expected = _fetch_sha256(checksum_asset)
        if expected is not None:
            actual = _sha256_of(tmp)
            if actual != expected:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise RuntimeError("更新包 SHA256 校验失败，已中止（可能下载被篡改或镜像异常）")
        # expected 为 None（.sha256 下载/解析失败）→ 退回体积校验兜底

    # 体积兜底：无 sha256 或 sha256 不可用时，仍要求至少 1MB，避免错误页直接替换
    if os.path.getsize(tmp) < 1024 * 1024:
        raise RuntimeError("下载的更新包异常，已中止")

    STAGED.clear()
    STAGED.update({"tmp": tmp, "asset": dict(asset), "version": version})
    return tmp


def apply_staged(tmp: str = None) -> None:
    """第二段：为暂存的更新包写自替换脚本并启动；当前进程由 server 侧退出。"""
    _, exe = _base()
    tmp = tmp or STAGED.get("tmp")
    if not exe or not os.path.exists(exe):
        raise RuntimeError("仅打包版（PyInstaller exe）支持自更新")
    if not tmp or not os.path.exists(tmp):
        raise RuntimeError("暂存的更新包不存在，请重新下载")

    pid = os.getpid()
    exe_old = exe + ".old"
    bat = os.path.join(tempfile.gettempdir(), "tokenmonitor-update.bat")
    log = os.path.join(tempfile.gettempdir(), "tokenmonitor-update.log")
    # cmd 脚本用系统默认编码（GBK）写，避免中文路径乱码。
    #
    # ⚠️ Windows 锁定「运行中的 exe 映像」：move /y 直接覆盖自身会永久
    # 「拒绝访问」。标准做法（Chrome 式自更新）：
    #   1) 把运行中的 exe **改名**为 .old（改名不受映像锁限制）
    #   2) 新 exe move 到原路径
    #   3) start 新 exe，尽力删除 .old
    with open(bat, "w", encoding="gbk", errors="replace") as f:
        f.write(
            "@echo off\r\n"
            "setlocal enabledelayedexpansion\r\n"
            f'set LOG={log}\r\n'
            'echo [%date% %time%] update begin > "%LOG%"\r\n'
            ":wait\r\n"
            f'tasklist /FI "PID eq {pid}" | find "{pid}" >nul\r\n'
            "if not errorlevel 1 (\r\n"
            "  timeout /t 1 /nobreak >nul\r\n"
            "  goto wait\r\n"
            ")\r\n"
            'echo old process gone >> "%LOG%"\r\n'
            "set N=0\r\n"
            ":retry\r\n"
            f'move /y "{exe}" "{exe_old}" >> "%LOG%" 2>&1\r\n'
            "if errorlevel 1 (\r\n"
            "  set /a N+=1\r\n"
            '  echo rename failed !N! >> "%LOG%"\r\n'
            "  if !N! GEQ 15 goto giveup\r\n"
            "  timeout /t 2 /nobreak >nul\r\n"
            "  goto retry\r\n"
            ")\r\n"
            'echo renamed old exe >> "%LOG%"\r\n'
            # 放新 exe 也做重试：AV/索引器常短暂锁住目标目录，一次失败就放弃太激进
            "set M=0\r\n"
            ":place\r\n"
            f'move /y "{tmp}" "{exe}" >> "%LOG%" 2>&1\r\n'
            "if errorlevel 1 (\r\n"
            "  set /a M+=1\r\n"
            '  echo place failed !M! >> "%LOG%"\r\n'
            "  if !M! GEQ 5 goto giveup\r\n"
            "  timeout /t 2 /nobreak >nul\r\n"
            "  goto place\r\n"
            ")\r\n"
            'echo placed new exe >> "%LOG%"\r\n'
            'echo waiting for resources release >> "%LOG%"\r\n'
            'timeout /t 4 /nobreak >nul\r\n'
            f'start "" "{exe}"\r\n'
            'echo started >> "%LOG%"\r\n'
            f'del "{exe_old}" >> "%LOG%" 2>&1\r\n'
            'del "%~f0"\r\n'
            "exit /b\r\n"
            ":giveup\r\n"
            # 防砖：走到这里时旧 exe 多半已被改名成 .old，必须还原，
            # 否则目录里没有 exe，软件直接消失（P0）
            'echo GIVE UP >> "%LOG%"\r\n'
            f'if exist "{exe_old}" move /y "{exe_old}" "{exe}" >> "%LOG%" 2>&1\r\n'
            'echo restore attempted >> "%LOG%"\r\n'
            'del "%~f0"\r\n')
    subprocess.Popen(["cmd", "/c", bat], close_fds=True,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def discard_staged() -> None:
    """删除已下载未安装的暂存更新包并清空暂存记录（程序退出时调用，不留后台垃圾）。"""
    tmp = STAGED.get("tmp")
    STAGED.clear()
    if tmp and os.path.exists(tmp):
        try:
            os.remove(tmp)
            print("已清理暂存更新包: " + tmp)
        except OSError:
            pass


def download_and_apply(asset: dict, checksum_asset=None):
    """兼容入口：下载 + 校验 + 直接进入替换流程（一步到位，不等确认）。"""
    tmp = download_staged(asset, checksum_asset)
    apply_staged(tmp)
