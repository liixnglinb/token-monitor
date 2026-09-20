# -*- coding: utf-8 -*-
"""面板后台刷新 + 设置持久化

设计要点（这是"自动几分钟刷新"能成立的前提）：
  · /api/summary 永远立即返回上一次的好数据，绝不在请求线程里扫描
  · 扫描在单个后台线程中串行执行；同一时刻最多一个构建在跑（busy 合并请求）
  · 自动刷新间隔可配置并持久化；0 = 关闭自动刷新
  · 软件更新检查走同样的缓存化套路，/api/version 不再被网络阻塞

被 server.py（打包版）与 webapp/app.py（开发版）共用，避免两份逻辑漂移。
"""
import json
import os
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))

DEFAULTS = {
    "refresh_minutes": 5,        # 数据自动重扫间隔；0 = 关闭
}
# 软件更新检查不再开放配置（产品决策，UI 不暴露任何"何时检测更新"项）：
# 启动即检查一次，此后固定每 30 分钟一次。老 settings.json 里遗留的
# auto_update_check / update_check_minutes 键会被 load_settings 直接丢弃。
UPDATE_CHECK_MINUTES = 30
MIN_REFRESH = 1
MAX_REFRESH = 720


def settings_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "TokenMonitor")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        d = os.path.expanduser("~")
    return d


def _sfile():
    return os.path.join(settings_dir(), "settings.json")


def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(_sfile(), "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            s.update({k: v for k, v in raw.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return _clamp(s)


def _clamp(s):
    try:
        m = int(s.get("refresh_minutes", DEFAULTS["refresh_minutes"]))
    except (TypeError, ValueError):
        m = DEFAULTS["refresh_minutes"]
    s["refresh_minutes"] = 0 if m <= 0 else max(MIN_REFRESH, min(MAX_REFRESH, m))
    return s


def save_settings(s):
    s = _clamp(dict(s))
    payload = json.dumps(s, ensure_ascii=False, indent=2)
    d = settings_dir()
    try:
        fd, tmp = tempfile.mkstemp(prefix="st-", dir=d)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, _sfile())
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return s


class Refresher:
    """后台刷新调度器。build_fn() 返回可序列化的 dict。"""

    def __init__(self, build_fn, version_fn=None):
        self._build = build_fn
        self._version_fn = version_fn
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._data = None
        self._built_at = None
        self._error = None
        self._busy = False
        self._dirty = False
        self._version = None
        self._version_at = None
        self.settings = load_settings()
        self._stop = threading.Event()
        self._thread = None

    # ---------- 生命周期 ----------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="tm-refresher")
        self._thread.start()

    def _loop(self):
        while not self._stop.is_set():
            with self._lock:
                rm = self.settings["refresh_minutes"]
                dirty = self._dirty
            # 进入软件必须自动扫描一次（_built_at 为空），不受自动刷新开关影响；
            # 开关只控制后续的周期性重扫与脏标记重扫
            due_data = self._built_at is None or (
                rm > 0 and (dirty
                or (time.time() - self._last_build_ts()) >= rm * 60))
            # 更新检查固定策略：启动即查（_version_at 为空）+ 每 30 分钟，不受设置影响
            due_ver = (self._version_fn is not None and (
                self._version_at is None
                or (time.time() - self._version_at) >= UPDATE_CHECK_MINUTES * 60))
            if not due_data and not due_ver:
                self._stop.wait(5.0)
                continue
            if due_ver:
                self._do_version()
            if due_data:
                self.refresh(force=False)
            self._stop.wait(2.0)

    def _last_build_ts(self):
        return getattr(self, "_ts", 0.0)

    # ---------- 对外 ----------
    def snapshot(self):
        """立即返回上次结果；没有结果时在后台发起首扫并返回 building 占位"""
        with self._lock:
            if self._data is not None:
                return self._data, self._built_at, self._error, self._busy
            self._dirty = True
        return ({"building": True, "refresh_minutes": self.settings["refresh_minutes"]},
                None, self._error, True)

    def refresh(self, force=True):
        """非阻塞：有扫描在跑就只标脏，跑完自动再扫一次"""
        with self._lock:
            if self._busy:
                self._dirty = True
                return {"ok": True, "started": False, "queued": True,
                        "built_at": self._built_at}
            self._dirty = False
        t = threading.Thread(target=self._do_build, daemon=True, name="tm-build")
        t.start()
        return {"ok": True, "started": True, "queued": False, "built_at": self._built_at}

    def set_settings(self, patch):
        with self._lock:
            self.settings.update({k: v for k, v in (patch or {}).items()
                                  if k in DEFAULTS})
            self.settings = _clamp(self.settings)
            self._dirty = True
        save_settings(self.settings)
        return dict(self.settings)

    def version(self):
        """返回缓存的版本信息；为空时在后台发起一次检查"""
        with self._lock:
            if self._version is not None:
                return self._version
            has_fn = self._version_fn is not None
        if has_fn:
            threading.Thread(target=self._do_version, daemon=True).start()
        return {"version": None, "latest": None, "has_update": False,
                "checking": has_fn}

    # ---------- 内部 ----------
    def _do_build(self):
        with self._lock:
            self._busy = True
        err = None
        try:
            data = self._build()
        except Exception as e:                          # 扫描失败要保留旧数据
            data, err = None, str(e)[:200]
        with self._lock:
            if data is not None:
                self._data = data
                self._built_at = datetime.now(CST).isoformat(timespec="seconds")
                self._ts = time.time()
                self._error = None
            else:
                self._error = err
            self._busy = False
            if self._dirty:                             # 期间有人要过新数据
                self._dirty = False

    def _do_version(self):
        if not self._version_fn:
            return
        try:
            v = self._version_fn()
        except Exception as e:
            v = {"error": str(e)[:120]}
        with self._lock:
            self._version = v
            self._version_at = time.time()

    def status(self):
        with self._lock:
            return {
                "built_at": self._built_at,
                "busy": self._busy,
                "queued": self._dirty,
                "error": self._error,
                "settings": dict(self.settings),
                "has_data": self._data is not None,
            }
