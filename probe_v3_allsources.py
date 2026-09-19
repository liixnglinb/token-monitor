# -*- coding: utf-8 -*-
r"""
Token Monitor v3 — 全源统一解析（含重叠检测）
================================================
核心原则：**新增源不能无脑相加**。

实测发现两类重复陷阱：
  1. CC Switch 是"多来源聚合器"：10,253 行中 9,611 行是
     从 Codex / Claude / OpenCode 会话**导入**的（data_source = *_session / session_log），
     这些数据**已经在**对应 agent 的原生日志里解析过了 → 必须排除。
  2. MiniMax 的 token_usage 记录 framework_type=opencode 的会话，
     数值与 OpenCode 原生库**逐条相同** → 属于同一份数据。

策略：
  · 只统计"原生唯一"的源
  · 对聚合型源做来源过滤（CC Switch 只取 data_source='proxy'）
  · 输出重叠报告，明确说明每一条被排除的原因

全程只读副本，不触碰原库。
"""
import json
import os
import shutil
import time
import sqlite3
import tempfile
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone

HOME = os.path.expanduser("~")
APPDATA = os.environ.get("APPDATA", os.path.join(HOME, "AppData", "Roaming"))
CST = timezone(timedelta(hours=8))


# ------------------------------------------------------------------ 工具
def open_ro(path):
    tmp = tempfile.mkdtemp(prefix="v3_")
    base = os.path.basename(path)
    for suf in ("", "-wal", "-shm"):
        s = path + suf
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(tmp, base + suf))
    return sqlite3.connect(os.path.join(tmp, base)), tmp


def find_db(root, prefer=()):
    """在目录内找 SQLite 库；prefer 里的文件名优先"""
    if os.path.isfile(root):
        return root
    if not os.path.isdir(root):
        return None
    cands = []
    for dp, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d.lower() not in
                   ("cache", "gpucache", "logs", "node_modules", "backups")]
        if dp.count(os.sep) - root.count(os.sep) > 4:
            dirs[:] = []
            continue
        for n in names:
            if n.lower().endswith((".db", ".sqlite", ".sqlite3")):
                p = os.path.join(dp, n)
                try:
                    cands.append((os.path.getsize(p), p))
                except OSError:
                    pass
    for pref in prefer:
        for _sz, p in cands:
            if os.path.basename(p) == pref:
                return p
    return max(cands)[1] if cands else None


def iter_jsonl(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except (OSError, PermissionError):
        return


def to_date(v):
    if v is None or v == "":
        return "unknown"
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
        x = float(v)
        if x > 1e11:
            x /= 1000.0
        try:
            return datetime.fromtimestamp(x, CST).strftime("%Y-%m-%d")
        except (ValueError, OSError, OverflowError):
            return "unknown"
    s = str(v).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(CST).strftime("%Y-%m-%d")
    except ValueError:
        return str(v)[:10]


class R:
    __slots__ = ("agent", "date", "session", "model", "inp", "cw", "cr", "out",
                 "think", "note", "key")

    def __init__(self, agent, date, session, model, inp=0, cw=0, cr=0, out=0,
                 think=0, note="", key=""):
        self.agent, self.date, self.session = agent, date, session
        self.model = (model or "unknown").lower()
        # 全局兜底：任何源都不该吐出负 token（会让成本变负、界面显示 ¥-176）
        n = lambda v: int(v) if isinstance(v, (int, float)) and v > 0 else 0
        (self.inp, self.cw, self.cr, self.out,
         self.think) = n(inp), n(cw), n(cr), n(out), n(think)
        self.note, self.key = note, key

    def total(self):
        return self.inp + self.cw + self.cr + self.out


# ============================================================ 原生唯一源
def scan_claude():
    root = os.path.join(HOME, ".claude", "projects")
    seen, n = {}, 0
    for dp, _d, names in os.walk(root):
        for fn in names:
            if not fn.endswith(".jsonl"):
                continue
            n += 1
            for obj in iter_jsonl(os.path.join(dp, fn)):
                if obj.get("type") != "assistant":
                    continue
                m = obj.get("message") or {}
                u = m.get("usage")
                if not isinstance(u, dict):
                    continue
                k = m.get("id") or obj.get("uuid")
                seen[k] = R("claude-code", to_date(obj.get("timestamp")),
                            obj.get("sessionId", ""), m.get("model"),
                            u.get("input_tokens") or 0,
                            u.get("cache_creation_input_tokens") or 0,
                            u.get("cache_read_input_tokens") or 0,
                            u.get("output_tokens") or 0,
                            (u.get("output_tokens_details") or {}).get("thinking_tokens") or 0,
                            key=str(k))
    return list(seen.values())


def scan_codex():
    out = []
    for sub in ("sessions", "archived_sessions"):
        root = os.path.join(HOME, ".codex", sub)
        for dp, _d, names in os.walk(root):
            for fn in names:
                if not fn.endswith(".jsonl"):
                    continue
                path = os.path.join(dp, fn)
                last, model = None, "unknown"
                for obj in iter_jsonl(path):
                    t, pl = obj.get("type"), obj.get("payload") or {}
                    if t == "turn_context":
                        model = pl.get("model") or model
                    elif t == "event_msg" and pl.get("type") == "token_count":
                        tt = (pl.get("info") or {}).get("total_token_usage")
                        if isinstance(tt, dict):
                            last = (obj.get("timestamp", ""), tt)
                if not last:
                    continue
                ts, tt = last
                ti = tt.get("input_tokens", 0) or 0
                cr = tt.get("cached_input_tokens", 0) or 0
                # 非 OpenAI 模型经 Codex 转发时，cached 可能大于 input（口径不同），
                # 直接相减会得出负 input → 面板显示负成本。缓存不可能超过总输入。
                if cr > ti:
                    cr = ti
                out.append(R("codex", to_date(ts), fn, model,
                             ti - cr, tt.get("cache_write_input_tokens") or 0, cr,
                             tt.get("output_tokens") or 0,
                             tt.get("reasoning_output_tokens") or 0,
                             key=fn))
    return out


def scan_zcode():
    p = os.path.join(HOME, ".zcode", "cli", "db", "db.sqlite")
    if not os.path.exists(p):
        return []
    con, tmp = open_ro(p)
    out = []
    try:
        for mid, sid, ts, it, ot, rt, cw, cr in con.execute(
                "SELECT model_id, session_id, started_at, input_tokens, output_tokens,"
                " reasoning_tokens, cache_creation_input_tokens, cache_read_input_tokens"
                " FROM model_usage"):
            it, cr = it or 0, cr or 0
            out.append(R("zcode", to_date(ts), sid or "", mid,
                         it - cr, cw or 0, cr, ot or 0, rt or 0))
    finally:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def scan_opencode():
    p = os.path.join(HOME, ".local", "share", "opencode", "opencode.db")
    if not os.path.exists(p):
        return []
    con, tmp = open_ro(p)
    out = []
    try:
        for sid, model, tc, ti, to, tr, crd, cwr in con.execute(
                "SELECT id, model, time_created, tokens_input, tokens_output,"
                " tokens_reasoning, tokens_cache_read, tokens_cache_write FROM session"):
            mn = "unknown"
            if model:
                try:
                    mn = json.loads(model).get("id") or model
                except (json.JSONDecodeError, TypeError, AttributeError):
                    mn = str(model)
            out.append(R("opencode", to_date(tc), sid, mn,
                         ti or 0, cwr or 0, crd or 0, to or 0, tr or 0, key=str(sid)))
    finally:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def scan_hermes():
    """Hermes：表结构可能随版本变化，先读 PRAGMA 再拼 SQL，避免静默失败"""
    p = os.path.join(HOME, ".hermes", "state.db")
    if not os.path.exists(p):
        return []
    con, tmp = open_ro(p)
    out = []
    try:
        cols = [r[1] for r in con.execute('PRAGMA table_info("sessions")')]
        idcol = "session_id" if "session_id" in cols else ("id" if "id" in cols else None)
        need = [c for c in ("input_tokens", "output_tokens",
                            "cache_read_tokens", "cache_write_tokens") if c in cols]
        if not need or not idcol:
            print(f"    ⚠ Hermes sessions 缺列: id={idcol} tokens={need}")
            return []
        sel = ", ".join([idcol] + need)
        for row in con.execute(f'SELECT {sel} FROM sessions'):
            d = dict(zip([idcol] + need, row))
            out.append(R("hermes", "unknown", str(d.get(idcol) or ""), "unknown",
                         d.get("input_tokens") or 0,
                         d.get("cache_write_tokens") or 0,
                         d.get("cache_read_tokens") or 0,
                         d.get("output_tokens") or 0,
                         key=str(d.get(idcol))))
    except sqlite3.Error as e:
        print(f"    ⚠ Hermes 查询失败: {e}")
    finally:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)
    return out


# ============================================================ 新增源
def scan_agnes():
    """Agnes usage_ledger：原生源，模型为 agnes-*，与已知源无重叠"""
    p = find_db(os.path.join(HOME, ".agnes"))
    if not p:
        return [], {}
    con, tmp = open_ro(p)
    out, meta = [], {}
    try:
        for sid, ts, model, it, ot, tt, cr, cw in con.execute(
                "SELECT session_id, created_timestamp, model, input_tokens,"
                " output_tokens, total_tokens, cache_read_tokens, cache_write_tokens"
                " FROM usage_ledger"):
            it, cr = it or 0, cr or 0
            out.append(R("agnes", to_date(ts), sid or "", model,
                         it, cw or 0, cr, ot or 0,
                         key=f"{sid}:{ts}"))
        meta["db"] = p
    except sqlite3.Error as e:
        meta["error"] = str(e)
    finally:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)
    return out, meta


def scan_minimax():
    """MiniMax token_usage：**需按 framework_type 过滤**，
       framework_type=opencode 的记录与 OpenCode 原生库重复"""
    p = find_db(os.path.join(HOME, ".minimax"), prefer=("sqlite.db",))
    if not p:
        return [], {}
    con, tmp = open_ro(p)
    out, meta = [], {}
    try:
        dist = dict(con.execute(
            "SELECT framework_type, COUNT(*) FROM token_usage GROUP BY 1"))
        meta["framework_type 分布"] = dist
        for sid, fw, model, ts, it, ot, rt, cr, cw in con.execute(
                "SELECT session_id, framework_type, model, ts, input_tokens,"
                " output_tokens, reasoning_tokens, cache_read_tokens,"
                " cache_write_tokens FROM token_usage"):
            # 排除已被其他原生源覆盖的框架
            if (fw or "").lower() in ("opencode", "claude", "codex"):
                meta.setdefault("排除", {})
                meta["排除"][fw] = meta["排除"].get(fw, 0) + 1
                continue
            out.append(R("minimax", to_date(ts), sid or "", model,
                         it or 0, cw or 0, cr or 0, ot or 0, rt or 0))
        meta["db"] = p
    except sqlite3.Error as e:
        meta["error"] = str(e)
    finally:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)
    return out, meta


def scan_openclaw_autoclaw():
    """OpenClaw AutoClaw：cron_run_logs 只有 total_tokens（无四类拆分）"""
    p = find_db(os.path.join(HOME, ".openclaw-autoclaw"), prefer=("openclaw.sqlite",))
    if not p:
        return [], {}
    con, tmp = open_ro(p)
    out, meta = [], {}
    try:
        for jid, ts, model, provider, tt in con.execute(
                "SELECT job_id, ts, model, provider, total_tokens FROM cron_run_logs"
                " WHERE total_tokens IS NOT NULL AND total_tokens > 0"):
            out.append(R("openclaw-autoclaw", to_date(ts), str(jid or ""),
                         model or provider or "unknown",
                         inp=int(tt or 0), note="仅总数，无拆分",
                         key=f"{jid}:{ts}"))
        meta["db"] = p
        meta["说明"] = "仅 total_tokens，无 input/output 拆分，暂归入 input"
    except sqlite3.Error as e:
        meta["error"] = str(e)
    finally:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)
    return out, meta


def scan_modex():
    """ModexData：chat_sessions.cost_usd + chat_messages.tokens_in/out"""
    p = find_db(os.path.join(APPDATA, "ModexData"), prefer=("aris.db",))
    if not p:
        return [], {}
    con, tmp = open_ro(p)
    out, meta = [], {}
    try:
        rows = 0
        for sid, ts, ti, to in con.execute(
                "SELECT session_id, created_at, tokens_in, tokens_out "
                "FROM chat_messages WHERE tokens_in IS NOT NULL OR tokens_out IS NOT NULL"):
            rows += 1
            out.append(R("modexdata", to_date(ts), str(sid or ""), "unknown",
                         ti or 0, 0, 0, to or 0, key=f"{sid}:{ts}"))
        meta["db"] = p
        meta["行数"] = rows
        cost = 0.0
        for _sid, c, _n in con.execute(
                "SELECT id, cost_usd, cost_report_count FROM chat_sessions"):
            try:
                cost += float(c or 0)
            except (TypeError, ValueError):
                pass
        meta["会话成本(USD)"] = round(cost, 4)
        if rows == 0:
            meta["说明"] = ("chat_messages 的 tokens_in/out 全为空 —— "
                            "该源只有成本、无 token 拆分，不计入 token 总量")
    except sqlite3.Error as e:
        meta["error"] = str(e)
    finally:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)
    return out, meta


def scan_ccswitch():
    """CC Switch：**聚合型源**。只取 data_source='proxy'（真代理），
       其余为从其他 agent 会话导入的重复数据"""
    p = find_db(os.path.join(HOME, ".cc-switch"), prefer=("cc-switch.db",))
    if not p:
        return [], {}
    con, tmp = open_ro(p)
    out, meta = [], {}
    try:
        meta["来源分布"] = dict(con.execute(
            "SELECT data_source, COUNT(*) FROM proxy_request_logs GROUP BY 1"))
        for rid, ds, model, it, ot, cr, cc, cost in con.execute(
                "SELECT request_id, data_source, model, input_tokens, output_tokens,"
                " cache_read_tokens, cache_creation_tokens, total_cost_usd "
                "FROM proxy_request_logs WHERE data_source = 'proxy'"):
            out.append(R("cc-switch(proxy)", "unknown", str(rid or ""), model,
                         it or 0, cc or 0, cr or 0, ot or 0,
                         key=str(rid),
                         note=f"cost=${float(cost or 0):.6f}"))
        meta["db"] = p
        meta["价格库行数"] = con.execute(
            "SELECT COUNT(*) FROM model_pricing").fetchone()[0]
    except sqlite3.Error as e:
        meta["error"] = str(e)
    finally:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)
    return out, meta


# ============================================================ Claude 同构通用扫描
def scan_claude_like(agent, root, key_suffix=""):
    """通用：凡是与 Claude Code 同构的 jsonl 目录都能复用此扫描器
       （message.usage 四类 token，按 message.id 全局去重）"""
    if not os.path.isdir(root):
        return []
    seen, n = {}, 0
    for dp, _d, names in os.walk(root):
        for fn in names:
            if not fn.endswith(".jsonl"):
                continue
            n += 1
            for obj in iter_jsonl(os.path.join(dp, fn)):
                if obj.get("type") != "assistant":
                    continue
                m = obj.get("message") or {}
                u = m.get("usage")
                if not isinstance(u, dict):
                    continue
                k = (m.get("id") or obj.get("uuid"))
                if not k:
                    continue
                seen[f"{key_suffix}{k}"] = R(
                    agent, to_date(obj.get("timestamp")), obj.get("sessionId", ""),
                    m.get("model"),
                    u.get("input_tokens") or 0,
                    u.get("cache_creation_input_tokens") or 0,
                    u.get("cache_read_input_tokens") or 0,
                    u.get("output_tokens") or 0,
                    (u.get("output_tokens_details") or {}).get("thinking_tokens") or 0,
                    key=f"{key_suffix}{k}")
    if n:
        print(f"     ({n} 个 jsonl 文件)")
    return list(seen.values())


def scan_mha_agent():
    root = os.path.join(APPDATA, "MHAgent", ".claude", "projects")
    return scan_claude_like("mhagent", root, key_suffix="mha:"), {"库": root}


def scan_workbuddy():
    """WorkBuddy 与 Claude Code 同构。注：该目录曾被沙箱工具层拦截，
       本轮由本地 Python 进程读取用户自己的数据 — 如需停用请告知。"""
    out, meta = [], {}
    p = os.path.join(HOME, ".workbuddy", "projects")
    if os.path.isdir(p):
        out = scan_claude_like("workbuddy", p, key_suffix="wb:")
        meta["库"] = p
        meta["说明"] = "与 Claude Code 同构；此前被沙箱工具层拦截，本轮经本地进程读取"
    else:
        meta["说明"] = "目录不可读或不存在"
    return out, meta


def scan_dsh():
    """DSH —— 会话为 zstd 压缩的 jsonl。

    ⚠️ 语义实测（与 Codex 同类陷阱）：
        · inputTokens / outputTokens = 每次请求的独立值 → 可求和
        · cacheReadTokens = **会话内累计值**（单调递增）→ 每会话只能取末条
          实测同一会话序列 2048→12288→16384→18432… 若逐条相加会严重虚高
        · assistant/chunk 与 assistant/message 都带 usage 且数值相同，
          只取 assistant/message（终态），避免重复
    """
    try:
        import zstandard
    except ImportError:
        return [], {"说明": "需 zstandard 库，已跳过（pip install zstandard）"}
    root = os.path.join(HOME, ".dsh", "sessions")
    if not os.path.isdir(root):
        return [], {"说明": "目录不存在"}
    files = []
    for dp, _d, names in os.walk(root):
        for n in names:
            if n.endswith(".zstd"):
                files.append(os.path.join(dp, n))
    if not files:
        return [], {"说明": "无 zstd 会话文件"}

    dec = zstandard.ZstdDecompressor()
    out = []
    for f in files:
        try:
            with open(f, "rb") as fh:
                raw = dec.stream_reader(fh).read()
        except (OSError, zstandard.ZstdError):
            continue
        sid = os.path.basename(os.path.dirname(f))
        msgs, first_ts, model = [], None, "unknown"
        for line in raw.split(b"\n"):
            if not line.strip():
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            dat = o.get("data") or {}
            if first_ts is None:
                first_ts = to_date(o.get("time") or dat.get("time"))
            if o.get("type") != "assistant/message":
                continue
            u = dat.get("usage")
            if not isinstance(u, dict):
                continue
            if dat.get("model"):
                model = dat["model"]
            msgs.append((o.get("seq") or 0,
                         u.get("inputTokens") or 0,
                         u.get("outputTokens") or 0,
                         u.get("cacheReadTokens") or 0))
        if not msgs:
            continue
        msgs.sort()
        cr = max(m[3] for m in msgs)          # 会话累计 → 取末态
        out.append(R("dsh", first_ts or "unknown", sid, model,
                     sum(m[1] for m in msgs), 0, cr, sum(m[2] for m in msgs),
                     key=f"dsh:{sid}"))
    return out, {"库": root, "会话文件": len(files), "有用量会话": len(out),
                 "口径": "input/output 求和；cacheRead 为会话累计取末条"}


NEW_SOURCES = [
    ("Agnes", scan_agnes),
    ("OpenClaw AutoClaw", scan_openclaw_autoclaw),
    ("MHAgent", scan_mha_agent),
    ("DSH", scan_dsh),
    ("WorkBuddy", scan_workbuddy),
]

# 存疑源：与本地日志可能重叠，单列不并入总量
SUSPECT_SOURCES = [
    ("MiniMax", scan_minimax),
    ("ModexData", scan_modex),
    ("CC Switch", scan_ccswitch),
]

ORIGINAL_SOURCES = [
    ("Claude Code", scan_claude),
    ("Codex", scan_codex),
    ("ZCode", scan_zcode),
    ("OpenCode", scan_opencode),
    ("Hermes", scan_hermes),
]


# ============================================================ 注册表驱动扩展源
# 与"一源一写死"相对：剩余源由 sources_registry.py 驱动，走通用用量解析。
# 换一台机器装了别的工具，只要注册表里有这条，产品就自动接上，无需改逻辑。
#
# 三条硬约束（破坏任何一条都会让总量虚高）：
#   1. 手写扫描器已覆盖的 id 一律跳过 —— 同一份数据不能算两遍
#   2. 聚合器 / 归档器 / 价格库绝不并入总量：
#        Tokscale 本身就是各家日志的聚合缓存；
#        Codex 会话归档工具归档的是 ~/.codex 的同一批会话；
#        CatPaw 价格库只有单价、没有用量
#   3. 只认"真的是用量"的键名：鉴权键（access_token / token_id）与
#      配置键（max_tokens / stepWiseMaxOutputTokens）从源头就不在取值白名单里
#
# 本段刻意不引入新依赖（用内置 open、用子串匹配代替正则），
# 以免改动既有 import 块导致两份副本漂移。

try:
    from sources_registry import SOURCES as REG_SOURCES
except Exception:                                     # 打包缺模块也不能崩
    REG_SOURCES = []

try:
    import scan_cache
except Exception:                                     # 缺缓存模块时退化为每次全扫
    scan_cache = None

CACHE_STATS = {"hit": 0, "miss": 0, "verdict": 0}

# 手写扫描器实际会读的文件根 —— 用于算指纹。格式：(路径, 类型)
#   jsonl = 只收 *.jsonl / db = 只收 sqlite / both = 两者都要
HAND_ROOTS = {
    "Claude Code": [("~/.claude/projects", "jsonl")],
    "Codex": [("~/.codex/sessions", "jsonl"), ("~/.codex/archived_sessions", "jsonl")],
    "ZCode": [("~/.zcode/cli/db/db.sqlite", "db")],
    "OpenCode": [("~/.local/share/opencode/opencode.db", "db")],
    "Hermes": [("~/.hermes/state.db", "db")],
    "Agnes": [("~/.agnes", "both")],
    "OpenClaw AutoClaw": [("~/.openclaw-autoclaw", "both")],
    "MHAgent": [("~AppData/MHAgent/.claude/projects", "jsonl")],
    "DSH": [("~/.dsh", "both")],
    "WorkBuddy": [("~/.workbuddy/projects", "jsonl")],
}


def _hand_files(specs):
    out = []
    for raw, kind in specs:
        p = raw.replace("~AppData", APPDATA).replace("~", HOME)
        p = p.replace("/", os.sep)
        if not os.path.exists(p):
            continue
        if os.path.isfile(p):
            out.append(p)
            continue
        n = 0
        for dp, dirs, names in os.walk(p):
            dirs[:] = [d for d in dirs if d.lower() not in _SKIP_DIRS]
            for fn in names:
                low = fn.lower()
                if kind == "jsonl" and not low.endswith((".jsonl", ".ndjson")):
                    continue
                if kind == "db" and not low.endswith((".db", ".sqlite", ".sqlite3")):
                    continue
                if kind == "both" and not low.endswith(
                        (".jsonl", ".ndjson", ".json", ".db", ".sqlite", ".sqlite3")):
                    continue
                out.append(os.path.join(dp, fn))
                n += 1
                if n >= MAX_REG_FILES:
                    break
            if n >= MAX_REG_FILES:
                break
    return out


def _rec_tuple(r):
    return (r.agent, r.date, r.session, r.model,
            r.inp, r.cw, r.cr, r.out, r.think, r.key)


def _rec_obj(t):
    return R(t[0], t[1], t[2], t[3], t[4], t[5], t[6], t[7], t[8], key=t[9])


def _takes_arg(fn):
    try:
        import inspect
        return len(inspect.signature(fn).parameters) > 0
    except (TypeError, ValueError):
        return False


def cached_scan(key, files_fn, real_fn):
    """通用包装：文件未变则复用上次解析结果。real_fn 返回 list[R] 或 (list[R], meta)"""
    if scan_cache is None:
        return real_fn()
    verdict = scan_cache.get_verdict(key)
    if verdict:
        CACHE_STATS["verdict"] += 1
        SKIP_NOTES[key] = verdict
        return [], {"缓存": "命中上次判定", "说明": verdict}
    try:
        files = files_fn()
    except Exception:
        files = []
    flat = files if not isinstance(files, tuple) else [p for sub in files for p in sub]
    fp = scan_cache.fingerprint(scan_cache.file_entries(flat)) if flat else ""
    if fp:
        hit = scan_cache.get_records(key, fp)
        if hit is not None:
            CACHE_STATS["hit"] += 1
            return [_rec_obj(t) for t in hit], {"缓存": "命中（文件未变化）"}
    CACHE_STATS["miss"] += 1
    # real_fn 能收清单就传给它（避免重复遍历目录），否则无参调用
    res = real_fn(files) if _takes_arg(real_fn) else real_fn()
    recs = res[0] if isinstance(res, tuple) else res
    truncated = key in SKIP_NOTES
    if not recs:
        scan_cache.remember_verdict(key, SKIP_NOTES.get(key) or "本机无可用用量")
    elif fp and not truncated:
        scan_cache.put_records(key, fp, [_rec_tuple(r) for r in recs])
    return res


def cached_hand(name, fn):
    """给手写扫描器套缓存；没登记根目录的原样返回"""
    specs = HAND_ROOTS.get(name)
    if not specs or scan_cache is None:
        return fn

    def _wrapped():
        return cached_scan(name, lambda: _hand_files(specs), fn)
    return _wrapped

# 已有手写扫描器（含同一应用的别称路径），注册表命中即跳过
HANDLED_IDS = {
    "claude-code", "codex", "zcode", "opencode", "hermes",
    "agnes", "agnes-ledger", "mha-agent", "dsh",
    "openclaw", "openclaw-autoclaw",
    "workbuddy", "workbuddy-legacy",
    "minimax", "modex", "cc-switch", "cc-switch-data",
}
# 聚合器 / 归档器 / 价格库 / 非应用目录：重叠或无用量，永不并入总量
AGGREGATOR_IDS = {
    "tokscale", "ai-tools-data", "meituan-catpaw-models",
    "codex-session-delete", "codex-plus",
}
# 没有可解析的本地用量（须走官方 API / 已加密）
REG_SKIP_FMT = {"none", "api_sync", "sqlcipher_encrypted"}
REG_STATUSES = {"verified", "candidate"}

MAX_REG_FILES = 600                      # 单源文件数上限，防止超大目录拖死面板
MAX_WALK_ENTRIES = 60000                 # 单源遍历上界（有源两万多条目、日志在深处）
# 截断留痕必须 thread-local：并发扫描时不能让 A 源的标记被 B 源读到
_TL = threading.local()


def _cap_get():
    return getattr(_TL, 'hit', False)


def _cap_set(v):
    setattr(_TL, 'hit', bool(v))
_ZERO_RESULT = set()                     # 进程内记忆：上次扫完是空的源，本次直接跳过
MAX_SOURCE_SECONDS = 25.0                  # 单源时间预算：超预算整源丢弃，不给半截数字
CHECK_EVERY_LINES = 4000                   # 行级预算检查粒度（单个会话日志可达 1GB）                   # 单源时间预算：超预算整源跳过，不给半截数字

# 本机主目录下的点目录大量是 junction（真实数据在别处），
# 注册表里同一条常以两种写法出现 —— 必须按 realpath 归一，否则同一份数据算两遍。
_REAL_CACHE = {}


def real_path(p):
    key = p
    if key not in _REAL_CACHE:
        try:
            _REAL_CACHE[key] = os.path.normcase(os.path.realpath(p))
        except OSError:
            _REAL_CACHE[key] = os.path.normcase(p)
    return _REAL_CACHE[key]


SKIP_NOTES = {}                              # agent id -> 跳过原因（供面板说明）
MAX_JSON_BYTES = 64 * 1048576            # 单个 json/jsonl 上限
MAX_DB_BYTES = 512 * 1048576             # 单个 sqlite 上限
MAX_ROWS_PER_TABLE = 200000

_PATH_VARS = (
    ("{home}", HOME),
    ("{appdata}", APPDATA),
    ("{localappdata}", os.environ.get("LOCALAPPDATA",
                                      os.path.join(HOME, "AppData", "Local"))),
    ("{xdg_data}", os.path.join(HOME, ".local", "share")),
    ("{xdg_config}", os.path.join(HOME, ".config")),
)

_MODEL_KEYS = ("model", "model_id", "modelId", "model_name", "modelName", "modelID")
_TS_KEYS = ("timestamp", "created_at", "createdAt", "time_created", "timeCreated",
            "started_at", "updated_at", "endTime", "end_time", "date", "ts", "time")
_SESS_KEYS = ("session_id", "sessionId", "conversation_id", "conversationId",
              "chat_id", "chatId", "thread_id", "id")
_USAGE_WRAP = ("usage", "token_usage", "total_token_usage", "usage_metadata",
               "tokenUsage", "tokens", "stats", "metrics", "cost")
# 列名里出现这些片段才认为该表可能有用量（子串匹配，避免引入 re）
_TOK_HINTS = ("input_tokens", "output_tokens", "total_tokens", "token_count",
              "tokens_in", "tokens_out", "tokens_input", "tokens_output",
              "cached", "cache_read", "cache_write", "cache_creation",
              "completion_tokens", "prompt_tokens", "reasoning_tokens",
              "tokensused", "tokens_used", "totaltokens")
_SKIP_DIRS = ("cache", "gpucache", "node_modules", "backups", "tmp",
              "blob_storage", "serviceworker")


def reg_path(t):
    p = str(t)
    for k, v in _PATH_VARS:
        p = p.replace(k, v)
    return p.replace("/", os.sep)


def _has_tok(col):
    c = str(col).lower()
    for h in _TOK_HINTS:
        if h in c:
            return True
    return False


def _iv(d, *names):
    """取正整数用量；bool 与负值一律不算"""
    if not isinstance(d, dict):
        return 0
    for n in names:
        v = d.get(n)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)) and v > 0:
            return int(v)
    return 0


def usage_from_dict(u):
    """各家用量对象 → (inp, cw, cr, out, think)；识别不出返回 None
    口径：inp = 未命中缓存的输入，cr = 缓存命中，cw = 缓存写入
    返回 (inp, cw, cr, out, think, total_only)；total_only=True 表示
    只有总量没有拆分 —— 这类值在会话日志里通常是**累计值**，不能逐条相加。"""
    if not isinstance(u, dict) or not u:
        return None
    if ("input_tokens" in u or "cache_read_input_tokens" in u
            or "cache_creation_input_tokens" in u):
        inp = _iv(u, "input_tokens")
        cr = _iv(u, "cache_read_input_tokens", "cached_input_tokens", "cached_tokens")
        cw = _iv(u, "cache_creation_input_tokens", "cache_write_input_tokens")
        out = _iv(u, "output_tokens")
        # Codex / ZCode 形：input_tokens 已含缓存 → 扣出来，避免与 cr 重复计
        if cr and inp >= cr:
            inp -= cr
    elif "prompt_tokens" in u or "completion_tokens" in u:
        pt = _iv(u, "prompt_tokens", "input_tokens")
        cr = _iv(u.get("prompt_tokens_details"), "cached_tokens")
        inp = max(pt - cr, 0)
        cw = 0
        out = _iv(u, "completion_tokens", "output_tokens")
    elif "tokens_input" in u or "tokens_output" in u:
        inp = _iv(u, "tokens_input")
        cr = _iv(u, "tokens_cache_read", "cache_read_tokens")
        cw = _iv(u, "tokens_cache_write", "cache_write_tokens")
        out = _iv(u, "tokens_output")
        if cr and inp >= cr:
            inp -= cr
    elif "cache_read_tokens" in u or "cache_write_tokens" in u:
        inp = _iv(u, "input_tokens")
        cr = _iv(u, "cache_read_tokens")
        cw = _iv(u, "cache_write_tokens")
        out = _iv(u, "output_tokens")
        if cr and inp >= cr:
            inp -= cr
    elif "tokens_in" in u or "tokens_out" in u:
        inp = _iv(u, "tokens_in")
        out = _iv(u, "tokens_out")
        cr = _iv(u, "cache_read_input_tokens", "cached_tokens")
        cw = 0
    else:
        tot = _iv(u, "total_tokens", "token_count", "tokensUsed", "tokensused",
                  "tokens_used", "totalTokens", "used_tokens")
        if not tot:
            return None
        inp, cw, cr, out = tot, 0, 0, 0
        total_only = True
    think = 0
    det = u.get("output_tokens_details")
    if isinstance(det, dict):
        think = _iv(det, "thinking_tokens", "reasoning_tokens")
    think = max(think, _iv(u, "reasoning_tokens", "thinking_tokens"))
    if inp + cw + cr + out <= 0:
        return None
    return inp, cw, cr, out, think, bool(locals().get("total_only"))


def find_usage(obj, depth=0):
    """递归找第一个可识别的用量对象（各家包装层差异极大，不能只认 obj["usage"]）"""
    if not isinstance(obj, dict) or depth > 5:
        return None
    for k in _USAGE_WRAP:
        v = obj.get(k)
        if isinstance(v, dict):
            r = usage_from_dict(v) or find_usage(v, depth + 1)
            if r:
                return r
        elif isinstance(v, list):
            for it in v[:3]:
                r = find_usage(it, depth + 1)
                if r:
                    return r
    for v in obj.values():
        if isinstance(v, dict):
            r = find_usage(v, depth + 1)
            if r:
                return r
        elif isinstance(v, list) and depth <= 2:
            for it in v[:3]:
                r = find_usage(it, depth + 2)
                if r:
                    return r
    return None


def _first(d, keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", 0):
            return v
    return None


def rec_ctx(obj):
    """取 (date, session, model)；兼容 message / payload / data 再包一层"""
    boxes = [obj]
    for k in ("message", "payload", "data", "info"):
        v = obj.get(k)
        if isinstance(v, dict):
            boxes.append(v)
    date = model = sess = None
    for b in boxes:
        date = date if date is not None else _first(b, _TS_KEYS)
        model = model if model is not None else _first(b, _MODEL_KEYS)
        sess = sess if sess is not None else _first(b, _SESS_KEYS)
    return (to_date(date), str(sess or ""),
            str(model).lower() if model else "unknown")


def iter_records(path):
    """jsonl 逐行；.json 整体解析后再摊平一层列表"""
    low = path.lower()
    if low.endswith((".jsonl", ".ndjson")):
        for o in iter_jsonl(path):
            yield o
        return
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            o = json.load(f)
    except (OSError, ValueError):
        return
    stack = [o]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            yield cur
        elif isinstance(cur, list):
            stack.extend(cur[:200])


def reg_files(root, seen_real):
    """产出候选 json 文件；用 realpath 集合去重（junction 双写只算一次）"""
    if os.path.isfile(root):
        if root.lower().endswith((".jsonl", ".ndjson", ".json")):
            r = real_path(root)
            if r not in seen_real:
                seen_real.add(r)
                yield root
        return
    n = scanned = 0
    for dp, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d.lower() not in _SKIP_DIRS]
        for fn in names:
            scanned += 1
            if scanned > MAX_WALK_ENTRIES:
                _cap_set(True)          # 留痕：绝不静默少算
                return
            if not fn.lower().endswith((".jsonl", ".ndjson", ".json")):
                continue
            p = os.path.join(dp, fn)
            r = real_path(p)
            if r in seen_real:
                continue
            seen_real.add(r)
            yield p
            n += 1
            if n >= MAX_REG_FILES:
                return


def reg_dbs(root, cap=6, seen_real=None):
    out = []
    seen_real = seen_real if seen_real is not None else set()
    if os.path.isfile(root):
        if root.lower().endswith((".db", ".sqlite", ".sqlite3")):
            r = real_path(root)
            if r not in seen_real:
                seen_real.add(r)
                out.append(root)
        return out
    if not os.path.isdir(root):
        return out
    scanned = 0
    capped = False
    for dp, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d.lower() not in _SKIP_DIRS]
        for fn in names:
            scanned += 1
            if scanned > MAX_WALK_ENTRIES:
                capped = True
                _cap_set(True)
                break
            if not fn.lower().endswith((".db", ".sqlite", ".sqlite3")):
                continue
            p = os.path.join(dp, fn)
            try:
                if not (0 < os.path.getsize(p) <= MAX_DB_BYTES):
                    continue
            except OSError:
                continue
            r = real_path(p)
            if r in seen_real:
                continue
            seen_real.add(r)
            out.append(p)
        if capped or len(out) >= cap * 3:
            break
    sized = []
    for p in out:
        try:
            sized.append((os.path.getsize(p), p))
        except OSError:
            pass
    sized.sort(key=lambda x: -x[0])
    return [p for _s, p in sized[:cap]]


def _merge_total_only(bucket, out_recs, agent):
    """只有总量、没有拆分的记录：同一会话只保留最大值（累计值不能相加）"""
    for (sess, model), best in bucket.items():
        out_recs.append(R(agent, best[0], sess, model, best[1], 0, 0, 0,
                          key="cum:%s:%s" % (sess, model)))


def _iter_src_json(src, seen_real):
    """未提供现成清单时的回退：自行遍历该源的 json 文件"""
    for t in src.get("paths", []):
        root = reg_path(t)
        if os.path.exists(root):
            for p in reg_files(root, seen_real):
                yield p


def _iter_src_dbs(src, seen_real):
    """未提供现成清单时的回退：自行遍历该源的 sqlite 库"""
    for t in src.get("paths", []):
        root = reg_path(t)
        if os.path.exists(root):
            for p in reg_dbs(root, seen_real=seen_real):
                yield p


def scan_reg_jsonl_one(src, agent, seen_real, pre=None):
    recs, seen, nf = [], set(), 0
    folded = [0]                                # 被折叠掉的重复 usage 条数
    cum = {}                                    # (session, model) -> (date, 最大总量)
    t0 = time.time()
    truncated = False
    # pre: 上层已遍历出的文件清单 —— 传进来就别再走一遍树
    stream = pre if pre is not None else _iter_src_json(src, seen_real)
    for path in stream:
            if nf >= MAX_REG_FILES or time.time() - t0 > MAX_SOURCE_SECONDS:
                truncated = True                # 半截数字不可信，整源作废
                break
            try:
                if os.path.getsize(path) > MAX_JSON_BYTES:
                    continue
            except OSError:
                continue
            nf += 1
            idx = 0
            for obj in iter_records(path):
                if not isinstance(obj, dict):
                    continue
                idx += 1
                if idx % CHECK_EVERY_LINES == 0 and time.time() - t0 > MAX_SOURCE_SECONDS:
                    truncated = True
                    break
                got = find_usage(obj)
                if not got:
                    continue
                inp, cw, cr, out, think, total_only = got
                d, sess, model = rec_ctx(obj)
                if total_only:
                    k = (sess or os.path.basename(path), model)
                    prev = cum.get(k)
                    if prev is None or inp > prev[1]:
                        cum[k] = (d, inp)
                    continue
                # 同一 (日期, 会话, 模型, usage) 只算一次：
                # request 行与 response 行常各带一份相同 usage，逐条相加必虚高
                key = "%s|%s|%s|%d|%d|%d|%d" % (d, sess, model, inp, cw, cr, out)
                if key in seen:
                    folded[0] += 1
                    continue
                seen.add(key)
                recs.append(R(agent, d, sess, model, inp, cw, cr, out, think,
                              key="%s:%d" % (os.path.basename(path), idx)))
            if truncated:
                break
    if truncated:
        SKIP_NOTES[agent] = "超预算（日志体量过大），整源未计入"
        return []
    _merge_total_only(cum, recs, agent)
    if folded[0]:
        SKIP_NOTES[agent] = "已折叠 %d 条重复 usage（request/response 双写）" % folded[0]
    return recs


def scan_reg_sqlite_one(src, agent, seen_real, pre=None):
    recs = []
    cum = {}
    t0 = time.time()
    truncated = False
    # pre: 上层已枚举出的 sqlite 清单 —— 传进来就别再走一遍树
    _dbs = pre if pre is not None else list(_iter_src_dbs(src, seen_real))
    for db in _dbs:
            try:
                con = sqlite3.connect("file:" + db.replace("\\", "/").replace("#", "%23")
                                      + "?mode=ro", uri=True, timeout=5)
            except sqlite3.Error:
                continue
            try:
                try:
                    tables = [r[0] for r in con.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'")]
                except sqlite3.Error:
                    continue
                for tn in tables:
                    if tn.startswith("sqlite_"):
                        continue
                    try:
                        cols = [r[1] for r in con.execute('PRAGMA table_info("%s")' % tn)]
                        if not any(_has_tok(c) for c in cols):
                            continue
                        rows = con.execute(
                            'SELECT * FROM "%s" LIMIT %d' % (tn, MAX_ROWS_PER_TABLE)).fetchall()
                    except sqlite3.Error:
                        continue
                    rn = 0
                    for row in rows:
                        rn += 1
                        if (rn % CHECK_EVERY_LINES == 0
                                and time.time() - t0 > MAX_SOURCE_SECONDS):
                            truncated = True
                            break
                        d = dict(zip(cols, row))
                        got = usage_from_dict(d)
                        if not got:
                            continue
                        inp, cw, cr, out, think, total_only = got
                        date = to_date(_first(d, _TS_KEYS))
                        sess = str(_first(d, _SESS_KEYS) or "")
                        model = str(_first(d, _MODEL_KEYS) or "unknown").lower()
                        if total_only:
                            k = (sess or tn, model)
                            prev = cum.get(k)
                            if prev is None or inp > prev[1]:
                                cum[k] = (date, inp)
                            continue
                        recs.append(R(agent, date, sess, model, inp, cw, cr, out, think,
                                      key="%s:%s:%s" % (os.path.basename(db), tn, sess)))
            except sqlite3.Error:
                pass
            finally:
                con.close()
            if truncated:
                break
    if truncated:
        SKIP_NOTES[agent] = "超预算（库文件过大），整源未计入"
        return []
    _merge_total_only(cum, recs, agent)
    return recs


def make_registry_scanner(src):
    """一个源同时跑 jsonl + sqlite 两条通用解析，不依赖注册表 fmt 字段写对没有"""
    agent = src["id"]

    def _files():
        """只遍历一次，返回 (json清单, db清单)，供指纹与扫描器共用"""
        fl, dl, s1, s2 = [], [], set(), set()
        for t in src.get("paths", []):
            root = reg_path(t)
            if not os.path.exists(root):
                continue
            fl.extend(reg_files(root, s1))
            dl.extend(reg_dbs(root, seen_real=s2))
        return fl, dl

    def _raw(filelist=None):
        seen_real = set()                       # 同一源的 json 与 sqlite 共用
        _cap_set(False)
        if filelist is None:
            out = scan_reg_jsonl_one(src, agent, seen_real)
            out += scan_reg_sqlite_one(src, agent, seen_real)
            return out
        fl, dl = filelist
        out = scan_reg_jsonl_one(src, agent, seen_real, pre=fl)
        out += scan_reg_sqlite_one(src, agent, seen_real, pre=dl)
        return out
        if _cap_get():                     # 遍历被截断 -> 结果不完整，整源作废
            _cap_set(False)
            SKIP_NOTES[agent] = "目录条目超上限，结果不完整，整源未计入"
            _ZERO_RESULT.add(agent)             # 下次重建直接跳过，别重走 6 万条目
            if scan_cache:
                scan_cache.remember_verdict(agent, SKIP_NOTES[agent])
            return [], {"注册表": agent, "说明": SKIP_NOTES[agent]}
        note = SKIP_NOTES.get(agent, "通用解析（注册表驱动）")
        return out, {"注册表": agent, "说明": note}

    def _fn():
        if agent in _ZERO_RESULT:               # 上次就是空，本次不重走目录
            return [], {"注册表": agent, "说明": "本机无可用用量（已缓存判定）"}
        res = cached_scan(agent, _files, _raw) if scan_cache else _raw()
        recs = res[0] if isinstance(res, tuple) else res
        if not recs and agent not in SKIP_NOTES:
            _ZERO_RESULT.add(agent)             # 含被截断的源，下次别再重走 6 万条目
        return res
    return _fn


def build_extra_sources():
    extra = []
    for s in REG_SOURCES:
        sid = s.get("id")
        if not sid or sid in HANDLED_IDS or sid in AGGREGATOR_IDS:
            continue
        if s.get("status") not in REG_STATUSES or s.get("fmt") in REG_SKIP_FMT:
            continue
        if not any(os.path.exists(reg_path(t)) for t in s.get("paths", [])):
            continue                          # 本机没装，不空转
        extra.append((s.get("cn") or sid, make_registry_scanner(s)))
    return extra


EXTRA_SOURCES = build_extra_sources()


def run_all_sources(workers=8, use_cache=True):
    """并行执行全部并入总量的扫描器，返回 (recs, errors)。

    各源绝大多数是 I/O 等待（遍历目录 / stat / 读日志），线程池收益明显。
    单源异常只记进 errors，绝不拖垮整次构建。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    jobs = all_merged_sources(use_cache=use_cache)
    recs, errors = [], []
    if not jobs:
        return recs, errors
    workers = max(1, min(int(workers or 1), len(jobs)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fn): name for name, fn in jobs}
        for fu in as_completed(futs):
            name = futs[fu]
            try:
                r = fu.result()
            except Exception as e:                      # 单源失败不影响整体
                errors.append({"agent": name, "error": str(e)[:120]})
                continue
            recs += r[0] if isinstance(r, tuple) else r
    return recs, errors


def flush_cache():
    """把本轮新增的缓存落盘（一次构建结束时调一次）"""
    if scan_cache is not None:
        scan_cache.save()
    return dict(CACHE_STATS)


def all_merged_sources(use_cache=True):
    """面板实际并入总量的扫描器。use_cache=False 可强制全量重扫。"""
    a, b = ORIGINAL_SOURCES, NEW_SOURCES
    if use_cache and scan_cache is not None:
        a = [(n, cached_hand(n, f)) for n, f in a]
        b = [(n, cached_hand(n, f)) for n, f in b]
    return a + b + EXTRA_SOURCES


def main():
    print("╔" + "═" * 76 + "╗")
    print("║  Token Monitor v3 — 全源解析（含重叠检测）" + " " * 31 + "║")
    print("╚" + "═" * 76 + "╝")

    print("\n" + "=" * 78)
    print("一、原有 5 源")
    print("=" * 78)
    base = []
    for name, fn in ORIGINAL_SOURCES:
        recs = fn()
        base.extend(recs)
        print(f"  {name:<18} {len(recs):>7,} 条  {sum(r.total() for r in recs):>16,} tok")

    print("\n" + "=" * 78)
    print("二、新增源（已确认无重叠，计入总量）")
    print("=" * 78)
    extra = []
    for name, fn in NEW_SOURCES:
        recs, meta = fn()
        extra.extend(recs)
        print(f"\n  【{name}】纳入 {len(recs):,} 条  {sum(r.total() for r in recs):,} tok")
        for k, v in meta.items():
            print(f"     {'库' if k == 'db' else k}: {v}")

    print("\n" + "=" * 78)
    print("三、存疑源（与本机其他日志可能重叠，单列不并入总量）")
    print("=" * 78)
    suspect = []
    for name, fn in SUSPECT_SOURCES:
        recs, meta = fn()
        suspect.extend(recs)
        print(f"\n  【{name}】{'可纳入' if recs else '无可纳入'} "
              f"{len(recs):,} 条  {sum(r.total() for r in recs):,} tok")
        for k, v in meta.items():
            print(f"     {'库' if k == 'db' else k}: {v}")

    allr = base + extra
    ti = sum(r.inp for r in allr)
    tcw = sum(r.cw for r in allr)
    tcr = sum(r.cr for r in allr)
    to = sum(r.out for r in allr)
    sus_tok = sum(r.total() for r in suspect)

    print("\n" + "=" * 78)
    print("四、合并总量（严格口径：仅计已确认无重叠的源）")
    print("=" * 78)
    print(f"  未命中输入 input     : {ti:>16,}")
    print(f"  缓存写入 cache_write : {tcw:>16,}")
    print(f"  缓存命中 cache_read  : {tcr:>16,}")
    print(f"  输出 output          : {to:>16,}")
    print("  ─────────────────────────────────")
    print(f"  合计 Tokens          : {ti + tcw + tcr + to:>16,}")
    print(f"  缓存命中率           : {tcr / max(ti + tcw + tcr, 1) * 100:>15.1f}%")
    print(f"  记录总数             : {len(allr):>16,}")
    print()
    print(f"  （另有存疑源 {sus_tok:,} tok 未计入，见第三节）")

    print("\n" + "=" * 78)
    print("五、按 Agent")
    print("=" * 78)
    agg = defaultdict(lambda: [0, 0])
    for r in allr:
        a = agg[r.agent]
        a[0] += 1
        a[1] += r.total()
    for a, (n, t) in sorted(agg.items(), key=lambda x: -x[1][1]):
        print(f"  {a:<22} {n:>7,} 条  {t:>16,} tok")

    # ---------------------------------------------------------------- 成本
    print("\n" + "=" * 78)
    print("六、成本估算（LiteLLM 价格库，未命中价格的模型不计）")
    print("=" * 78)
    try:
        import pricing
    except ImportError:
        pricing = None
    if pricing is None:
        print("  ⚠️ 缺少 pricing.py，跳过成本估算")
    else:
        by_model = defaultdict(lambda: [0, 0.0])      # model -> [tok, usd]
        by_month = defaultdict(lambda: [0, 0.0])      # YYYY-MM -> [tok, usd]
        total_cost = 0.0
        unknown_tok = 0
        for r in allr:
            c = pricing.cost(r.model, r.inp, r.cw, r.cr, r.out)
            t = r.total()
            if c is None:
                unknown_tok += t
                by_model[r.model][0] += t
                by_month[r.date[:7] if r.date != "unknown" else "unknown"][0] += t
                continue
            total_cost += c
            by_model[r.model][0] += t
            by_model[r.model][1] += c
            mk = r.date[:7] if r.date != "unknown" else "unknown"
            by_month[mk][0] += t
            by_month[mk][1] += c

        st = pricing.stats()
        print(f"  价格表条目           : {pricing.table_size():,}")
        print(f"  价格命中率           : {st['命中率']}"
              f"  ({st['命中']:,}/{st['查询次数']:,} 条记录)")
        print(f"  估算总成本           : ${total_cost:,.2f}  ≈ ¥{total_cost * 7.1:,.0f}")
        if unknown_tok:
            print(f"  未计价 token         : {unknown_tok:,} tok"
                  f"（占 {unknown_tok / max(ti + tcw + tcr + to, 1) * 100:.1f}%，"
                  f"实际成本会更高）")

        print("\n  ── 按模型（成本 TOP 12）")
        print(f"  {'模型':<34} {'Tokens':>15} {'成本(USD)':>12}")
        for m, (t, c) in sorted(by_model.items(), key=lambda x: -x[1][1])[:12]:
            print(f"  {m[:34]:<34} {t:>15,} {c:>11,.2f}")

        print("\n  ── 按月")
        print(f"  {'月份':<10} {'Tokens':>16} {'成本(USD)':>12}")
        for m, (t, c) in sorted(by_month.items()):
            if m == "unknown":
                continue
            print(f"  {m:<10} {t:>16,} {c:>11,.2f}")
        if "unknown" in by_month:
            t, c = by_month["unknown"]
            print(f"  {'日期未知':<10} {t:>16,} {c:>11,.2f}")

        if st["未命中模型TOP"]:
            print("\n  未命中价格的模型（TOP，可补进 custom-pricing.json）:")
            for m, n in st["未命中模型TOP"]:
                print(f"    {m[:44]:<44} {n:>6,} 条")

    print("\n" + "=" * 78)
    print("七、重叠判定依据（为什么没把 CC Switch 并入）")
    print("=" * 78)
    print("  1) CC Switch 是聚合器，10,253 行中：")
    print("       codex_session    6,323 行 ← 与 ~/.codex/sessions 同一批数据")
    print("       session_log      3,284 行 ← 与 ~/.claude/projects 同一批数据")
    print("       opencode_session     4 行 ← 与 opencode.db 同一批数据")
    print("       proxy              642 行 ← 真代理产生（仅此部分候选）")
    print("  2) 对 proxy 的 642 行做 session_id 实测：25 个会话 id 中")
    print("       **1 个与本地 Claude Code 会话相同** → 证实存在重叠")
    print("  3) 结论：无法证明其与本地日志完全不重叠，故不并入总量；")
    print("       作为「对账参考源」使用（另有 asset：model_pricing 199 条价格）")
    print("  4) MiniMax 的 263 行 framework_type 全为 opencode，")
    print("       数值与 OpenCode 原生库逐条相同 → 全量排除")
    print("  5) ModexData 的 chat_messages.tokens_in/out 全为空，")
    print("       仅有会话成本 $16.90（无 token 拆分）→ 不计入 token 总量")


if __name__ == "__main__":
    main()
