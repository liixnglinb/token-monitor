# -*- coding: utf-8 -*-
"""自动更新 —— 对比 GitHub Releases，下载新版 exe 并自替换重启。

流程：/api/update → fetch_latest() 找到更新 → download_staged()
     下载新版到临时目录 → 优先用 .sha256 资产做 SHA256 完整性校验
     （校验失败立即中止，防止镜像返回截断/被篡改的包变砖）
     → 无校验资产时退回「体积 ≥ 1MB」兜底 → apply_staged()：
     先用 --selfcheck 预检新版 exe 能在本机完成 PyInstaller 引导
     （防安全软件拦截 python3xx.dll 导致替换后起不来，连续失败即中止、
     保留当前版本）→ 写 update.bat（等进程退出 → move 替换 → 启动新版 →
     轮询 boot.stamp 确认引导成功，失败自动重试 3 次，仍失败回滚旧版本）
     → server 1 秒后 os._exit(0) → bat 接管完成替换。
"""
import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import (
    ThreadPoolExecutor,
    TimeoutError as FuturesTimeoutError,
    as_completed,
)

# 64 位十六进制哈希（SHA256 摘要串）
_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

REPO = "liixnglinb/token-monitor"
EXE_NAME = "TokenMonitor.exe"
_UA = "TokenMonitor-Updater"
_PROGRESS_LOCK = threading.Lock()
_PROGRESS = {
    "state": "idle",
    "percent": 0,
    "downloaded": 0,
    "total": 0,
    "version": None,
    "message": "",
    "source": None,
}


# ── 出网与路径加固（纵深防御）────────────────────────────────────────
# 更新链路的 URL 由「固定镜像前缀 + GitHub 下载地址」拼接而成，全部收敛进
# 白名单；更新临时文件必须落在系统临时目录内。拼接源均为本模块常量，
# 这里是第二道防线：即便常量被改坏，越界访问也会在真正请求前被拦下。
_ALLOWED_HOSTS = frozenset({
    "api.github.com", "github.com", "objects.githubusercontent.com",
    "gh-proxy.com", "ghfast.top",
})


def _guard_url(url: str) -> str:
    """出网白名单校验：仅放行 https + 已知官方/镜像域名，且域名解析出的
    所有 IP 必须是公网地址（阻断内网/环回/链路本地，防 DNS rebinding）。"""
    u = urllib.parse.urlparse(url)
    host = (u.hostname or "").lower()
    if u.scheme != "https" or host not in _ALLOWED_HOSTS:
        raise RuntimeError("拒绝访问非白名单地址: %s" % url)
    for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise RuntimeError("拒绝解析到非公网地址的主机 %s → %s"
                               % (host, info[4][0]))
    return url


class _AllowlistRedirectHandler(urllib.request.HTTPRedirectHandler):
    """重定向目标必须同样通过白名单 + 解析边界校验（防跳转进内网）。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _guard_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_AllowlistRedirectHandler)


def _guard_temp_path(path: str) -> str:
    """路径越界校验：更新相关文件必须落在系统临时目录内。"""
    base = os.path.realpath(tempfile.gettempdir())
    p = os.path.realpath(path)
    if os.path.commonpath([base, p]) != base:
        raise RuntimeError("路径越出临时目录: %s" % path)
    return p


def set_progress(**patch):
    """Thread-safe progress snapshot for the local UI."""
    with _PROGRESS_LOCK:
        _PROGRESS.update(patch)
        return dict(_PROGRESS)


def update_progress():
    with _PROGRESS_LOCK:
        return dict(_PROGRESS)


def _base():
    """返回 (只读资源目录, 可执行文件路径)。开发态可执行文件为 None。"""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS, sys.executable
    return os.path.dirname(os.path.abspath(__file__)), None


def local_version() -> str:
    base, _ = _base()
    try:
        with open(os.path.join(base, "version.txt"), encoding="utf-8") as f:
            # version.txt 可能带 UTF-8 BOM（PowerShell 5.1 的 Set-Content 就会写 BOM）。
            # 不剥掉的话 "1.9.13" 会被当成非语义化版本，导致"已是最新却提示有更新"。
            text = f.read().lstrip("\ufeff").strip()
            return text.lstrip("v") or "0.0.0"
    except OSError:
        return "0.0.0"


def _parse(v: str):
    return tuple(int(x) for x in v.strip().lstrip("\ufeff").lstrip("v").split("."))


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
    url = _guard_url(f"https://api.github.com/repos/{REPO}/releases/latest")
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", "User-Agent": _UA})
    try:
        with _OPENER.open(req, timeout=timeout) as r:
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


def find_setup_asset(assets):
    """找 Inno Setup 安装包资产（name 形如 TokenMonitor-setup-<版本>.exe）。

    为什么优先用它而不是 TokenMonitor.exe：单文件 exe 只能靠自替换脚本覆盖自己
    （见 apply_staged 的 bat），用户看不到任何安装界面；安装包则是标准的 Inno 向导，
    由用户自己点「下一步」完成安装——这正是需求要的形态。找不到时才退回单文件 exe。
    """
    for a in assets:
        name = (a.get("name") or "")
        low = name.lower()
        if low.startswith("tokenmonitor-setup") and low.endswith(".exe"):
            return a
    return None


def find_sum_asset(assets, name: str = None):
    """找某个资产对应的 sha256 校验文件（name == <资产名> + '.sha256'）。无则返回 None。

    name 省略时按单文件 exe 找。安装包与单文件 exe 各有自己的 .sha256 资产
    （TokenMonitor-setup-<版本>.exe.sha256 / TokenMonitor.exe.sha256），
    所以调用方要把实际下载的那个资产名传进来，否则安装包这条路径会静默降级成体积校验。
    """
    target = (name or EXE_NAME) + ".sha256"
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


def _fetch_sha256(asset, timeout: int = 30, preferred_source=None):
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
        _download(
            url,
            tmp,
            timeout=timeout,
            min_size=0,
            speed_test=False,
            preferred_source=preferred_source,
        )
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


# 候选源。正式下载前会并发采样，按本机到各源的实际吞吐率排序。
# 顺序即"探测全失败时的兜底优先级" —— 2026-09-27 起镜像在前：
# 国内网络下直连 GitHub 常常不可用，探测失败时先试镜像才不会"更新点不动"。
# 2026-09-27：ghproxy.net 实测仅 ~90KB/s 且频繁卡死，换成 ghfast.top（下载页同款备用镜像）。
_SOURCES = (
    ("GH Proxy", "https://gh-proxy.com/"),
    ("ghfast.top", "https://ghfast.top/"),
    ("GitHub 直连", ""),
)
_PROBE_BYTES = 384 * 1024
_PROBE_MIN_BYTES = 32 * 1024
# 2026-09-27 实测本机 TTFB ≈1.0-1.1s：原 1.6s 超时太紧，网络一抖三个源会全部采样失败、
# 退回"直连优先"的静态顺序。放宽到 3s/4s，代价只是更新检查多等几秒（后台执行）。
_PROBE_TIMEOUT = 3.0
_PROBE_BUDGET = 4.0
_SOURCE_CACHE_TTL = 5 * 60
_SOURCE_CACHE_LOCK = threading.Lock()
_SOURCE_CACHE = {}


def _source_url(url: str, prefix: str) -> str:
    return prefix + url if prefix else url


def _probe_source(source, url: str):
    """在 3 秒预算内采样，返回该源在本机网络下的实际吞吐率。"""
    label, prefix = source
    target = _guard_url(_source_url(url, prefix))
    req = urllib.request.Request(target, headers={
        "User-Agent": _UA,
        "Accept-Encoding": "identity",
        "Range": "bytes=0-%d" % (_PROBE_BYTES - 1),
    })
    started = time.perf_counter()
    received = 0
    with _OPENER.open(req, timeout=_PROBE_TIMEOUT) as r:
        while received < _PROBE_BYTES:
            if time.perf_counter() - started >= _PROBE_BUDGET:
                break
            chunk = r.read(min(64 * 1024, _PROBE_BYTES - received))
            if not chunk:
                break
            received += len(chunk)
    elapsed = max(time.perf_counter() - started, 0.001)
    if received < _PROBE_MIN_BYTES:
        raise RuntimeError("%s 测速样本不足" % label)
    return label, prefix, received / elapsed


def _rank_sources(url: str):
    """并发测速并缓存排名；全部失败时保留原始顺序兜底。"""
    now = time.monotonic()
    with _SOURCE_CACHE_LOCK:
        cached = _SOURCE_CACHE.get(url)
        if cached and cached[0] > now:
            return list(cached[1])

    results = {}
    pool = ThreadPoolExecutor(max_workers=len(_SOURCES))
    try:
        futures = {
            pool.submit(_probe_source, source, url): source
            for source in _SOURCES
        }
        for future in as_completed(futures, timeout=_PROBE_BUDGET):
            source = futures[future]
            try:
                label, prefix, speed = future.result()
                results[(label, prefix)] = speed
            except Exception:
                # 单个源探测失败不影响其余源，也不阻断正式下载。
                continue
    except FuturesTimeoutError:
        # 排名只负责选优，不允许慢源拖住更新启动。
        pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    if results:
        ordered = sorted(_SOURCES, key=lambda s: (
            -results.get((s[0], s[1]), -1.0),
            _SOURCES.index(s),
        ))
    else:
        ordered = list(_SOURCES)

    if results:
        with _SOURCE_CACHE_LOCK:
            _SOURCE_CACHE[url] = (now + _SOURCE_CACHE_TTL, tuple(ordered))
    return ordered


def _ordered_sources(url: str, speed_test: bool = True, preferred_source=None):
    sources = _rank_sources(url) if speed_test else list(_SOURCES)
    if preferred_source:
        preferred = tuple(preferred_source)
        moved = [s for s in sources if s != preferred]
        sources = ([preferred] if preferred in _SOURCES else []) + moved
    return sources


def _download(
    url: str,
    dest: str,
    timeout: int = 20,
    min_size: int = 1024 * 1024,
    progress_cb=None,
    speed_test: bool = True,
    preferred_source=None,
):
    last_err = None
    dest = _guard_temp_path(dest)
    for label, prefix in _ordered_sources(url, speed_test, preferred_source):
        target = _guard_url(_source_url(url, prefix))
        # 落盘走 mkstemp + 原子替换：先写进临时目录里的随机命名文件，
        # 完整且过体积校验后才 replace 成 dest —— 断流/坏包不会在
        # dest 留下半个文件
        fd, part = tempfile.mkstemp(prefix="tm-dl-")
        try:
            req = urllib.request.Request(target, headers={
                "User-Agent": _UA,
                "Accept-Encoding": "identity",
            })
            with os.fdopen(fd, "wb") as f, _OPENER.open(req, timeout=timeout) as r:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                if progress_cb:
                    progress_cb(done, total, label)
                while True:
                    chunk = r.read(1 << 19)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if progress_cb:
                        progress_cb(done, total, label)
            size = os.path.getsize(part)
            if size >= min_size:
                os.replace(part, dest)
                return label, prefix         # 成功
            last_err = RuntimeError("下载内容异常（%d 字节）" % size)
        except Exception as e:              # 超时 / 连接失败 / HTTP 错误 → 换下一个源
            last_err = e
            continue
        finally:
            if os.path.exists(part):
                try:
                    os.remove(part)
                except OSError:
                    pass
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

    # 暂存名必须保留 .exe 扩展名：安装包要能被直接 Popen 拉起（CreateProcess 认扩展名），
    # 原来的 "TokenMonitor.exe.new" 只能给自替换脚本 move 用。
    tmp = os.path.join(tempfile.gettempdir(), "TokenMonitor-update.exe")
    declared_total = int(asset.get("size") or 0)
    set_progress(
        state="downloading",
        percent=0,
        downloaded=0,
        total=declared_total,
        version=version,
        message="正在测速并选择最快下载源",
        source=None,
    )

    def on_progress(done, total, source):
        known_total = total or declared_total
        percent = round(done / known_total * 100, 1) if known_total else 0
        set_progress(
            state="downloading",
            percent=min(percent, 100),
            downloaded=done,
            total=known_total,
            version=version,
            message="正在从 %s 下载新版本" % source,
            source=source,
        )

    try:
        source_label, source_prefix = _download(
            asset["browser_download_url"],
            tmp,
            min_size=declared_total or 1024 * 1024,
            progress_cb=on_progress,
        )
    except Exception as exc:
        set_progress(
            state="error",
            percent=0,
            version=version,
            message=str(exc)[:160],
            source=None,
        )
        raise

    set_progress(
        state="verifying",
        percent=100,
        downloaded=declared_total,
        total=declared_total,
        version=version,
        message="正在校验 %s 下载的更新包" % source_label,
        source=source_label,
    )

    # SHA256 完整性校验（优先）：防镜像返回截断/被篡改的包导致变砖
    if checksum_asset is not None:
        expected = _fetch_sha256(
            checksum_asset,
            preferred_source=(source_label, source_prefix),
        )
        if expected is not None:
            actual = _sha256_of(tmp)
            if actual != expected:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                set_progress(
                    state="error",
                    percent=0,
                    version=version,
                    message="更新包 SHA256 校验失败",
                    source=source_label,
                )
                raise RuntimeError("更新包 SHA256 校验失败，已中止（可能下载被篡改或镜像异常）")
        # expected 为 None（.sha256 下载/解析失败）→ 退回体积校验兜底

    # 体积兜底：无 sha256 或 sha256 不可用时，仍要求至少 1MB，避免错误页直接替换
    if os.path.getsize(tmp) < 1024 * 1024:
        set_progress(
            state="error",
            percent=0,
            version=version,
            message="下载的更新包异常",
            source=source_label,
        )
        raise RuntimeError("下载的更新包异常，已中止")

    STAGED.clear()
    STAGED.update({
        "tmp": tmp,
        "asset": dict(asset),
        "version": version,
        "source": source_label,
    })
    set_progress(
        state="ready",
        percent=100,
        downloaded=os.path.getsize(tmp),
        total=os.path.getsize(tmp),
        version=version,
        message="已从 %s 下载完成，准备安装" % source_label,
        source=source_label,
    )
    return tmp


# ── 更新预检 ─────────────────────────────────────────────────────────
# 预检命令行参数由 main.py 在单实例锁之前消费：进程只要能执行到 Python 代码
# 就立即退出 0。⚠️ 未来的新版 main.py 必须保留该参数处理，否则预检会因
# 单实例互斥体冲突而永远"假成功"（或唤起旧窗口），防线失效。
_SELFCHECK_FLAG = "--selfcheck"
_PREFLIGHT_ATTEMPTS = 3      # 连续失败次数上限（杀软深扫通常 1-2 次内放行）
_PREFLIGHT_WAIT = 90.0       # 单次预检最长等待秒数（正常 <10s，留杀软深扫余量）
_PREFLIGHT_RETRY_GAP = 8.0   # 两次预检之间的间隔秒数


def _preflight_new_exe(staged: str) -> None:
    """验证暂存的新版 exe 能在本机完成 PyInstaller 引导（能执行到 Python 代码）。

    通过则正常返回；失败抛 RuntimeError（含用户可读的处置提示），调用方
    （apply_staged）据此在替换当前 exe 之前中止更新——旧版本原样保留。
    """
    _, exe = _base()
    # 复制到安装目录再试运行，而不是直接从 %TEMP% 执行：
    # 从 TEMP 运行无签名 exe 本身就是常见杀软启发式拦截点。
    # realpath 规范化后再拼装，杜绝符号链接/相对路径把探针文件带出安装目录。
    probe = os.path.join(os.path.dirname(os.path.realpath(exe)),
                         "TokenMonitor.preflight.exe")
    probe_dir = os.path.dirname(probe)
    try:
        if os.path.commonpath([os.path.realpath(exe), probe]) != probe_dir:
            raise RuntimeError("更新预检失败：探针路径越出安装目录")
        shutil.copyfile(staged, probe)
    except OSError as exc:
        raise RuntimeError("更新预检失败：无法写入安装目录（%s）" % exc)

    last_code = None
    try:
        for attempt in range(1, _PREFLIGHT_ATTEMPTS + 1):
            set_progress(
                state="applying",
                percent=100,
                message="正在预检新版本能否在本机启动（第 %d/%d 次）"
                        % (attempt, _PREFLIGHT_ATTEMPTS),
                source=STAGED.get("source"),
            )
            try:
                proc = subprocess.Popen(
                    [probe, _SELFCHECK_FLAG],
                    close_fds=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except OSError as exc:
                raise RuntimeError("更新预检失败：无法启动新版 exe（%s）" % exc)
            try:
                last_code = proc.wait(timeout=_PREFLIGHT_WAIT)
            except subprocess.TimeoutExpired:
                # 引导失败会弹模态错误框等用户点确认；一直没人点就超时杀掉重试
                proc.kill()
                proc.wait()
                last_code = None
            if last_code == 0:
                return
            time.sleep(_PREFLIGHT_RETRY_GAP)
    finally:
        try:
            os.remove(probe)
        except OSError:
            pass

    raise RuntimeError(
        "新版本连续 %d 次预检失败（退出码 %s），已中止更新，当前版本未受影响。"
        "多为安全软件拦截新版 exe 所致：可将安装目录加入杀软信任区后重试，"
        "或稍后再试" % (_PREFLIGHT_ATTEMPTS,
                        "超时" if last_code is None else last_code))


def _launch_setup_installer() -> None:
    """拉起安装包向导，把「安装」这一步交回给用户。

    与自替换路径的区别：不做防砖预检、不写 bat、不自动重启。安装向导自己接管一切
    ——installer.iss 里 CloseApplications=yes，运行中的进程由它关闭；装完由 Inno
    的默认行为启动新版本。DETACHED_PROCESS 是为了让安装器脱离本进程：
    server 侧 1 秒后会 os._exit(0)，不脱离子进程会被一起收掉。
    """
    tmp = STAGED.get("tmp")
    if not tmp or not os.path.exists(tmp):
        raise RuntimeError("暂存的安装包不存在，请重新下载")
    set_progress(
        state="applying",
        percent=100,
        message="正在打开安装程序",
        source=STAGED.get("source"),
    )
    flags = 0
    if hasattr(subprocess, "DETACHED_PROCESS"):
        flags = subprocess.DETACHED_PROCESS | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([tmp], close_fds=True, creationflags=flags)


def apply_staged(tmp: str = None) -> None:
    """第二段：安装暂存的更新包；当前进程由 server 侧退出。

    暂存的是 Inno 安装包时走 _launch_setup_installer（弹出安装向导，用户点「下一步」）；
    只有拿不到安装包、退回单文件 exe 时才走原来的自替换脚本路径。
    """
    asset_name = str((STAGED.get("asset") or {}).get("name") or "").lower()
    if "setup" in asset_name:
        return _launch_setup_installer()
    _, exe = _base()
    tmp = tmp or STAGED.get("tmp")
    if not exe or not os.path.exists(exe):
        raise RuntimeError("仅打包版（PyInstaller exe）支持自更新")
    if not tmp or not os.path.exists(tmp):
        raise RuntimeError("暂存的更新包不存在，请重新下载")
    set_progress(
        state="applying",
        percent=100,
        message="正在准备安装更新",
        source=STAGED.get("source"),
    )

    # 防砖预检：先确认新版 exe 在本机跑得起来（能执行到 Python 代码），
    # 再动当前安装。2026-10-01 实测：安全软件（联想电脑管家/火绒引擎）对
    # 「刚被自更新替换的无签名 exe」首次启动会深度实时扫描，可能拦掉
    # _MEI 解压目录里的 python3xx.dll / vcruntime，LoadLibrary 报
    # 「找不到指定的模块」，用户以为软件变砖。预检把这类拦截挡在替换之前：
    # 重试仍失败就中止更新，当前版本原样保留。
    _preflight_new_exe(tmp)

    pid = os.getpid()
    exe_old = exe + ".old"
    bat = _guard_temp_path(os.path.join(tempfile.gettempdir(),
                                        "tokenmonitor-update.bat"))
    log = _guard_temp_path(os.path.join(tempfile.gettempdir(),
                                        "tokenmonitor-update.log"))
    # cmd 脚本用系统默认编码（GBK）写，避免中文路径乱码。
    #
    # ⚠️ Windows 锁定「运行中的 exe 映像」：move /y 直接覆盖自身会永久
    # 「拒绝访问」。标准做法（Chrome 式自更新）：
    #   1) 把运行中的 exe **改名**为 .old（改名不受映像锁限制）
    #   2) 新 exe move 到原路径
    #   3) start 新 exe，尽力删除 .old
    # 脚本内容先写进 mkstemp 临时文件再原子替换成 bat：cmd 只会读到完整脚本
    fd_bat, bat_part = tempfile.mkstemp(prefix="tokenmonitor-update-bat.")
    try:
        with os.fdopen(fd_bat, "w", encoding="gbk", errors="replace") as f:
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
                # ── 启动确认 + 自动重试 + 回滚（根治「找不到指定的模块」）──
                # 新版本 main() 第一时间写 %LOCALAPPDATA%\TokenMonitor\boot.stamp；
                # 轮询不到 = 引导失败（杀软拦 DLL 等）→ 杀掉弹窗进程自动重试，
                # 连续 3 次失败 → 还原 .old 旧版本并启动，软件绝不消失。
                "set STAMP=%LOCALAPPDATA%\\TokenMonitor\\boot.stamp\r\n"
                "set ATT=0\r\n"
                ":boot\r\n"
                "set /a ATT+=1\r\n"
                'echo [%date% %time%] boot attempt !ATT! >> "%LOG%"\r\n'
                'if exist "%STAMP%" del "%STAMP%" >nul 2>&1\r\n'
                f'start "" "{exe}"\r\n'
                "set B=0\r\n"
                ":bootwait\r\n"
                'timeout /t 5 /nobreak >nul\r\n'
                'if exist "%STAMP%" goto booted\r\n'
                "set /a B+=1\r\n"
                "if !B! LSS 12 goto bootwait\r\n"
                'echo boot not confirmed (attempt !ATT!) >> "%LOG%"\r\n'
                'taskkill /F /IM TokenMonitor.exe >nul 2>&1\r\n'
                "if !ATT! LSS 3 goto boot\r\n"
                "goto rollback\r\n"
                ":booted\r\n"
                'echo boot confirmed >> "%LOG%"\r\n'
                f'del "{exe_old}" >> "%LOG%" 2>&1\r\n'
                'del "%~f0"\r\n'
                "exit /b\r\n"
                ":rollback\r\n"
                # 防砖：连续 3 次启动都没确认 → 还原旧版本并启动
                'echo ROLLBACK to old version >> "%LOG%"\r\n'
                f'if exist "{exe_old}" move /y "{exe_old}" "{exe}" >> "%LOG%" 2>&1\r\n'
                f'start "" "{exe}"\r\n'
                'del "%~f0"\r\n'
                "exit /b\r\n"
                ":giveup\r\n"
                # 防砖：走到这里时旧 exe 多半已被改名成 .old，必须还原，
                # 否则目录里没有 exe，软件直接消失（P0）
                'echo GIVE UP >> "%LOG%"\r\n'
                f'if exist "{exe_old}" move /y "{exe_old}" "{exe}" >> "%LOG%" 2>&1\r\n'
                'echo restore attempted >> "%LOG%"\r\n'
                'del "%~f0"\r\n')
        os.replace(bat_part, bat)
    except BaseException:
        try:
            os.remove(bat_part)
        except OSError:
            pass
        raise
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
