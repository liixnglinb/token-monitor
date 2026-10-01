# -*- coding: utf-8 -*-
"""Token Monitor —— exe 入口（内嵌窗口版）

启动本地服务 → 在**内嵌窗口**（Windows WebView2）中打开看板 → 关闭窗口即退出。
不再调用系统浏览器；界面仍是同一套 HTML（webapp/static/index.html）。

打包：pyinstaller TokenMonitor.spec
"""
import ctypes
import ipaddress
import logging
import os
import socket
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
import urllib.request

import webview

WINDOW_TITLE = "Token Monitor"
BG = "#0B0D10"          # 与面板底色一致，加载时不闪白

SERVE_ERROR = []        # 服务线程崩溃时记录最近一条错误；main() 据此决定是否提示退出
_INSTANCE_MUTEX = None  # 单实例互斥体句柄，存模块级防 GC（进程结束前一直持有）


def _setup_log() -> logging.Logger:
    """文件日志：windowed 模式没有控制台，出问题只能靠它排查"""
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    d = os.path.join(base, "TokenMonitor")
    try:
        os.makedirs(d, exist_ok=True)
        logging.basicConfig(
            filename=os.path.join(d, "app.log"), level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
    except Exception:
        logging.basicConfig(level=logging.INFO)
    return logging.getLogger("tokenmonitor")


LOG = _setup_log()


def find_port(start: int = 8420) -> int:
    """从 8420 起找一个可用端口（被占用就往后找）"""
    for p in range(start, start + 20):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return start


def serve(port: int) -> None:
    try:
        import uvicorn
        import server
        LOG.info("服务线程启动 port=%s", port)
        # ws="none"：本项目是纯 HTTP 服务，不需要 WebSocket。
        # 不显式关掉的话，uvicorn 会导入 websockets —— 打包环境若缺该包，
        # 会抛 `ImportError: cannot import name '__version__' from 'websockets'`
        # http="h11"：h11 是纯 Python 实现（uvicorn 的必需依赖，必定存在）。
        # 默认的 "auto" 会优先用 httptools —— 那是 uvicorn[standard] 的可选 C 扩展，
        # 本项目依赖里没有，打包后会出现残缺模块 →
        # `AttributeError: module 'httptools' has no attribute 'HttpRequestParser'`
        uvicorn.run(server.app, host="127.0.0.1", port=port,
                    log_level="warning", http="h11", ws="none")
    except BaseException:
        exc = traceback.format_exc()
        LOG.error("服务线程异常退出:\n%s", exc)
        # 记录最近一条错误（截断到末尾 1500 字符），供 main() 判定是否提示退出
        SERVE_ERROR.append(exc[-1500:])


def _guard_loopback_url(url: str) -> str:
    """就绪探测只允许打向本机回环地址：协议与主机名白名单之外，
    还要校验解析后的 IP 全部落在回环段（防 DNS rebinding 到内网）。"""
    u = urllib.parse.urlparse(url)
    host = (u.hostname or "").lower()
    if u.scheme != "http" or host != "127.0.0.1":
        raise RuntimeError("拒绝访问非回环地址: %s" % url)
    for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(info[4][0]).is_loopback:
            raise RuntimeError("拒绝解析到非回环地址的主机: %s" % info[4][0])
    return url


def wait_ready(port: int, timeout: float = 20.0, serve_thread: "threading.Thread | None" = None) -> bool:
    """等端口真正可访问再开窗口，否则会先看到白屏/连接失败页

    首次启动要扫描本机日志，服务就绪可能要几秒。
    服务线程若在等待期间崩溃（已死或已记录错误），立即返回 False，
    不要傻等满 timeout 才让 main() 去开白屏窗口。
    """
    url = _guard_loopback_url("http://127.0.0.1:%d/" % port)
    deadline = time.time() + timeout
    while time.time() < deadline:
        # 服务线程已死或已记录错误：没必要再等，直接判定失败
        if serve_thread is not None and not serve_thread.is_alive():
            return False
        if SERVE_ERROR:
            return False
        try:
            with urllib.request.urlopen(url, timeout=0.8) as r:
                if r.status < 500:
                    return True
        except Exception:
            time.sleep(0.25)
    return False


def open_external(url: str) -> None:
    """外链交给系统默认浏览器，不在应用窗口里打开"""
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass


def hook_external_links(window) -> None:
    """把页面里的站外链接改走系统浏览器

    面板里只有少量外链（如 GitHub），不拦的话会在窗口内跳走、回不来。
    """
    js = """
    (function(){
      if (window.__tmLinkHooked) return;
      window.__tmLinkHooked = true;
      document.addEventListener('click', function(e){
        var a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
        if (!a) return;
        var href = a.getAttribute('href') || '';
        var external = /^https?:\\/\\//i.test(href) && href.indexOf(location.origin) !== 0;
        if (external || a.target === '_blank') {
          e.preventDefault();
          if (window.pywebview && window.pywebview.api && window.pywebview.api.open_external) {
            window.pywebview.api.open_external(href);
          }
        }
      }, true);
    })();
    """
    try:
        window.evaluate_js(js)
    except Exception:
        pass


class Api:
    """暴露给页面调用的最小接口"""

    def open_external(self, url: str) -> None:
        open_external(url)


# ── 顶边融合：标题栏染成侧栏同色，实现 ZCode 式「无边框一体」观感 ──
# 原理：DWM 允许给原生标题栏上色（Win11 22000+）。标题栏 = 侧栏色后，
# 左侧 logo 列与标题栏在视觉上连成一根贯通到窗口顶的侧栏；
# 右上角的原生最小化/关闭按钮保留（不牺牲缩放、贴靠、任务栏行为）。
# Win10 不支持上色（调用返回错误码，被忽略），退化为深色标题栏。
_DWM_SIDEBAR = 0x00130F0C      # COLORREF(0x00BBGGRR) ← 侧栏 #0C0F13
_DWM_TEXT = 0x007D7169         # 标题文字 ← --dim #69717D（弱化到近隐形）
_DWM_COLOR_NONE = 0xFFFFFFFE   # 去掉 1px 窗口边框线


def fuse_titlebar() -> None:
    """给窗口上 DWM 深色融合妆。找不到句柄或非 Win11 时静默跳过。"""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = 0
        for _ in range(10):                       # 窗口句柄可能晚几百毫秒才就绪
            hwnd = user32.FindWindowW(None, WINDOW_TITLE)
            if hwnd:
                break
            time.sleep(0.3)
        if not hwnd:
            LOG.warning("fuse_titlebar: 未找到窗口句柄，跳过")
            return
        dwm = ctypes.windll.dwmapi
        def _set(attr: int, val: int) -> None:
            v = ctypes.c_uint(val)
            # 注意：attr/size 必须传原生 int——包成 c_int 传给 int 型形参
            # 在部分 Python/ctypes 版本会抛 TypeError
            dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), attr,
                                      ctypes.byref(v), ctypes.sizeof(v))
        _set(20, 1)                               # DWMWA_USE_IMMERSIVE_DARK_MODE
        _set(35, _DWM_SIDEBAR)                    # DWMWA_CAPTION_COLOR
        _set(36, _DWM_TEXT)                       # DWMWA_TEXT_COLOR
        _set(34, _DWM_COLOR_NONE)                 # DWMWA_BORDER_COLOR
        LOG.info("fuse_titlebar applied hwnd=%s", hwnd)
    except Exception:
        LOG.warning("fuse_titlebar 失败（不影响使用）:\n%s", traceback.format_exc())


# ── 系统托盘：关窗最小化到托盘继续监控；托盘「退出」结束全部后台 ──
_TRAY = {"icon": None, "window": None, "port": 0}   # 运行期引用，防 GC 回收


def _tray_image():
    """从打包资源里的 icon.ico 读 64px 图像作托盘图标。"""
    from PIL import Image
    base = sys._MEIPASS if getattr(sys, "frozen", False) \
        else os.path.dirname(os.path.abspath(__file__))
    img = Image.open(os.path.join(base, "icon.ico"))
    img.load()
    if img.size != (64, 64):
        img = img.resize((64, 64), Image.LANCZOS)
    return img.convert("RGBA")


def _api_get(port: int, path: str):
    """托盘菜单动作走本地 HTTP，复用后端既有逻辑（重扫/检查更新）。"""
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:%d%s" % (port, path), timeout=4) as r:
            return r.status
    except Exception:
        return None


def _quit_all(icon=None, item=None) -> None:
    """托盘「退出」：停托盘 → 关窗口 → 删暂存更新包 → 硬退出。

    os._exit 让 uvicorn / 扫描线程随进程立即终止，不残留任何后台。
    """
    LOG.info("托盘退出：开始清理全部后台")
    try:
        import updater
        updater.discard_staged()      # 删除已下载未安装的暂存更新包
    except Exception:
        LOG.warning("清理暂存更新包失败（忽略）:\n%s", traceback.format_exc())
    try:
        w = _TRAY.get("window")
        if w:
            w.destroy()
    except Exception:
        pass
    try:
        if icon:
            icon.stop()
    except Exception:
        pass
    LOG.info("托盘退出：os._exit(0)")
    os._exit(0)


def _on_closing(window) -> bool:
    """点窗口 X：隐藏到托盘继续监控（真退出走托盘菜单），返回 False 取消关闭。

    注：这里不弹托盘冒泡通知 —— 用户明确要求"最小化不留小窗"，静默收进托盘即可。"""
    try:
        window.hide()
        LOG.info("窗口隐藏到托盘")
    except Exception:
        LOG.warning("隐藏到托盘失败:\n%s", traceback.format_exc())
    return False                        # 取消默认关闭行为


def _setup_tray(window, port: int) -> None:
    """托盘图标 + 右键菜单。失败只记日志，主功能不受影响。"""
    try:
        import pystray
        img = _tray_image()

        def _show(*_a):
            try:
                window.show()
            except Exception:
                pass

        menu = pystray.Menu(
            pystray.MenuItem("显示面板", _show, default=True),
            pystray.MenuItem("重新扫描数据源",
                             lambda *_a: _api_get(port, "/api/reload")),
            pystray.MenuItem("检查更新",
                             lambda *_a: _api_get(port, "/api/version")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出（结束全部后台）", _quit_all),
        )
        icon = pystray.Icon("TokenMonitor", img, "Token Monitor", menu)
        _TRAY["icon"] = icon
        _TRAY["window"] = window
        _TRAY["port"] = port
        threading.Thread(target=icon.run, daemon=True, name="tm-tray").start()
        LOG.info("托盘已启动")
    except Exception:
        LOG.warning("托盘初始化失败（不影响主功能）:\n%s", traceback.format_exc())


def _force_foreground(hwnd) -> None:
    """把窗口拉到前台。SetForegroundWindow 受前台权限限制，
    先 AttachThreadInput 到当前前台线程再调用（标准绕法）。"""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    fg = user32.GetForegroundWindow()
    tid_fg = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    tid_self = kernel32.GetCurrentThreadId()
    attached = False
    try:
        if tid_fg and tid_fg != tid_self:
            attached = bool(user32.AttachThreadInput(tid_fg, tid_self, True))
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(tid_fg, tid_self, False)


def _activate_existing() -> None:
    """二次启动：还原并前置"已在运行"的实例窗口，而不是弹提示让用户自己找。

    场景：窗口被 X 收进托盘后，用户又从快捷方式/托盘双击启动 ——
    期望是上次那个窗口直接回到眼前（窗口对象一直在，只是被 ShowWindow(SW_HIDE) 藏了）。
    """
    try:
        user32 = ctypes.windll.user32
        hwnd = 0
        for _ in range(15):                    # 已有实例可能刚隐藏到托盘，句柄需要等一小会儿
            hwnd = user32.FindWindowW(None, WINDOW_TITLE)
            if hwnd:
                break
            time.sleep(0.2)
        if not hwnd:
            LOG.warning("二次启动：未找到已有实例的窗口句柄")
            return
        SW_SHOW, SW_RESTORE = 5, 9
        if user32.IsIconic(hwnd) or not user32.IsWindowVisible(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE if user32.IsIconic(hwnd) else SW_SHOW)
        _force_foreground(hwnd)
        LOG.info("二次启动：已唤起已有窗口 hwnd=%s", hwnd)
    except Exception:
        LOG.warning("二次启动唤起窗口失败（不影响已在运行的实例）:\n%s", traceback.format_exc())


def main() -> None:
    global _INSTANCE_MUTEX

    # 更新预检模式：updater 在替换 exe 之前以 --selfcheck 启动新版一次，
    # 只要能执行到这里，就说明 PyInstaller 引导器加载 python3xx.dll 及整个
    # Python 运行时成功（即「Failed to load Python DLL」一类故障不存在），
    # 立即正常退出 0 表示预检通过。
    # ⚠️ 必须放在单实例锁之前：预检发生时旧实例仍在运行，先建锁会被判成
    # 二次启动，把旧窗口拉到前台且退出码语义混乱。
    if "--selfcheck" in sys.argv[1:]:
        LOG.info("selfcheck OK：bootloader 与 Python 运行时加载正常")
        return

    LOG.info("=== 启动 exe=%s frozen=%s ===", sys.executable, getattr(sys, "frozen", False))

    # 单实例锁：Windows 命名互斥体，防止重复启动多个实例。
    # 二次启动 = 唤起已有窗口（用户直觉），而不是弹"已在运行"再让人自己翻托盘。
    _INSTANCE_MUTEX = ctypes.windll.kernel32.CreateMutexW(
        0, 0, "Local\\TokenMonitor.SingleInstance")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS = 183
        LOG.info("检测到已有实例在运行 → 唤起其窗口后本进程退出")
        _activate_existing()
        sys.exit(0)

    port = find_port()
    LOG.info("选定端口 %s", port)
    serve_thread = threading.Thread(target=serve, args=(port,), daemon=True)
    serve_thread.start()
    ok = wait_ready(port, serve_thread=serve_thread)
    LOG.info("服务就绪=%s", ok)
    if not ok:
        # 服务线程崩溃：弹出提示后直接退出，避免用户看到白屏窗口
        if SERVE_ERROR:
            LOG.error("服务启动失败：\n%s", SERVE_ERROR[-1])
            ctypes.windll.user32.MessageBoxW(
                0,
                "服务启动失败，请查看日志：%LOCALAPPDATA%\\TokenMonitor\\app.log",
                "Token Monitor", 0x40)
            sys.exit(1)
        LOG.warning("服务在 20 秒内未就绪，仍尝试开窗口（页面可能暂时连不上）")

    window = webview.create_window(
        WINDOW_TITLE,
        "http://127.0.0.1:%d/" % port,
        width=1280,
        height=860,
        min_size=(1000, 660),
        background_color=BG,
        text_select=True,          # 允许选中数字，方便复制
        js_api=Api(),
    )

    window.events.loaded += lambda: hook_external_links(window)
    window.events.shown += lambda: fuse_titlebar()
    # 点 X = 隐藏到托盘继续监控；彻底退出走托盘菜单「退出（结束全部后台）」
    window.events.closing += lambda *a: _on_closing(window)
    _setup_tray(window, port)

    # 阻塞在窗口事件循环；真退出由托盘菜单触发（os._exit 清理全部后台）
    try:
        webview.start()
    except BaseException:
        LOG.error("窗口事件循环异常:\n%s", traceback.format_exc())
        raise
    LOG.info("窗口已关闭，进程退出")


if __name__ == "__main__":
    main()
