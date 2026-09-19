# -*- coding: utf-8 -*-
"""扫描结果持久缓存 —— 解决"每次重建都从零重读全部日志"

核心观察：agent 日志是 append-only 的，绝大多数文件在两次扫描之间根本没变。
45s 里真正必要的工作只占一小部分。

两级缓存：
  1. 源级指纹：某源候选文件集合的 (realpath, mtime_ns, size) 聚合哈希不变
     → 直接复用上次解析出的记录，跳过全部解析
  2. 判定缓存：上次扫完是 0 结果、或被截断作废的源
     → 跨进程也直接跳过（原来只在进程内有效，重启就重新走一遍 6 万条目）

缓存文件放在 %LOCALAPPDATA%\\TokenMonitor，打包版与开发版共用。
"""
import hashlib
import json
import os
import sys
import tempfile
import threading
import time

_LOCK = threading.Lock()
_DIR = None
_PATH = None
_MEM = None                      # dict 或 None（未加载）
LAST_ERROR = [None]              # 最近一次落盘失败原因（供面板显示）
_FMT = 3                         # 结构版本；改记录字段时 +1 让旧缓存自动作废

# (agent, date, session, model, inp, cw, cr, out, think, key)
FIELDS = 10


def cache_dir():
    global _DIR, _PATH
    if _DIR is None:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        cand = os.path.join(base, "TokenMonitor")
        try:
            os.makedirs(cand, exist_ok=True)
        except OSError:
            cand = os.path.expanduser("~")
        # 必须 realpath：逻辑路径与真实路径可能不同卷，
        # 那样 os.replace 会报 WinError 17（跨磁盘驱动器），缓存永远写不进去
        try:
            cand = os.path.realpath(cand)
        except OSError:
            pass
        _DIR = cand
        _PATH = os.path.join(_DIR, "scan-cache.json")
    return _DIR


def _load():
    global _MEM
    cache_dir()                       # 确保 _PATH 已初始化（否则 open(None) 直接炸）
    if _MEM is not None:
        return _MEM
    data = {"fmt": _FMT, "sources": {}, "verdicts": {}}
    try:
        with open(_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict) and raw.get("fmt") == _FMT:
            data["sources"] = raw.get("sources") or {}
            data["verdicts"] = raw.get("verdicts") or {}
    except (OSError, ValueError):
        pass
    _MEM = data
    return _MEM


def fingerprint(entries):
    """entries: 可迭代的 (path, mtime_ns, size)。顺序无关，内容敏感。"""
    h = hashlib.sha1()
    for p, mt, sz in sorted(entries):
        h.update(("%s\x1f%d\x1f%d\n" % (p, mt, sz)).encode("utf-8", "replace"))
    return h.hexdigest()


def file_entries(paths):
    """把文件路径列表转成指纹素材；stat 失败的文件忽略但计入存在性"""
    out = []
    for p in paths:
        try:
            st = os.stat(p)
        except OSError:
            out.append((str(p), -1, -1))
            continue
        out.append((os.path.normcase(os.path.realpath(p)),
                    getattr(st, "st_mtime_ns", int(st.st_mtime)), int(st.st_size)))
    return out


def get_records(agent, fp):
    """指纹命中则返回记录元组列表，否则 None"""
    with _LOCK:
        d = _load()["sources"].get(agent)
        if d and d.get("fp") == fp:
            return [tuple(x) for x in d.get("recs") or []]
    return None


def put_records(agent, fp, recs):
    """recs: 元组列表 (agent,date,session,model,inp,cw,cr,out,think,key)"""
    with _LOCK:
        d = _load()
        d["sources"][agent] = {
            "fp": fp,
            "saved_at": int(time.time()),
            "recs": [list(r[:FIELDS]) for r in recs],
        }
        d["verdicts"].pop(agent, None)


def remember_verdict(agent, note):
    """记住"这个源是空的/被截断"，跨进程生效"""
    with _LOCK:
        d = _load()
        d["verdicts"][agent] = {"note": note, "saved_at": int(time.time())}
        d["sources"].pop(agent, None)


def get_verdict(agent):
    with _LOCK:
        v = _load()["verdicts"].get(agent)
        return (v or {}).get("note") if v else None


def forget(agent):
    with _LOCK:
        d = _load()
        d["sources"].pop(agent, None)
        d["verdicts"].pop(agent, None)


def save():
    with _LOCK:
        d = _load()
        payload = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
        fd, tmp = tempfile.mkstemp(prefix="sc-", dir=cache_dir())
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp, _PATH)
        except OSError as e:
            LAST_ERROR[0] = "replace 失败: %s" % e
            try:
                os.remove(tmp)
            except OSError:
                pass
            try:                    # 放弃原子性兜底直写，至少别让缓存完全不落盘
                with open(_PATH, "w", encoding="utf-8") as f:
                    f.write(payload)
                LAST_ERROR[0] = None
                return True
            except OSError as e2:
                LAST_ERROR[0] = "直写也失败: %s" % e2
                return False
    return True


def stats():
    d = _load()
    n = sum(len(v.get("recs") or []) for v in d["sources"].values())
    try:
        size = os.path.getsize(_PATH)
    except (OSError, TypeError):
        size = 0
    return {"sources": len(d["sources"]), "verdicts": len(d["verdicts"]),
            "records": n, "bytes": size, "path": _PATH}
