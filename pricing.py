# -*- coding: utf-8 -*-
"""模型计价 —— 内置快照兜底 · LiteLLM 主源 · OpenRouter 回退 · CC Switch 补充

价格单位统一为「每 token 美元」。
数据来源（优先级由低到高）：
  pricing-bundled.json.gz                      (内置快照, ~12000 条, 兜底基线)
  ↓ 以下为本机缓存，存在则覆盖内置：
  %APPDATA%/tokscale/cache/pricing-litellm.json     (主源, ~2.3MB)
  %APPDATA%/tokscale/cache/pricing-openrouter.json  (回退)
  %APPDATA%/tokscale/cache/pricing-models-dev.json  (补充)
  ~/.cc-switch/cc-switch.db → model_pricing          (补充, 199 条)
"""
import gzip
import json
import os
import sqlite3
import sys

CACHE = os.path.join(os.environ.get("APPDATA", ""), "tokscale", "cache")

# 各源里"每 token 成本"字段的可能别名
F_IN = ("input_cost_per_token", "input_cost_per_token_usd", "prompt", "input")
F_OUT = ("output_cost_per_token", "output_cost_per_token_usd", "completion",
         "output")
F_CR = ("cache_read_input_token_cost", "cache_read_cost_per_token",
        "cache_read_input_token_cost_usd", "input_cost_per_token_cache_hit",
        "cache_read")
F_CW = ("cache_creation_input_token_cost", "cache_write_cost_per_token",
        "cache_creation_input_token_cost_usd", "input_cost_per_token_cache_miss",
        "cache_write")


def _num(v):
    try:
        f = float(v)
        return f if f >= 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def _first(d, names):
    for n in names:
        if n in d and d[n] is not None:
            return _num(d[n])
    return 0.0


def _load_json(fn):
    p = os.path.join(CACHE, fn)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    if isinstance(d, dict):
        d = d.get("data", d)
    return d if isinstance(d, dict) else {}


def _norm(m):
    """归一化模型名：小写、去空白、去 provider 前缀与常见别名前缀

    实测别名：日志里的 `zai_glm-5.3-flash` 与价格表的 `glm-5.3-flash`；
    连字符形式的 `sn-`（商汤小浣熊命名空间）同理 —— 曾漏掉它，
    导致 sn-deepseek-v4-pro / sn-glm-5-3-flash 等 2.12 亿 tok 误判为"价格未知"。
    注意：只加**能验证到去前缀后精确命中**的前缀；
    sensenova-* / ark-code-latest / ox-alpha-free 在价表里 0 命中，属真缺价，不许猜。
    是同一模型，不归一化会导致未命中。
    """
    m = (m or "").strip().lower()
    if not m:
        return ""
    for pre in ("zai_", "openai_", "anthropic_", "google_", "meta_", "sn-"):
        if m.startswith(pre):
            m = m[len(pre):]
            break
    return m


_INDEX = None
_STATS = {"total": 0, "hit": 0, "miss": {}}
ORIGIN = {"bundled": 0, "cache": 0, "ccswitch": 0}   # 价表来源构成，供面板显示


def _res(name):
    """资源定位：PyInstaller 打包后文件在 sys._MEIPASS 下"""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(
        os.path.abspath(__file__))
    return os.path.join(base, name)


def _load_custom():
    """用户自定义价表 —— 最高优先级，用来补我们不知道的模型。

    查找顺序（后者覆盖前者）：
      1) <程序目录>/custom-pricing.json
      2) %LOCALAPPDATA%/TokenMonitor/custom-pricing.json

    数值单位是「每 100 万 token 的美元价」，内部换算成 per-token。
    格式：{"model-name": {"input": 3, "output": 15,
                    "cache_write": 3.75, "cache_read": 0.3}}
      别名：in/out/w/r、prompt/completion 也认；
      缺 cache 项时按 Anthropic 口径用 input 的 1.25x / 0.1x 估算；
      以 // 开头的键视为注释。
    """
    out = {}
    paths = [_res("custom-pricing.json")]
    la = os.environ.get("LOCALAPPDATA")
    if la:
        paths.append(os.path.join(la, "TokenMonitor", "custom-pricing.json"))
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        for m, v in data.items():
            if str(m).startswith("//") or not isinstance(v, dict):
                continue
            # 用户写的是"每 100 万 token 美元"，这里换算成 per-token
            pi = _first(v, ("input", "in", "prompt")) / 1e6
            po = _first(v, ("output", "out", "completion")) / 1e6
            pw = _first(v, ("cache_write", "w", "cache_creation")) / 1e6
            pr = _first(v, ("cache_read", "r", "cached")) / 1e6
            if not (pi or po):
                continue
            pw = pw or pi * 1.25
            pr = pr or pi * 0.1
            key = _norm(m)
            out[key] = (pi, po, pw, pr)
            out.setdefault(key.split("/")[-1], (pi, po, pw, pr))
    return out


def _load_bundled():
    """内置价表快照（已归一化，元组顺序同索引：in/out/cw/cr）。

    这是兜底基线：用户机器上没有 tokscale / CC Switch 时，成本仍然算得出来。
    读不到就返回空，让上层继续尝试本机价表。
    """
    out = {}
    try:
        with gzip.open(_res("pricing-bundled.json.gz"), "rb") as f:
            data = json.loads(f.read().decode("utf-8"))
        for m, v in data.items():
            if isinstance(v, (list, tuple)) and len(v) == 4:
                out[_norm(m)] = tuple(float(x) for x in v)
    except Exception as e:
        # 绝不静默：读不到内置快照意味着新机器上可能全部计价失败，必须留痕
        ORIGIN["bundled_error"] = "%s: %s" % (type(e).__name__, e)
        return {}
    return out


def _build():
    global _INDEX, ORIGIN
    if _INDEX is not None:
        return _INDEX
    # 本机价表优先，优先级由低到高，后者覆盖前者
    raw = {}
    for fn in ("pricing-models-dev.json", "pricing-openrouter.json",
               "pricing-litellm.json"):
        for m, v in _load_json(fn).items():
            if not isinstance(v, dict):
                continue
            tup = (_first(v, F_IN), _first(v, F_OUT), _first(v, F_CW),
                   _first(v, F_CR))
            if tup[0] or tup[1]:
                raw[_norm(m)] = tup
    # CC Switch 仅作补漏，不覆盖已有的权威价格
    for m, v in _ccswitch_pricing().items():
        raw.setdefault(m, v)
    ORIGIN["cache"] = len(raw)

    # 内置快照只**补空位**：本机没有的模型才用它兜底。
    # 不能当基线先插入 —— 快照里含短名条目，而索引是短名先到先得，
    # 那样快照里的旧价会遮蔽本机更新过的价（实测总价从 $1286 掉到 $581）。
    for m, v in _load_bundled().items():
        raw.setdefault(m, v)

    # 用户自定义：最高优先级，最后覆盖（补内置价表里没有的模型）
    cust = _load_custom()
    ORIGIN["custom"] = len(cust)
    raw.update(cust)

    # 建索引：同时登记 全名 与 去 provider 前缀后的短名
    idx = {}
    for m, tup in raw.items():
        idx.setdefault(m, tup)
        short = m.split("/")[-1]
        if short and short not in idx:
            idx[short] = tup
    ORIGIN["total"] = len(idx)
    _INDEX = idx
    return idx


def _ccswitch_pricing():
    """CC Switch 的 model_pricing 表（每 token 美元）"""
    p = os.path.join(os.path.expanduser("~"), ".cc-switch", "cc-switch.db")
    out = {}
    if not os.path.exists(p):
        return out
    # ⚠️ 实际列名（实测）：
    #   model_id · input_cost_per_million · output_cost_per_million
    #   cache_read_cost_per_million · cache_creation_cost_per_million
    # 早期版本按 input_price 猜测字段，会读出 199 条「全 0 价格」，
    # 因其优先级最高而**静默覆盖** LiteLLM 的正确价格 → 成本被算成 0。
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro&immutable=1", uri=True)
        names = [r[1].lower() for r in
                 con.execute("PRAGMA table_info(model_pricing)")]
        if "model_id" not in names:
            con.close()
            return out
        rows = con.execute("SELECT * FROM model_pricing").fetchall()
        con.close()
    except sqlite3.Error:
        return out

    def g(d, *ks):
        for k in ks:
            if k in d and d[k] is not None:
                return d[k]
        return 0

    # 该表字段一律为「每百万 token」→ 换算为每 token
    scale = 1e-6
    for row in rows:
        d = dict(zip(names, row))
        model = _norm(g(d, "model_id", "model", "model_name"))
        if not model:
            continue
        tup = (_num(g(d, "input_cost_per_million")) * scale,
               _num(g(d, "output_cost_per_million")) * scale,
               _num(g(d, "cache_creation_cost_per_million")) * scale,
               _num(g(d, "cache_read_cost_per_million")) * scale)
        # 只有真正读到价格才登记，避免全 0 覆盖其他源
        if tup[0] or tup[1]:
            out[model] = tup
    return out


def lookup(model):
    """返回 (in, out, cache_write, cache_read) 每 token 美元；未命中返回 None"""
    idx = _build()
    m = _norm(model)
    if not m or m in ("unknown", "none"):
        return None
    if m in idx:
        return idx[m]
    short = m.split("/")[-1]
    if short in idx:
        return idx[short]
    # 前缀/包含匹配：取最长公共候选，避免短名误配
    best, blen = None, 0
    for k, v in idx.items():
        if len(k) > blen and (m.startswith(k) or k.startswith(m)):
            best, blen = v, len(k)
    return best


def cost(model, inp=0, cw=0, cr=0, out=0):
    """计算单条记录成本（美元）。未命中价格返回 None。"""
    t = lookup(model)
    _STATS["total"] += 1
    if t is None:
        _STATS["miss"][model] = _STATS["miss"].get(model, 0) + 1
        return None
    _STATS["hit"] += 1
    pi, po, pcw, pcr = t
    # 缓存写入通常按 input 的 1.25 倍计价（Anthropic 口径），缺字段时回退
    if pcw == 0:
        pcw = pi * 1.25
    if pcr == 0:
        pcr = pi * 0.1
    return inp * pi + cw * pcw + cr * pcr + out * po


def stats():
    tot = _STATS["total"]
    return {
        "查询次数": tot,
        "命中": _STATS["hit"],
        "未命中": tot - _STATS["hit"],
        "命中率": f"{_STATS['hit'] / tot * 100:.1f}%" if tot else "-",
        "未命中模型TOP": sorted(_STATS["miss"].items(), key=lambda x: -x[1])[:8],
    }


def table_size():
    return len(_build())


if __name__ == "__main__":
    print(f"价格表条目: {table_size():,}")
    for m in ("claude-sonnet-4-20250514", "gpt-5", "claude-opus-4-1-20250805",
              "gpt-4o", "deepseek-chat", "qwen3-coder-plus"):
        t = lookup(m)
        if t:
            print(f"  {m:<28} in=${t[0]*1e6:.3f}/M  out=${t[1]*1e6:.3f}/M"
                  f"  cw=${t[2]*1e6:.3f}/M  cr=${t[3]*1e6:.4f}/M")
        else:
            print(f"  {m:<28} 未命中")
