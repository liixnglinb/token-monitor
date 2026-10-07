# -*- coding: utf-8 -*-
"""阿里 Qoder（Qoder CN）转录的接入口径。

回归背景（2026-10-07）：注册表里 qoder 的 paths 从未包含
`{home}/.qoder-cn/projects` —— 真实转录一直在那里，面板却显示这个源没用量。
接上之后又踩到第二个坑：该源用的是 Anthropic 的字段名，语义却是 OpenAI 的
（input_tokens 已含 cache_read_input_tokens，实测 context_usage_ratio×1e6
恒等于 input_tokens），照 Anthropic 口径相加会把 528M 报成 1,045M。
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import probe_v3_allsources as probe
import pricing
import sources_registry as SR

ARK = "qoder-custom-72bd0478-adb3-48a5-9c6b-5090280aa47f/ark-code-latest"


def _rec(rid, inp, cr, out, model=ARK, ts="2026-10-07T10:00:00.000+08:00"):
    """按 Qoder CN 转录的真实包装层造一条 assistant 记录。"""
    return {
        "type": "assistant",
        "sessionId": "sess-1",
        "timestamp": ts,
        "uuid": "u-" + rid,
        "message": {
            "id": "msg-" + rid,
            "role": "assistant",
            "model": model,
            "usage": {
                "input_tokens": inp,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": cr,
                "output_tokens": out,
                "request_id": rid,
                "context_usage_ratio": inp / 1000000.0,
            },
        },
    }


class QoderCNRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tm-qodercn-")
        self._cache = probe.scan_cache
        probe.scan_cache = None          # 测试文件不该写进本机共享缓存
        probe.SKIP_NOTES.clear()
        self.src = {"id": "qoder", "paths": [], "fmt": "jsonl_generic",
                    "cache_in_input": True}

    def tearDown(self):
        probe.scan_cache = self._cache
        probe.SKIP_NOTES.clear()
        self.tmp.cleanup()

    def _scan(self, records, src=None):
        p = os.path.join(self.tmp.name, "sess-1.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return probe.scan_reg_jsonl_one(src or self.src, "qoder", set(), pre=[p])

    # ---------------------------------------------------------------- 注册表
    def test_qoder_entry_covers_qoder_cn_transcripts(self):
        q = next(s for s in SR.SOURCES if s["id"] == "qoder")
        got = [probe.reg_path(t) for t in q["paths"]]
        hit = [g for g in got if os.path.normpath(g).lower().endswith(
            os.path.join(".qoder-cn", "projects"))]
        self.assertEqual(1, len(hit), "必须有一条路径解析到 ~/.qoder-cn/projects")
        self.assertTrue(os.path.isabs(hit[0]), "路径模板要能解析成绝对路径")

    def test_cache_in_input_is_declared_not_defaulted(self):
        """只有 qoder 声明了这个口径，其余源一律保持 Anthropic 语义。"""
        declared = [s["id"] for s in SR.SOURCES if s.get("cache_in_input")]
        self.assertEqual(["qoder"], declared)
        u = {"input_tokens": 1000, "cache_read_input_tokens": 800,
             "cache_creation_input_tokens": 0, "output_tokens": 20}
        plain = probe.usage_from_dict(u)
        self.assertEqual((1000, 0, 800, 20, 0, False), plain[:6],
                         "不声明时不得扣缓存 —— 真 Anthropic 源扣了就把量算少")
        corrected = probe.usage_from_dict(u, cache_in_input=True)
        self.assertEqual(200, corrected[0], "声明后 input 只剩未命中缓存的一段")
        self.assertEqual(800, corrected[2])
        self.assertEqual(1020, sum(corrected[:4]), "扣减前后总量必须一致")

    # ---------------------------------------------------------------- 扫描
    def test_transcript_tokens_are_not_double_counted(self):
        recs = self._scan([_rec("r1", 375231, 0, 8192),
                           _rec("r2", 551119, 550592, 81)])
        self.assertEqual(2, len(recs))
        by = {r.key.split(":")[1]: r for r in recs}
        self.assertEqual(375231, by["1"].inp)
        self.assertEqual((527, 0, 550592, 81),
                         (by["2"].inp, by["2"].cw, by["2"].cr, by["2"].out))
        self.assertEqual(ARK, by["2"].model)
        self.assertEqual("2026-10-07", by["2"].date)

    def test_duplicate_request_id_is_folded_and_announced(self):
        recs = self._scan([_rec("same", 1000, 400, 10), _rec("same", 1000, 400, 10)])
        self.assertEqual(1, len(recs), "同一 request_id 只能算一次")
        self.assertIn("折叠", probe.SKIP_NOTES.get("qoder", ""))

    def test_credit_only_builtin_records_produce_no_tokens(self):
        """内置模型（qfmodel 等）四个 token 字段恒 0、只有 credits：
        本地既换不出 token 也没有单价，必须一条都不产生，绝不能拿 credits 当 token。"""
        recs = self._scan([_rec("c1", 0, 0, 0, model="qfmodel")])
        self.assertEqual([], recs)

    def test_without_the_flag_the_same_file_would_double_count(self):
        """反向证据：同一个文件不声明口径，这一条就从小小的 551,119 涨成 1,101,792。"""
        plain = self._scan([_rec("r2", 551119, 550592, 81)],
                           src={"id": "qoder", "paths": []})
        self.assertEqual(551119, plain[0].inp)
        self.assertEqual(1101792, (plain[0].inp + plain[0].cw
                                   + plain[0].cr + plain[0].out))

    # ---------------------------------------------------------------- 计价
    def test_ark_channel_is_subscription_not_priced(self):
        """BYOK 走的是 Qoder 订阅通道，只记用量不计金额（没有可验证的单价就不编）。"""
        self.assertTrue(pricing.is_plan(ARK))
        self.assertIsNone(pricing.cost(ARK, inp=1000, cr=200, out=50))


if __name__ == "__main__":
    unittest.main()
