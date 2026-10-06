"""设置面：钳制规则与非法输入的契约。

规则本身：0 = 关闭自动刷新，只能由界面上那个开关明确表达；
负数 / 垃圾输入不得顺手关掉自动刷新（以前 -5 → 0，用户只是填错个数）。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import refresher as RF


class ClampTests(unittest.TestCase):
    def cl(self, v):
        return RF._clamp({"refresh_minutes": v})["refresh_minutes"]

    def test_zero_means_off(self):
        self.assertEqual(0, self.cl(0))
        self.assertEqual(0, self.cl("0"))

    def test_negative_falls_to_minimum_not_off(self):
        self.assertEqual(RF.MIN_REFRESH, self.cl(-5))
        self.assertEqual(RF.MIN_REFRESH, self.cl(-999999))

    def test_too_large_is_capped(self):
        self.assertEqual(RF.MAX_REFRESH, self.cl(10 ** 9))

    def test_garbage_uses_default(self):
        for bad in ("abc", None, [], {}, "3.5.1"):
            self.assertEqual(RF.DEFAULTS["refresh_minutes"], self.cl(bad), bad)

    def test_numeric_string_and_normal_range(self):
        self.assertEqual(30, self.cl("30"))
        self.assertEqual(5, self.cl(5))
        self.assertEqual(RF.MAX_REFRESH, self.cl(RF.MAX_REFRESH))


class SettingsApiTests(unittest.TestCase):
    """只测契约（状态码 / ok 字段），不依赖真实扫描结果。"""

    def setUp(self):
        try:
            from fastapi.testclient import TestClient
        except Exception as e:                    # 需要 httpx（见 requirements-dev.txt）
            raise unittest.SkipTest("TestClient 不可用: %s" % e)
        import server
        # base_url 必须是 127.0.0.1：服务端有本地来源守卫（防 DNS rebinding / CSRF），
        # TestClient 默认的 testserver 会被直接 403 —— 那条守卫本身也是要保住的行为。
        self.client = TestClient(server.app, base_url="http://127.0.0.1")

    def test_bad_json_is_rejected_not_silently_accepted(self):
        r = self.client.post("/api/settings", content=b"not json",
                             headers={"Content-Type": "application/json"})
        self.assertEqual(400, r.status_code)
        self.assertFalse(r.json()["ok"])

    def test_non_object_body_rejected(self):
        r = self.client.post("/api/settings", json=[1, 2, 3])
        self.assertEqual(400, r.status_code)

    def test_unknown_keys_dropped_and_value_clamped(self):
        r = self.client.post("/api/settings",
                             json={"refresh_minutes": -3, "evil": "<script>"})
        self.assertEqual(200, r.status_code)
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertEqual(RF.MIN_REFRESH, body["settings"]["refresh_minutes"])
        self.assertNotIn("evil", body["settings"])

    def test_summary_shape_before_any_data(self):
        """首扫期间也必须是一个前端能直接消费的对象，而不是 500。"""
        r = self.client.get("/api/summary")
        self.assertEqual(200, r.status_code)
        d = r.json()
        self.assertTrue(d.get("building") or isinstance(d.get("matrix"), list), str(d)[:120])


if __name__ == "__main__":
    unittest.main()
