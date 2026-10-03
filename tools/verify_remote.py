# -*- coding: utf-8 -*-
"""核对远端仓库最终状态：关键文件在位、历史样式表已删除、发布产物齐全。

用法：python tools/verify_remote.py
"""
from __future__ import annotations

import subprocess
import sys

REPO = "liixnglinb/token-monitor"

EXPECT_PRESENT = [
    "docs/ui-spec.md",
    "docs/shots/overview-dark.png",
    "tools/ui_audit.py",
    "tools/contrast_check.py",
    "tools/ui_verify.py",
    "tools/ui_smoke.py",
    "tools/final_check.py",
    "tools/style_snapshot.py",
    "tests/test_version_file.py",
    "webapp/static/styles/styles.css",
    "webapp/static/styles/tokens.css",
    "webapp/static/styles/base.css",
    "webapp/static/styles/components.css",
    "webapp/static/styles/layout.css",
    "webapp/static/js/theme.js",
    "webapp/static/js/ui.js",
    "webapp/static/index.html",
]
EXPECT_GONE = [
    "webapp/static/styles/ui-polish.css",
    "webapp/static/styles/theme.css",
    "webapp/static/styles/sidebar.css",
    "webapp/static/styles/canvas.css",
    "webapp/static/js/voyra-ui.js",
    "webapp/static/styles/legacy.css",
    "webapp/static/styles/legacy-src/ui-polish.css",
    "webapp/static/styles/legacy-src/theme.css",
    "tools/consolidate_legacy_css.py",
]


def gh(*args: str) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    return (result.stdout or result.stderr or "").strip()


def main() -> int:
    def jq(expr: str) -> str:
        return gh("api", f"repos/{REPO}/{path}", "--jq", expr)

    failures: list[str] = []
    print("== 关键文件在位 ==")
    for path in EXPECT_PRESENT:
        sha = gh("api", f"repos/{REPO}/contents/{path}", "--jq", ".sha")
        ok = bool(sha) and "Not Found" not in sha
        print(f"  {'OK  ' if ok else '缺失'} {path}")
        if not ok:
            failures.append(path)

    print("\n== 历史样式表已删除 ==")
    for path in EXPECT_GONE:
        out = gh("api", f"repos/{REPO}/contents/{path}", "--jq", ".sha")
        gone = "Not Found" in out
        print(f"  {'已删除' if gone else '仍存在!'} {path}")
        if not gone:
            failures.append(path)

    print("\n== 版本号与发布 ==")
    content = gh("api", f"repos/{REPO}/contents/version.txt", "--jq", ".content")
    if content and "Not Found" not in content:
        import base64
        print("  version.txt =", base64.b64decode(content).decode("utf-8").lstrip("\ufeff"))
    releases = gh("api", f"repos/{REPO}/releases?per_page=3", "--jq",
                  '.[] | "  " + .tag_name + " | " + (.assets | length | tostring) + " 个产物 | " + (.published_at // "未发布")')
    print(releases or "  （无）")

    print("\n== 最近提交 ==")
    print(gh("api", f"repos/{REPO}/commits?per_page=4", "--jq", '.[] | "  " + .sha[0:8]'))

    print()
    if failures:
        print(f"存在 {len(failures)} 项问题：" + ", ".join(failures))
        return 1
    print("远端状态核对通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
