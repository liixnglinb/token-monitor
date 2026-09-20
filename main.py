# -*- coding: utf-8 -*-
"""Token Monitor —— exe 入口（内嵌窗口版）

启动本地服务 → 在**内嵌窗口**（Windows WebView2）中打开看板 → 关闭窗口即退出。
不再调用系统浏览器；界面仍是同一套 HTML（webapp/static/index.html）。

打包：pyinstaller TokenMonitor.spec
"""
import ctypes
import logging
import os
import socket
import sys
import tempfile
import threading
import time
import traceback
import urllib.request

import webview

WINDOW_TITLE = "Token Monitor"
BG = "#0B0C0E"          # 与面板底色一致，加载时不闪白

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


def wait_ready(port: int, timeout: float = 20.0, serve_thread: "threading.Thread | None" = None) -> bool:
    """等端口真正可访问再开窗口，否则会先看到白屏/连接失败页

    首次启动要扫描本机日志，服务就绪可能要几秒。
    服务线程若在等待期间崩溃（已死或已记录错误），立即返回 False，
    不要傻等满 timeout 才让 main() 去开白屏窗口。
    """
    url = "http://127.0.0.1:%d/" % port
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


def main() -> None:
    global _INSTANCE_MUTEX
    LOG.info("=== 启动 exe=%s frozen=%s ===", sys.executable, getattr(sys, "frozen", False))

    # 单实例锁：Windows 命名互斥体，防止重复启动多个实例。
    # 注意 windowed exe 没有控制台，重复启动时 MessageBox 是唯一可见提示。
    _INSTANCE_MUTEX = ctypes.windll.kernel32.CreateMutexW(
        0, 0, "Local\\TokenMonitor.SingleInstance")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS = 183
        LOG.warning("检测到已有实例在运行，本进程退出")
        ctypes.windll.user32.MessageBoxW(
            0, "Token Monitor 已在运行。", "Token Monitor", 0x40)
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

    # 阻塞在窗口事件循环；用户关闭窗口后返回，进程随之退出
    try:
        webview.start()
    except BaseException:
        LOG.error("窗口事件循环异常:\n%s", traceback.format_exc())
        raise
    LOG.info("窗口已关闭，进程退出")


if __name__ == "__main__":
    main()
