# -*- coding: utf-8 -*-
"""导出下载页数据：dist-page/data.json

之前 data.json 是手工拼出来的，没有任何脚本生成，所以必然滞后于产品。
本脚本走和产品完全相同的一条管道（all_merged_sources + pricing），
保证下载页上的数字与用户打开面板看到的口径一致。

用法：  python token-monitor/dist-page/export_data.py
"""
import io
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
# 生成器和它渲染的产品同仓：本目录的上一层就是 token-monitor/。
# 以前生成器住在工作区根，靠 ROOT/token-monitor 找扫描器，结果根目录还留过一份早已漂移的
# 旧分叉（probe_v3 与仓库版差 235 行），一旦 import 失败就静默退回旧分叉，页面数字和面板
# 对不上（box-agent 293M vs 1.62B 那次）。现在只有一条路径可走：
# 宁可 ImportError 当场炸出来，也不要拿错的扫描器算出一份看着合理的报表。
APP = os.path.dirname(BASE)
sys.path.insert(0, APP)

import pricing                                 # noqa: E402
import probe_v3_allsources as V3               # noqa: E402
print("扫描器:", V3.__file__)

OUT = os.path.join(BASE, "data.json")


def main():
    recs = []
    errors = []
    for name, fn in V3.all_merged_sources():
        try:
            r = fn()
            recs += r[0] if isinstance(r, tuple) else r
        except Exception as e:                 # 单源失败不拖垮导出
            errors.append("%s: %s" % (name, str(e)[:120]))

    per_agent = {}
    plan_tokens = 0
    unpriced_tokens = 0
    per_day = {}
    models = {}
    for r in recs:
        a = per_agent.setdefault(r.agent, {"tokens": 0, "req": 0, "cost": 0.0,
                                             "days": {}, "plan_tokens": 0})
        tok = r.total()
        a["tokens"] += tok
        a["req"] += 1
        c = pricing.cost(r.model, r.inp, r.cw, r.cr, r.out)
        a["cost"] += (c or 0.0)
        if c is None and pricing.is_plan(r.model):
            plan_tokens += tok
            a["plan_tokens"] += tok          # 供下载页区分「套餐不计费」与「价格未知」
        elif c is None:
            unpriced_tokens += tok           # 有价表外的模型：页面要如实说明这部分没算进金额
        models[r.model] = models.get(r.model, 0) + tok
        if r.date != "unknown":
            a["days"][r.date] = a["days"].get(r.date, 0) + tok
        per_day[r.date] = per_day.get(r.date, 0) + tok

    try:
        import sources_registry as SR
        names = {s.get("id"): (s.get("cn") or s.get("id"))
                 for s in getattr(SR, "SOURCES", []) if s.get("id")}
    except Exception:
        names = {}
    coverage = [{"id": k, "name": names.get(k, k), "note": v}
                for k, v in sorted((getattr(V3, "SKIP_NOTES", {}) or {}).items())]

    days_known = sorted(d for d in per_day if d != "unknown")
    cache_base = sum(r.inp + r.cw + r.cr for r in recs)
    data = {
        "kpi": {
            "tokens": sum(r.total() for r in recs),
            "requests": len(recs),
            "cost_usd": round(sum(pricing.cost(r.model, r.inp, r.cw, r.cr, r.out) or 0.0
                                  for r in recs), 6),
            "cache_rate": (sum(r.cr for r in recs) / cache_base) if cache_base else 0.0,
            "plan_tokens": plan_tokens,
            "plan_models": sorted({r.model for r in recs if pricing.is_plan(r.model)}),
            "unpriced_tokens": unpriced_tokens,
            "models": len(models),
            "span": [days_known[0], days_known[-1]] if days_known else [],
            "active_days": len(days_known),
        },
        "cache_stats": V3.flush_cache(),
        "coverage": coverage,
        "agents": [
            {"name": k, "tokens": v["tokens"], "req": v["req"],
             "cost": round(v["cost"], 6), "days": v["days"],
             "plan_tokens": v["plan_tokens"]}
            for k, v in sorted(per_agent.items(), key=lambda x: -x[1]["tokens"])
        ],
        "errors": errors,
    }

    io.open(OUT, "w", encoding="utf-8", newline="\n").write(
        json.dumps(data, ensure_ascii=False))
    print("导出完成:", OUT)
    print("  agents=%d  tokens=%s  requests=%s  cost=$%.2f  cache=%.1f%%"
          % (len(data["agents"]), format(data["kpi"]["tokens"], ","),
             format(data["kpi"]["requests"], ","), data["kpi"]["cost_usd"],
             data["kpi"]["cache_rate"] * 100))
    if V3.SKIP_NOTES:
        print("  源说明（会随扫描变化，仅供核对）:")
        for k, v in sorted(V3.SKIP_NOTES.items()):
            print("     %-16s %s" % (k, v))
    if errors:
        print("  扫描出错:", errors)


main()
