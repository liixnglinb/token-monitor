# -*- coding: utf-8 -*-
"""Token Monitor 服务端 —— DeepSeek 风格用量面板

数据管道：复用 probe_v3_allsources 的 9 个扫描器（含全部去重/语义修正），
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
CNY_RATE = 7.1                       # 展示用近似汇率，与 probe_v3 报告一致

STATIC_DIR = os.path.join(ROOT, "webapp", "static")

app = FastAPI(title="Token Monitor")
app.add_middleware(GZipMiddleware, minimum_size=1024)

_state = {"built_at": None, "data": None}


def _build() -> dict:
    """扫描全部数据源 → 计价 → 聚合矩阵。耗时约 5~20s。"""
    import probe_v3_allsources as V3

    pricing._STATS["hit"] = 0
    pricing._STATS["total"] = 0
    pricing._STATS["miss"] = {}

    recs = []
    scan_errors = []
    for name, fn in V3.ORIGINAL_SOURCES + V3.NEW_SOURCES:
        try:
            r = fn()
            recs += r[0] if isinstance(r, tuple) else r
        except Exception as e:                      # 单源失败不拖垮面板
            scan_errors.append({"agent": name, "error": str(e)[:120]})
            continue

    cells = {}
    unpriced_tokens = 0
    for r in recs:
        t = pricing.lookup(r.model)
        c = pricing.cost(r.model, r.inp, r.cw, r.cr, r.out)
        if c is None:
            c = 0.0
            unpriced_tokens += r.total()
        k = (r.date, r.agent, r.model)
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

    matrix = [{"date": d, "agent": a, "model": m, **v}
              for (d, a, m), v in cells.items()]

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
        "scan_errors": scan_errors,
    }


def get_data() -> dict:
    if _state["data"] is None:
        _state["data"] = _build()
        _state["built_at"] = datetime.now(CST).isoformat(timespec="seconds")
    return _state["data"]


@app.get("/api/summary")
def api_summary():
    d = get_data()
    return JSONResponse(d, headers={"Cache-Control": "no-store"})


@app.get("/api/reload")
def api_reload():
    _state["data"] = _build()
    _state["built_at"] = datetime.now(CST).isoformat(timespec="seconds")
    return {"ok": True, "built_at": _state["built_at"],
            "rows": len(_state["data"]["matrix"])}


@app.get("/api/version")
def api_version():
    local = updater.local_version()
    info = {"version": local, "latest": None, "has_update": False,
            "repo": updater.REPO}
    try:
        latest, _assets = updater.fetch_latest()
        info["latest"] = latest
        info["has_update"] = updater.is_newer(latest, local)
    except Exception as e:                          # 断网 / 限流时不影响使用
        info["error"] = str(e)[:120]
    return info


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


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
