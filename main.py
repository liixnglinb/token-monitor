# -*- coding: utf-8 -*-
"""Token Monitor —— exe 入口（内嵌窗口版）

启动本地服务 → 在**内嵌窗口**（Windows WebView2）中打开看板 → 关闭窗口即退出。
不再调用系统浏览器；界面仍是同一套 HTML（webapp/static/index.html）。

打包：pyinstaller TokenMonitor.spec
"""
import socket
import threading
import time
import urllib.request

import webview

WINDOW_TITLE = "Token Monitor"
BG = "#0B0C0E"          # 与面板底色一致，加载时不闪白


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
    import uvicorn
    import server
    uvicorn.run(server.app, host="127.0.0.1", port=port, log_level="warning")


def wait_ready(port: int, timeout: float = 20.0) -> bool:
    """等端口真正可访问再开窗口，否则会先看到白屏/连接失败页

    首次启动要扫描本机日志，服务就绪可能要几秒。
    """
    url = "http://127.0.0.1:%d/" % port
    deadline = time.time() + timeout
    while time.time() < deadline:
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
    port = find_port()
    threading.Thread(target=serve, args=(port,), daemon=True).start()
    wait_ready(port)

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
    webview.start()


if __name__ == "__main__":
    main()
