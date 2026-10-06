"""注册表驱动的 sqlite 源：能真的取出用量，坏库不崩。

回归背景（2026-10-06）：`scan_reg_sqlite_one` 取列名写的是
`SELECT name FROM pragma_table_info(?)` —— 单列结果却按 `r[1]` 取，
每个带表的库都抛 IndexError；异常穿过整源，把同一源里**已经解析出来的
jsonl 记录一起丢掉**，面板上表现为「阿里 Qoder / 月之暗面 Kimi 扫描失败」。
"""
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import probe_v3_allsources as probe


def _make_db(path, ddl):
    con = sqlite3.connect(path)
    for sql in ddl:
        con.execute(sql)
    con.commit()
    con.close()


class RegistrySqliteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tm-regdb-")
        self.src = {"id": "fake", "cn": "Fake", "fmt": "jsonl_generic"}
        probe.SKIP_NOTES.clear()
        probe._cap_set(False)

    def tearDown(self):
        probe.SKIP_NOTES.clear()
        probe._cap_set(False)
        self.tmp.cleanup()

    def _scan(self, db):
        return probe.scan_reg_sqlite_one(self.src, "fake", set(), pre=[db])

    def test_token_columns_produce_records(self):
        db = os.path.join(self.tmp.name, "usage.db")
        _make_db(db, [
            "CREATE TABLE msg (id TEXT, session_id TEXT, model TEXT, created_at TEXT,"
            " input_tokens INTEGER, output_tokens INTEGER)",
            "INSERT INTO msg VALUES ('m1','s1','gpt-x','2026-09-01T10:00:00',120,30)",
            "INSERT INTO msg VALUES ('m2','s1','gpt-x','2026-09-02T10:00:00',10,5)",
        ])
        recs = self._scan(db)
        self.assertEqual(2, len(recs), "两行用量都应被取出")
        by_date = {r.date: r for r in recs}
        self.assertEqual(120, by_date["2026-09-01"].inp)
        self.assertEqual(30, by_date["2026-09-01"].out)
        self.assertEqual("gpt-x", by_date["2026-09-01"].model)

    def test_table_without_token_columns_is_skipped(self):
        db = os.path.join(self.tmp.name, "plain.db")
        _make_db(db, [
            "CREATE TABLE settings (k TEXT, v TEXT)",
            "INSERT INTO settings VALUES ('theme','dark')",
        ])
        self.assertEqual([], self._scan(db))

    def test_corrupt_db_does_not_raise(self):
        bad = os.path.join(self.tmp.name, "broken.db")
        with open(bad, "wb") as f:
            f.write(b"not a sqlite file at all" * 40)
        try:
            out = self._scan(bad)
        except Exception as e:                       # 坏数据只能被跳过，不能冒泡
            self.fail("损坏的库不应抛出：%r" % e)
        self.assertEqual([], out)


if __name__ == "__main__":
    unittest.main()
