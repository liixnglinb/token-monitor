# -*- coding: utf-8 -*-
"""本地预览下载页：复刻线上路由（/token-monitor/ 静态 + /tm-api/latest 代理）。

用法：python token-monitor/dist-page/serve_preview.py [端口]   默认 8431
"""
import ipaddress
import json
import os
import re
import socket
import sys
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(BASE, os.pardir, "site")
# 站点共享资产（landing-cards 等）住在网站仓库的 public/ 下。预览必须一并服务，
# 否则本地这一版比线上"少一层"——卡片淡入/淡出的行为问题在本地根本暴露不出来。
SHARED = r"D:\Voyra 个人网站\public\design-system"
REPO = "liixnglinb/token-monitor"
MIME = {".html": "text/html; charset=utf-8", ".webp": "image/webp",
        ".png": "image/png", ".svg": "image/svg+xml", ".js": "text/javascript",
        ".css": "text/css", ".ico": "image/x-icon"}
_cache = {"t": 0, "body": b'{"error":"none"}'}


class _AllowlistRedirectHandler(urllib.request.HTTPRedirectHandler):
    """重定向目标必须仍是白名单域名（防跳转进内网）。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u = urllib.parse.urlparse(newurl)
        if u.scheme != "https" or (u.hostname or "") != "api.github.com":
            raise ValueError("拒绝重定向到非白名单地址: %s" % newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_AllowlistRedirectHandler)


def latest():
    if _cache["t"] and time.time() - _cache["t"] < 60:
        return _cache["body"]
    url = "https://api.github.com/repos/%s/releases/latest" % REPO
    # 出网白名单 + 解析边界校验：域名固定、解析出的 IP 必须全部为公网地址
    u = urllib.parse.urlparse(url)
    host = (u.hostname or "").lower()
    if u.scheme != "https" or host != "api.github.com":
        raise ValueError("拒绝访问非白名单地址: %s" % url)
    for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ValueError("拒绝解析到非公网地址的主机 %s → %s" % (host, info[4][0]))
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "preview"})
    try:
        with _OPENER.open(req, timeout=8) as r:
            d = json.loads(r.read().decode("utf-8"))
        assets = [{"name": a["name"], "size": a["size"], "url": a["browser_download_url"]}
                  for a in d.get("assets", [])]
        payload = {
            "version": str(d.get("tag_name", "")).lstrip("v"),
            "source": "api",
            "published": d.get("published_at"),
            "assets": assets,
        }
        # 与线上 Function 一致：代取 .sha256（浏览器直取会被 CORS 挡）
        sum_asset = next((a for a in assets
                          if a["name"].endswith(".sha256") and "setup" in a["name"].lower()), None)
        if sum_asset:
            for url in (sum_asset["url"], "https://gh-proxy.com/" + sum_asset["url"]):
                try:
                    with urllib.request.urlopen(
                            urllib.request.Request(url, headers={"User-Agent": "preview"}),
                            timeout=8) as r2:
                        m = re.search(r"[0-9a-fA-F]{64}", r2.read().decode("utf-8", "replace"))
                    if m:
                        payload["sha256"] = m.group(0).lower()
                        break
                except Exception:
                    continue
        body = json.dumps(payload).encode("utf-8")
    except Exception as e:
        body = json.dumps({"error": str(e)[:120]}).encode("utf-8")
    _cache["t"] = time.time()
    _cache["body"] = body
    return body


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/tm-api/latest":
            return self.send(200, latest(), "application/json; charset=utf-8")
        if p.startswith("/design-system/"):
            return self._send_file(SHARED, os.path.basename(p))   # 只取文件名，路径穿越无从下手
        if p in ("/", "/token-monitor", "/token-monitor/"):
            p = "/token-monitor/index.html"
        rel = p.lstrip("/")
        if rel.startswith("token-monitor/"):
            rel = rel[len("token-monitor/"):]
        return self._send_file(SITE, rel)

    def _send_file(self, root, rel):
        f = os.path.normpath(os.path.join(os.path.abspath(root), *rel.split("/")))
        if not f.startswith(os.path.abspath(root)) or not os.path.isfile(f):
            return self.send(404, b"not found", "text/plain")
        with open(f, "rb") as fh:
            body = fh.read()
        return self.send(200, body, MIME.get(os.path.splitext(f)[1], "application/octet-stream"))


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8431
    print("preview: http://127.0.0.1:%d/token-monitor/" % port)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
