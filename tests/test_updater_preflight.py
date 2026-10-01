# -*- coding: utf-8 -*-
"""更新预检（_preflight_new_exe / --selfcheck 防砖机制）单元测试。

背景：安全软件对「刚被自更新替换的无签名 exe」首次启动会深度扫描，
可能拦掉 _MEI 解压目录里的 python3xx.dll，LoadLibrary 报
「找不到指定的模块」。预检要求在替换当前 exe 之前新版先试运行成功，
失败即中止更新、保留当前版本。这里用假进程对象验证预检的重试、
超时、中止与残留清理逻辑，不依赖真实 PyInstaller exe。
"""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import updater


def sandbox_open(base, rel, mode):
    """在 base 沙箱内打开 rel 路径：规范化并校验不越界（禁 ../ 穿越）。"""
    root = os.path.realpath(base)
    p = os.path.realpath(os.path.join(root, rel))
    if os.path.commonpath([root, p]) != root:
        raise ValueError("路径越出沙箱: %s" % p)
    return open(p, mode)


class _FakeProc:
    """替代 subprocess.Popen 返回值的假进程。code 为 "timeout" 时模拟
    引导失败弹出的模态框一直没人点（wait 超时）。"""

    def __init__(self, code):
        self._code = code
        self.killed = False
        self.wait_timeout_used = None

    def wait(self, timeout=None):
        self.wait_timeout_used = timeout
        if self._code == "timeout" and not self.killed:
            raise subprocess.TimeoutExpired(cmd="probe", timeout=timeout)
        return 1 if self._code == "timeout" else self._code

    def kill(self):
        self.killed = True


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tm-preflight-test-")
        self.addCleanup(self.tmp.cleanup)
        self.base = os.path.realpath(self.tmp.name)

        # 造一个假的暂存更新包 + 假安装目录（含当前 exe）
        os.makedirs(os.path.join(self.base, "app"), exist_ok=True)
        self.exe = os.path.join(self.base, "app", "TokenMonitor.exe")
        with sandbox_open(self.base, os.path.join("app", "TokenMonitor.exe"),
                          "wb") as f:
            f.write(b"old-exe")
        self.staged = os.path.join(self.base, "staged.bin")
        with sandbox_open(self.base, "staged.bin", "wb") as f:
            f.write(b"new-exe")

        # 把工作目录整体指到临时目录，避免测试碰真实安装位置
        patcher = mock.patch.object(updater, "_base",
                                    return_value=(self.base, self.exe))
        patcher.start()
        self.addCleanup(patcher.stop)
        # 缩短重试节奏，测试不必等 8 秒
        patcher2 = mock.patch.object(updater, "_PREFLIGHT_RETRY_GAP", 0.0)
        patcher2.start()
        self.addCleanup(patcher2.stop)

    def _probe_path(self):
        return os.path.join(self.base, "app", "TokenMonitor.preflight.exe")

    def test_success_first_attempt(self):
        proc = _FakeProc(0)
        with mock.patch.object(updater.subprocess, "Popen",
                               return_value=proc) as popen:
            updater._preflight_new_exe(self.staged)
        popen.assert_called_once()
        args = popen.call_args[0][0]
        self.assertEqual(args[1], updater._SELFCHECK_FLAG)
        self.assertEqual(os.path.normcase(args[0]),
                         os.path.normcase(self._probe_path()))
        self.assertEqual(proc.wait_timeout_used, updater._PREFLIGHT_WAIT)
        # 预检探针文件用完必须清理，不留安装目录垃圾
        self.assertFalse(os.path.exists(self._probe_path()))

    def test_retries_then_succeeds(self):
        """第 1 次被拦（退出码 1）、第 2 次放行 —— 预检应重试而不是直接放弃。"""
        procs = [_FakeProc(1), _FakeProc(0)]
        with mock.patch.object(updater.subprocess, "Popen",
                               side_effect=procs):
            updater._preflight_new_exe(self.staged)
        self.assertFalse(procs[0].killed)
        self.assertFalse(os.path.exists(self._probe_path()))

    def test_aborts_after_max_attempts_and_keeps_old_version(self):
        procs = [_FakeProc(1) for _ in range(updater._PREFLIGHT_ATTEMPTS)]
        with mock.patch.object(updater.subprocess, "Popen",
                               side_effect=procs):
            with self.assertRaisesRegex(RuntimeError, "预检失败"):
                updater._preflight_new_exe(self.staged)
        self.assertFalse(os.path.exists(self._probe_path()))
        # 关键防砖断言：预检失败时当前 exe 与暂存包都原样保留
        with sandbox_open(self.base,
                          os.path.join("app", "TokenMonitor.exe"),
                          "rb") as f:
            self.assertEqual(f.read(), b"old-exe")
        with sandbox_open(self.base, "staged.bin", "rb") as f:
            self.assertEqual(f.read(), b"new-exe")

    def test_dialog_timeout_kills_and_aborts(self):
        """引导失败弹框没人点 → 超时 kill → 报错信息里带「超时」。"""
        proc = _FakeProc("timeout")
        with mock.patch.object(updater.subprocess, "Popen", return_value=proc):
            with mock.patch.object(updater, "_PREFLIGHT_ATTEMPTS", 1):
                with self.assertRaisesRegex(RuntimeError, "超时"):
                    updater._preflight_new_exe(self.staged)
        self.assertTrue(proc.killed)

    def test_apply_staged_never_touches_install_when_preflight_fails(self):
        """防砖核心：预检不通过时，apply_staged 必须在写更新脚本/杀进程之前中止。"""
        bat_path = os.path.join(tempfile.gettempdir(),
                                "tokenmonitor-update.bat")
        if os.path.exists(bat_path):        # 清掉历史运行残留，保证断言有效
            os.remove(bat_path)
        spawned = []

        def _no_spawn(*a, **kw):
            spawned.append(a)
            raise AssertionError("预检失败后仍尝试执行更新脚本")

        with mock.patch.object(updater, "_preflight_new_exe",
                               side_effect=RuntimeError("预检失败")), \
             mock.patch.object(updater.subprocess, "Popen",
                               side_effect=_no_spawn):
            with self.assertRaisesRegex(RuntimeError, "预检失败"):
                updater.apply_staged(tmp=self.staged)
        self.assertEqual(spawned, [])
        self.assertFalse(os.path.exists(bat_path))

    def test_apply_staged_preflight_success_reaches_bat(self):
        """预检通过 → 流程照旧走到写更新脚本并启动（用假 Popen 截住）。"""
        bat_path = os.path.join(tempfile.gettempdir(),
                                "tokenmonitor-update.bat")
        if os.path.exists(bat_path):
            os.remove(bat_path)
        spawned = []

        def _fake_popen(cmd, **kw):
            spawned.append(cmd)
            return _FakeProc(0)

        try:
            with mock.patch.object(updater.subprocess, "Popen",
                                   side_effect=_fake_popen):
                updater.apply_staged(tmp=self.staged)
            # 两次 spawn：第 1 次是预检探针（--selfcheck），第 2 次是更新脚本
            self.assertEqual(len(spawned), 2)
            self.assertEqual(spawned[1][0], "cmd")
            self.assertIn("tokenmonitor-update.bat", " ".join(spawned[1]))
            # bat 文件确实生成在临时目录
            self.assertTrue(os.path.exists(bat_path))
        finally:
            if os.path.exists(bat_path):
                os.remove(bat_path)


if __name__ == "__main__":
    unittest.main()
