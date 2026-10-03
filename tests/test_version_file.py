# -*- coding: utf-8 -*-
"""版本号读取与比较的单元测试。

背景：`version.txt` 可能带 UTF-8 BOM —— PowerShell 5.1 的
`Set-Content -Encoding utf8` 会写 BOM，CI 里也是这么写版本号的。
不剥 BOM 时 `_parse` 会抛 ValueError，落进 `local != latest` 分支，
于是"已经是最新版"也会显示「⬆ 更新到 vX.Y.Z」，点下去还会白下载一遍。
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import updater


class VersionFileTest(unittest.TestCase):
    def _with_version(self, raw: bytes) -> str:
        folder = tempfile.mkdtemp(prefix="tm-version-")
        with open(os.path.join(folder, "version.txt"), "wb") as handle:
            handle.write(raw)
        with mock.patch.object(updater, "_base", return_value=(folder, None)):
            return updater.local_version()

    def test_plain_version(self):
        self.assertEqual(self._with_version(b"1.9.13"), "1.9.13")

    def test_utf8_bom_version(self):
        self.assertEqual(self._with_version(b"\xef\xbb\xbf1.9.13"), "1.9.13")

    def test_utf8_bom_with_newline_and_v(self):
        self.assertEqual(self._with_version(b"\xef\xbb\xbfv1.9.13\r\n"), "1.9.13")

    def test_missing_file_falls_back(self):
        with mock.patch.object(updater, "_base", return_value=("/nonexistent-dir", None)):
            self.assertEqual(updater.local_version(), "0.0.0")

    def test_parse_tolerates_bom_and_v(self):
        self.assertEqual(updater._parse("\ufeffv1.9.13"), (1, 9, 13))

    def test_same_version_is_not_an_update(self):
        # 关键回归：BOM 版本号与最新版相同 → 不应提示更新
        local = self._with_version(b"\xef\xbb\xbf1.9.13")
        self.assertFalse(updater.is_newer("1.9.13", local))

    def test_newer_version_is_an_update(self):
        local = self._with_version(b"\xef\xbb\xbf1.9.13")
        self.assertTrue(updater.is_newer("1.9.14", local))

    def test_non_semver_local_falls_back_to_inequality(self):
        local = self._with_version(b"dev")
        self.assertTrue(updater.is_newer("1.9.13", local))


if __name__ == "__main__":
    unittest.main()
