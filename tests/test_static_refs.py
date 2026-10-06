"""静态资源引用完整性：版本戳不能漂移，引用到的文件必须真的在。

两类会静默坏掉界面的情况：
1. 改了 js/css 却忘了同步 `?v=` 戳 —— WebView2 的缓存跨版本存活，
   自动更新之后用户拿到的还是旧脚本（表现是"改动没生效"，且只在装过旧版的机器上出现）。
2. 引用了不存在的路径 —— 单个 404 在打包版里没有任何提示。
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "webapp", "static")


def read(p):
    return open(p, encoding="utf-8").read()


class StaticRefTests(unittest.TestCase):
    def setUp(self):
        self.html = read(os.path.join(STATIC, "index.html"))
        self.css = read(os.path.join(STATIC, "styles", "styles.css"))

    def test_cache_stamps_are_identical_everywhere(self):
        stamps = set(re.findall(r"[?&]v=(\d{6,10})", self.html))
        self.assertTrue(stamps, "index.html 里一个版本戳都没有，说明戳被误删了")
        css_stamps = set(re.findall(r"[?&]v=(\d{6,10})", self.css))
        self.assertTrue(css_stamps, "styles.css 的分层 @import 缺版本戳")
        self.assertEqual(stamps, css_stamps,
                         "版本戳漂移：HTML=%s CSS=%s，改前端必须一起改" % (stamps, css_stamps))

    def test_all_referenced_assets_exist(self):
        # 先去掉 CSS 注释：styles.css 里有一条被注释掉的 legacy.css @import，
        # 连注释一起扫会误报"引用了不存在的文件"。
        css = re.sub(r"/\*.*?\*/", "", self.css, flags=re.S)
        refs = set(re.findall(r'(?:src|href)="(/static/[^"?]+)', self.html))
        refs |= set(re.findall(r'url\("\./([a-z_]+\.css)', css))
        refs |= set(re.findall(r'"/static/(?:js|styles)/([A-Za-z0-9_.-]+)"', self.html))
        missing = []
        for r in sorted(refs):
            rel = r[len("/static/"):].lstrip("./") if r.startswith("/static/") else r
            if os.path.isfile(os.path.join(STATIC, rel.replace("/", os.sep))):
                continue
            if os.path.isfile(os.path.join(STATIC, "styles", rel.replace("/", os.sep))):
                continue
            missing.append(r)
        self.assertEqual([], missing)

    def test_scripts_load_in_the_order_the_concat_gate_checks(self):
        """加载顺序 = CI 拼接做跨文件重名检查的顺序，两处必须一致。"""
        order = re.findall(r'src="/static/js/([a-z_]+\.js)', self.html)
        self.assertEqual(9, len(order), order)
        self.assertIn("app.js", order[-1])          # app.js 必须最后（它负责启动）
        self.assertEqual("core.js", order[0])       # core.js 必须最先（DATA / 全局兜底）

    def test_no_orphan_js_files(self):
        """js/ 下不允许存在没被引用的脚本：漏引用就是"写了但永远不生效"。"""
        listed = set(re.findall(r'src="/static/js/([a-z_]+\.js)', self.html))
        on_disk = {f for f in os.listdir(os.path.join(STATIC, "js")) if f.endswith(".js")}
        self.assertEqual(set(), on_disk - listed,
                         "这些脚本没被 index.html 引用：%s" % sorted(on_disk - listed))


if __name__ == "__main__":
    unittest.main()
