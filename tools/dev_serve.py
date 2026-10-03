# -*- coding: utf-8 -*-
"""开发期静态服务：只跑 FastAPI（不起 WebView 窗口、不起托盘），方便改前端后刷新查看。

与 main.py 的 serve() 行为一致：不显式关闭 websockets 导入，http="h11"。
用法：
    python tools/dev_serve.py            # 127.0.0.1:8420
    python tools/dev_serve.py 8500       # 换端口
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8420
    import uvicorn
    import server

    print(f"[dev_serve] http://127.0.0.1:{port}  static={server.STATIC_DIR}", flush=True)
    uvicorn.run(server.app, host="127.0.0.1", port=port,
                log_level="warning", http="h11", ws="none")


if __name__ == "__main__":
    main()
