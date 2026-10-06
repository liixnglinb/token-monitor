# -*- coding: utf-8 -*-
"""Token Monitor 服务端 —— DeepSeek 风格用量面板

数据管道：probe_v3_allsources 的手写扫描器 + 注册表驱动扩展源
（含全部去重 / 语义修正 / 超预算整源丢弃），
经 pricing.py 计价后，聚合成 (date, agent, model) 矩阵交给前端自由筛选。

接口（与前端 js 的调用点一一对应，加删路由请同时改这份清单）：
        GET  /api/summary           全量聚合矩阵 + KPI（首扫期间是 partial 部分结果）
        GET  /api/reload            重新扫描数据源
        GET  /api/settings          后端状态 + 设置（busy/queued/error/built_at）
        POST /api/settings          改设置（只认 DEFAULTS 白名单键，越界钳制）
        GET  /api/version           本地版本 / 最新版本 / 是否有更新
        POST /api/update            下载新版（并发测速挑最快源）
        GET  /api/update/progress   下载进度（percent/state/source/message）
        POST /api/update/apply      替换 exe 并重启
        GET  /                      前端页面
"""
import os
import sys
import threading
import time
import logging

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import pricing
import updater

# 与 main.py 用同一个 logger：本地服务的日志和界面的报错要落到同一份 app.log，
# 否则用户报障时只有半边证据。
LOG = logging.getLogger("tokenmonitor")
_CLIENT_ERR = {"ts": [], "n": 0}      # 前端异常上报的限流窗口

CST = None  # 延迟导入保持结构清晰（见下）
from datetime import datetime, timezone, timedelta
CST = timezone(timedelta(hours=8))
CNY_RATE = 7.1
SCAN_WORKERS = int(os.environ.get("TM_WORKERS", "8"))   # 并行扫描线程数                       # 展示用近似汇率，与 probe_v3 报告一致

STATIC_DIR = os.path.join(ROOT, "webapp", "static")

app = FastAPI(title="Token Monitor")
app.add_middleware(GZipMiddleware, minimum_size=1024)


# ── 本机防护中间件 ───────────────────────────────────────────────
# 后端只裸奔在 127.0.0.1：恶意网页可跨站调 /api/reload（触发全盘扫描）、
# POST /api/settings、POST /api/update（驱动下载更新），且 Host 头可被
# DNS rebinding 伪造。下面这块纯 ASGI 中间件做两道本地防护：
#   规则 A 防 DNS rebinding：Host 主机名不在 {127.0.0.1, localhost, [::1]}
#   规则 B 防跨站 CSRF：/api/* 带了 Origin 且 Origin 主机名不在上述集合 → 拦截
# 无 Origin 的请求（curl、同源 GET）直接放行，不破坏现有用法。
# 注意：pywebview 内嵌浏览器加载的是 http://127.0.0.1:port，同源请求，
#       不带跨站 Origin，也不受影响。
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
_ALLOWED_ORIGIN_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _host_name(host: str) -> str:
    """从 Host 头剥离端口，IPv6 保留方括号形式以便与集合比对"""
    host = (host or "").strip()
    if host.startswith("["):
        end = host.find("]")
        return host[:end + 1] if end != -1 else host
    return host.split(":")[0]


def _origin_host(origin: str) -> str:
    """从 Origin 头取主机名（urlparse 已剥端口与方括号）"""
    from urllib.parse import urlparse
    return (urlparse(origin or "").hostname or "").lower()


async def _guard_reply(send, status: int, payload: dict) -> None:
    import json
    body = json.dumps(payload).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": body})


class LocalOnlyGuard:
    """只允许本机来源的中间件（DNS rebinding + 跨站 CSRF 双防）"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode()
                   for k, v in scope.get("headers", [])}
        if _host_name(headers.get("host", "")) not in _ALLOWED_HOSTS:
            await _guard_reply(send, 403, {"ok": False, "error": "forbidden host"})
            return
        path = (scope.get("path") or "").split("?")[0]
        origin = headers.get("origin")
        if path.startswith("/api/") and origin:
            if _origin_host(origin) not in _ALLOWED_ORIGIN_HOSTS:
                await _guard_reply(send, 403,
                                   {"ok": False, "error": "cross-origin blocked"})
                return
        await self.app(scope, receive, send)


app.add_middleware(LocalOnlyGuard)    # 挂在 GZip 之后，最外层先执行

# 启动时清理上次更新留下的旧映像（改名后的 *.exe.old 尽力删除）
if getattr(sys, "frozen", False):
    try:
        _old = sys.executable + ".old"
        if os.path.exists(_old):
            os.remove(_old)
    except OSError:
        pass

import refresher as RF                                # noqa: E402


def _version_probe():
    """软件更新检查：由后台线程按间隔调用，结果缓存供 /api/version 秒回"""
    try:
        import updater
    except Exception:
        return {"version": "dev", "latest": None, "has_update": False,
                "dev_mode": True}
    local = updater.local_version()
    info = {"version": local, "latest": None, "has_update": False,
            "repo": updater.REPO}
    try:
        latest, _assets, meta = updater.fetch_latest()
        info["latest"] = latest
        info["has_update"] = updater.is_newer(latest, local)
        info["body"] = meta.get("body", "")
        info["date"] = meta.get("date", "")
    except Exception as e:                              # 断网/限流不影响使用
        info["error"] = str(e)[:120]
    return info


def _aggregate(recs, scan_errors, V3) -> dict:
    """把原始用量记录聚合成面板要用的矩阵 + KPI。纯函数，可重复调用。"""
    cells = {}
    unpriced_tokens = 0
    unpriced_requests = 0    # 价表缺价（API 但没匹配到价格）的请求数
    plan_tokens = 0          # 套餐/订阅制：有意不计费，只记用量
    plan_models = set()      # 供界面区分『套餐不计费』与『价表缺价』
    for r in recs:
        t = pricing.lookup(r.model)
        c = pricing.cost(r.model, r.inp, r.cw, r.cr, r.out)
        isplan = pricing.is_plan(r.model)
        if isplan:
            plan_models.add(r.model)
            plan_tokens += r.total()      # 套餐：有意不计费
            c = 0.0
        elif c is None:
            c = 0.0
            unpriced_tokens += r.total()  # API 但价表缺价
            unpriced_requests += 1
        k = (r.date, r.agent, r.model, (r.session or "unknown")[:12])
        cell = cells.get(k)
        if cell is None:
            cell = cells[k] = {"tokens": 0, "cost": 0.0, "requests": 0,
                               "inp": 0, "out": 0, "cr": 0, "cw": 0, "think": 0,
                               "priced": 0, "unpriced": 0}
        cell["tokens"] += r.total()
        cell["cost"] += c
        cell["requests"] += 1
        cell["inp"] += r.inp
        cell["out"] += r.out
        cell["cr"] += r.cr
        cell["cw"] += r.cw
        # 深度思考 Token（Codex reasoning / Claude reasoning_tokens 等）。
        # 语义上属于输出的一部分，单独透出供前端做「输出内思考」子段展示；
        # 不参与 tokens 总和（避免重复计数）。旧前端多收此字段无副作用（增量键）。
        cell["think"] += getattr(r, "think", 0) or 0
        cell["unpriced" if (t is None or isplan) else "priced"] += 1

    matrix = [{"date": d, "agent": a, "model": m, "session": s, **v}
              for (d, a, m, s), v in cells.items()]

    def _sum(key):
        out = {}
        for row in matrix:
            o = out.setdefault(row[key], {"tokens": 0, "cost": 0.0, "requests": 0})
            o["tokens"] += row["tokens"]
            o["cost"] += row["cost"]
            o["requests"] += row["requests"]
        return [{"name": k, **v} for k, v in out.items()]

    dates = sorted({row["date"] for row in matrix if row["date"] != "unknown"})
    total_cache_base = sum(r.inp + r.cw + r.cr for r in recs)

    return {
        "generated_at": datetime.now(CST).isoformat(timespec="seconds"),
        "cny_rate": CNY_RATE,
        "range": {"min": dates[0] if dates else None,
                  "max": dates[-1] if dates else None},
        "matrix": matrix,
        "agents": sorted(_sum("agent"), key=lambda x: -x["tokens"]),
        "models": sorted(_sum("model"), key=lambda x: -x["tokens"]),
        "kpi_all": {
            "tokens": sum(r.total() for r in recs),
            "requests": len(recs),
            "cost_usd": sum(r["cost"] for r in matrix),
            "cache_rate": sum(r.cr for r in recs) / max(total_cache_base, 1),
            "unpriced_tokens": unpriced_tokens,
            "unpriced_requests": unpriced_requests,
            "plan_tokens": plan_tokens,
            "plan_models": sorted(plan_models),
        },
        "source_notes": dict(getattr(V3, "SKIP_NOTES", {})),
        "coverage": _coverage(V3),
        "scan_errors": scan_errors,
    }


def _build(progress_cb=None) -> dict:
    """扫描全部数据源 → 计价 → 聚合矩阵。

    实测耗时（本机 62 个源、8 线程并行）：
      · 磁盘缓存全空的首次扫描  约 110s
      · 有 scan-cache 的常规重建 约 20~30s（未变动的源直接复用上次解析结果）
    本函数只在后台线程里跑；/api/summary 始终立即返回上一次的好数据，界面不会被扫描阻塞。

    progress_cb(payload)：扫描过程中每完成若干源就回抛一份「部分结果」，
    让首扫期间的界面不再是一片空白。只读不改，正式返回值不受影响。
    """
    import probe_v3_allsources as V3

    pricing._STATS["hit"] = 0
    pricing._STATS["total"] = 0
    pricing._STATS["miss"] = {}

    # 并行扫描：绝大多数源是 I/O 等待，线程池能把冷扫从 ~110s 压到 ~30s 量级
    acc, errs = [], []
    last_pub = [0.0]

    def on_progress(done, total, name, new_recs, error):
        acc.extend(new_recs)
        if error:
            errs.append({"agent": name, "error": error})
        if progress_cb is None:
            return
        now = time.monotonic()
        # 节流：聚合是 O(已扫记录数)，逐源发布会变成 O(n²)；2s 一跳足够跟手
        if done < total and now - last_pub[0] < 2.0:
            return
        last_pub[0] = now
        payload = _aggregate(list(acc), list(errs), V3)
        payload["partial"] = True
        payload["progress"] = {"done": done, "total": total}
        progress_cb(payload)

    recs, scan_errors = V3.run_all_sources(workers=SCAN_WORKERS,
                                           on_progress=on_progress if progress_cb else None)

    payload = _aggregate(recs, scan_errors, V3)
    payload["cache_stats"] = V3.flush_cache()
    return payload


_R = RF.Refresher(_build, version_fn=_version_probe)   # 必须在 _build 之后


_SRC_NAMES = None


def _coverage(V3):
    """已知来源清单：{id, name, note} —— 供前端在侧栏展示「未计入」分组。

    note 来自 SKIP_NOTES（扫描时对"检出但没计入"的源写下的原因），
    name 用注册表的中文名（缺失时回退 id）。"""
    global _SRC_NAMES
    if _SRC_NAMES is None:
        _SRC_NAMES = {}
        try:
            import sources_registry as SR
            for s in getattr(SR, "SOURCES", []):
                sid = s.get("id")
                if sid:
                    _SRC_NAMES[sid] = s.get("cn") or sid
        except Exception:
            pass
    notes = getattr(V3, "SKIP_NOTES", {}) or {}
    return [{"id": k, "name": _SRC_NAMES.get(k, k), "note": v}
            for k, v in sorted(notes.items())]


@app.get("/api/summary")
def api_summary():
    """立即返回上一次的好数据；首扫进行中退回部分结果（partial=true）；什么都没有才返回 building 占位"""
    d, built_at, err, busy = _R.snapshot()
    d = dict(d)
    meta = dict(_R.status())
    meta["updated"] = built_at
    if err:
        meta["error"] = err
    d["_meta"] = meta
    if busy and not d.get("partial"):
        d.setdefault("building", True)
    return JSONResponse(d, headers={"Cache-Control": "no-store"})


@app.get("/api/reload")
def api_reload():
    """非阻塞：正在扫描时再点 = 排队，绝不并发跑两个扫描"""
    return JSONResponse(_R.refresh(force=True))


@app.post("/api/client-error")
async def api_client_error(request: Request):
    """前端未捕获异常 / Promise 拒绝的落地通道。

    界面是 WebView，崩在里面用户只会看到"某块没出来"，事后什么线索都没有。
    这里把消息写进和本地服务同一份 app.log，报障时能直接看。
    只收字符串摘要 + 文件名 + 行号：不收对话原文、不收请求体、不做任何持久化结构。
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "请求体不是合法 JSON"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "请求体必须是 JSON 对象"}, status_code=400)
    now = time.time()
    _CLIENT_ERR["n"] = sum(1 for t in _CLIENT_ERR["ts"] if now - t < 60)
    if _CLIENT_ERR["n"] >= 12:                       # 死循环报错不该把日志刷爆
        return JSONResponse({"ok": False, "error": "rate-limited"}, status_code=429)
    _CLIENT_ERR["ts"].append(now)
    msg = str(body.get("msg") or "")[:500]
    src = str(body.get("src") or "")[:200]
    try:
        line = max(0, min(int(body.get("line") or 0), 10 ** 7))
    except (TypeError, ValueError):
        line = 0
    LOG.warning("前端异常: %s @ %s:%s", msg or "(空)", src or "?", line)
    return JSONResponse({"ok": True})


@app.get("/api/settings")
def api_get_settings():
    return JSONResponse(_R.status())


@app.post("/api/settings")
async def api_set_settings(request: Request):
    try:
        body = await request.json()
    except Exception:
        # 以前解析失败当成"空补丁"照样回 ok:true，界面以为存好了其实什么都没改。
        return JSONResponse({"ok": False, "error": "请求体不是合法 JSON"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "请求体必须是 JSON 对象"}, status_code=400)
    return JSONResponse({"ok": True, "settings": _R.set_settings(body)})


@app.get("/api/version")
def api_version():
    """读后台缓存的版本信息，秒回；缓存为空时自行发起一次检查"""
    return JSONResponse(_R.version())


@app.post("/api/update")
def api_update():
    """第一段：下载新版到暂存（不替换、不重启），等用户在界面确认安装。

    注：此前这里调 download_and_apply「一步到位」——下载完立刻替换重启，
    与需求的"下载完成后提示是否现在更新并重启"不符，故拆成两段。"""
    try:
        latest, assets, _meta = updater.fetch_latest()
        asset = updater.find_exe_asset(assets)
        if asset is None:
            return JSONResponse({"ok": False,
                                 "error": "Release 中没有可更新的 exe 资产"}, status_code=400)
        # 若 Release 附带 .sha256 校验资产则一并传入，下载后做 SHA256 完整性校验
        updater.download_staged(asset, checksum_asset=updater.find_sum_asset(assets),
                                version=latest)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]}, status_code=500)
    return {"ok": True, "latest": latest, "staged": True}


@app.post("/api/update/apply")
def api_update_apply():
    """第二段：用户确认「现在更新并重启」后，替换 exe 并重启（自替换脚本接管）。"""
    try:
        updater.apply_staged()
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]}, status_code=500)
    # 1 秒后退出当前进程，让更新脚本接管（替换 exe 并重启）
    threading.Timer(1.0, lambda: os._exit(0)).start()
    return {"ok": True}


@app.get("/api/update/progress")
def api_update_progress():
    return JSONResponse(
        updater.update_progress(),
        headers={"Cache-Control": "no-store"},
    )


_R.start()          # 后台刷新线程：按 settings.refresh_minutes 自动重扫


@app.get("/")
def index():
    return FileResponse(
        os.path.join(STATIC_DIR, "index.html"),
        headers={"Cache-Control": "no-store"},
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
