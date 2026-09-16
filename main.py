# -*- coding: utf-8 -*-
"""Token Monitor —— exe 入口。

启动本地服务 → 自动打开浏览器 → 托管运行。
打包：pyinstaller --onefile --name TokenMonitor main.py ...
"""
import socket
import threading
import webbrowser


def find_port(start: int = 8420) -> int:
    for p in range(start, start + 20):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return start


def main():
    port = find_port()
    url = f"http://127.0.0.1:{port}/"
    # 延迟打开浏览器，等 uvicorn 开始监听
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    import uvicorn
    import server
    print(f"Token Monitor → {url}")
    uvicorn.run(server.app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
