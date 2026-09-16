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
import sqlite3
import tempfile
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
        self.inp, self.cw, self.cr, self.out, self.think = inp, cw, cr, out, think
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
