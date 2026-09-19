# -*- coding: utf-8 -*-
"""Token Monitor 服务端 —— DeepSeek 风格用量面板

数据管道：probe_v3_allsources 的手写扫描器 + 注册表驱动扩展源
（含全部去重 / 语义修正 / 超预算整源丢弃），
经 pricing.py 计价后，聚合成 (date, agent, model) 矩阵交给前端自由筛选。

接口：  GET  /api/summary   全量聚合矩阵 + KPI
        GET  /api/reload    重新扫描数据源
        GET  /api/version   本地版本 / 最新版本 / 是否有更新
        POST /api/update    下载新版并自替换重启
        GET  /              前端页面
"""
import os
import sys
import threading

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import pricing
import updater

CST = None  # 延迟导入保持结构清晰（见下）
from datetime import datetime, timezone, timedelta
CST = timezone(timedelta(hours=8))
CNY_RATE = 7.1
SCAN_WORKERS = int(os.environ.get("TM_WORKERS", "8"))   # 并行扫描线程数                       # 展示用近似汇率，与 probe_v3 报告一致

STATIC_DIR = os.path.join(ROOT, "webapp", "static")

app = FastAPI(title="Token Monitor")
app.add_middleware(GZipMiddleware, minimum_size=1024)

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
        latest, _assets = updater.fetch_latest()
        info["latest"] = latest
        info["has_update"] = updater.is_newer(latest, local)
    except Exception as e:                              # 断网/限流不影响使用
        info["error"] = str(e)[:120]
    return info


def _build() -> dict:
    """扫描全部数据源 → 计价 → 聚合矩阵。

    实测耗时（本机 62 个源、8 线程并行）：
      · 磁盘缓存全空的首次扫描  约 110s
      · 有 scan-cache 的常规重建 约 20~30s（未变动的源直接复用上次解析结果）
    本函数只在后台线程里跑；/api/summary 始终立即返回上一次的好数据，界面不会被扫描阻塞。
    """
    import probe_v3_allsources as V3

    pricing._STATS["hit"] = 0
    pricing._STATS["total"] = 0
    pricing._STATS["miss"] = {}

    # 并行扫描：绝大多数源是 I/O 等待，线程池能把冷扫从 ~110s 压到 ~30s 量级
    recs, scan_errors = V3.run_all_sources(workers=SCAN_WORKERS)

    cells = {}
    unpriced_tokens = 0
    for r in recs:
        t = pricing.lookup(r.model)
        c = pricing.cost(r.model, r.inp, r.cw, r.cr, r.out)
        if c is None:
            c = 0.0
            unpriced_tokens += r.total()
        k = (r.date, r.agent, r.model, (r.session or "unknown")[:12])
        cell = cells.get(k)
        if cell is None:
            cell = cells[k] = {"tokens": 0, "cost": 0.0, "requests": 0,
                               "inp": 0, "out": 0, "cr": 0, "cw": 0,
                               "priced": 0, "unpriced": 0}
        cell["tokens"] += r.total()
        cell["cost"] += c
        cell["requests"] += 1
        cell["inp"] += r.inp
        cell["out"] += r.out
        cell["cr"] += r.cr
        cell["cw"] += r.cw
        cell["unpriced" if t is None else "priced"] += 1

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
        },
        "source_notes": dict(getattr(V3, "SKIP_NOTES", {})),
        "cache_stats": V3.flush_cache(),
        "scan_errors": scan_errors,
    }


_R = RF.Refresher(_build, version_fn=_version_probe)   # 必须在 _build 之后


@app.get("/api/summary")
def api_summary():
    """立即返回上一次的好数据；没有结果时后台发起首扫并返回 building 占位"""
    d, built_at, err, busy = _R.snapshot()
    d = dict(d)
    meta = dict(_R.status())
    meta["updated"] = built_at
    if err:
        meta["error"] = err
    d["_meta"] = meta
    if busy:
        d.setdefault("building", True)
    return JSONResponse(d, headers={"Cache-Control": "no-store"})


@app.get("/api/reload")
def api_reload():
    """非阻塞：正在扫描时再点 = 排队，绝不并发跑两个扫描"""
    return JSONResponse(_R.refresh(force=True))


@app.get("/api/settings")
def api_get_settings():
    return JSONResponse(_R.status())


@app.post("/api/settings")
async def api_set_settings(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    return JSONResponse({"ok": True, "settings": _R.set_settings(body)})


@app.get("/api/version")
def api_version():
    """读后台缓存的版本信息，秒回；缓存为空时自行发起一次检查"""
    return JSONResponse(_R.version())


@app.post("/api/update")
def api_update():
    try:
        latest, assets = updater.fetch_latest()
        asset = updater.find_exe_asset(assets)
        if asset is None:
            return JSONResponse({"ok": False,
                                 "error": "Release 中没有可更新的 exe 资产"}, status_code=400)
        updater.download_and_apply(asset)           # 下载 → 写自替换脚本
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]}, status_code=500)
    # 1 秒后退出当前进程，让更新脚本接管（替换 exe 并重启）
    threading.Timer(1.0, lambda: os._exit(0)).start()
    return {"ok": True, "latest": latest}


_R.start()          # 后台刷新线程：按 settings.refresh_minutes 自动重扫


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
