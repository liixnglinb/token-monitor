import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import probe_v3_allsources as probe
import scan_cache


class TokenDetectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tm-token-test-")
        self.old_cache_dir = scan_cache._DIR
        self.old_cache_path = scan_cache._PATH
        self.old_cache_mem = scan_cache._MEM
        self.old_probe_cache = probe.scan_cache
        scan_cache._DIR = self.tmp.name
        scan_cache._PATH = os.path.join(self.tmp.name, "scan-cache.json")
        scan_cache._MEM = None
        probe.scan_cache = scan_cache
        probe.SKIP_NOTES.clear()
        probe._cap_set(False)

    def tearDown(self):
        probe.SKIP_NOTES.clear()
        probe._cap_set(False)
        probe.scan_cache = self.old_probe_cache
        scan_cache._DIR = self.old_cache_dir
        scan_cache._PATH = self.old_cache_path
        scan_cache._MEM = self.old_cache_mem
        self.tmp.cleanup()

    def _write_jsonl(self, path, rows):
        with open(path, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def test_anthropic_cache_read_is_not_subtracted(self):
        got = probe.usage_from_dict({
            "input_tokens": 2000,
            "cache_creation_input_tokens": 100,
            "cache_read_input_tokens": 500,
            "output_tokens": 300,
        })
        self.assertEqual(sum(got[:4]), 2900)

    def test_openai_cached_input_is_subtracted(self):
        got = probe.usage_from_dict({
            "prompt_tokens": 2000,
            "completion_tokens": 300,
            "prompt_tokens_details": {"cached_tokens": 500},
        })
        self.assertEqual(sum(got[:4]), 2300)

    def test_codex_uses_provider_total(self):
        usage = {
            "input_tokens": 3154231,
            "cached_input_tokens": 329877376,
            "output_tokens": 609552,
            "total_tokens": 333641159,
        }
        self.assertEqual(sum(probe._codex_usage(usage)[:4]), 333641159)

    def test_empty_verdict_is_invalidated_when_logs_change(self):
        path = os.path.join(self.tmp.name, "session.jsonl")
        self._write_jsonl(path, [{"type": "meta"}])
        src = {"paths": []}

        def real_scan(files):
            return probe.scan_reg_jsonl_one(src, "test-source", set(), pre=files)

        first = probe.cached_scan("test-source", lambda: [path], real_scan)
        self.assertEqual(first, [])

        self._write_jsonl(path, [{
            "timestamp": "2026-09-24T00:00:00Z",
            "session_id": "s1",
            "model": "m1",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }])
        second = probe.cached_scan("test-source", lambda: [path], real_scan)
        self.assertEqual(sum(r.total() for r in second), 15)

    def test_file_cache_does_not_treat_rewrite_as_append(self):
        path = os.path.join(self.tmp.name, "rewrite.jsonl")
        src = {"paths": []}

        def line_for(usage, size):
            row = {
                "timestamp": "2026-09-24T00:00:00Z",
                "session_id": "s1",
                "model": "m1",
                "usage": usage,
            }
            raw = json.dumps(row, ensure_ascii=False).encode("utf-8")
            return raw + b" " * (size - len(raw) - 1) + b"\n"

        with open(path, "wb") as f:
            f.write(line_for({"input_tokens": 10, "output_tokens": 5}, 512))
        first = probe.scan_reg_jsonl_one(src, "test-source", set(), pre=[path])
        self.assertEqual(sum(r.total() for r in first), 15)

        with open(path, "wb") as f:
            f.write(line_for({"input_tokens": 99, "output_tokens": 77}, 512))
        second = probe.scan_reg_jsonl_one(src, "test-source", set(), pre=[path])
        self.assertEqual(sum(r.total() for r in second), 176)

    def test_json_arrays_are_not_limited_to_200_items(self):
        path = os.path.join(self.tmp.name, "many.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump([{"n": i} for i in range(250)], f)
        self.assertEqual(len(list(probe.iter_records(path))), 250)


if __name__ == "__main__":
    unittest.main()
