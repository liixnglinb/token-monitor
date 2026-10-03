# -*- coding: utf-8 -*-
"""把散落的旧样式表合并成单一的 legacy 层，供新设计系统稳定覆盖。

背景：`webapp/static/styles/` 下有 10 个历史样式表，按 index.html 的加载顺序层层覆盖，
且含 1103 处硬编码颜色。直接删会丢视觉，直接叠加又会"未分层样式骑在分层样式之上"。
做法：按原加载顺序拼接，整体包进 `@layer legacy { ... }`，原文件的先后关系保持不变，
新设计系统（tokens/base/components/layout，属于 app 层）永远优先。

用法：python tools/consolidate_legacy_css.py [--dry]
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
STYLES = ROOT / "webapp" / "static" / "styles"
# 旧样式表已归档到 styles/legacy-src/（保留可追溯的原始文件），合并产物仍在 styles/
SRC = STYLES / "legacy-src"

# 保持 index.html 里的原始加载顺序（后者覆盖前者）
LEGACY_FILES = [
    "base.css",
    "sidebar.css",
    "shell.css",
    "overview.css",
    "models.css",
    "settings.css",
    "responsive.css",
    "canvas.css",
    "modern.css",
    "theme.css",
    "ui-polish.css",
]

OUT = STYLES / "legacy.css"

HEADER = """/* =============================================================================
   legacy.css —— 历史样式归档层（自动生成，请勿手工编辑）
   -----------------------------------------------------------------------------
   由 tools/consolidate_legacy_css.py 按原加载顺序合并：
     base → sidebar → shell → overview → models → settings → responsive
     → canvas → modern → theme → ui-polish
   整体包在 @layer legacy 中，优先级低于新设计系统（tokens / base / components /
   layout 属于 app 层）。改版期间只做兼容兜底，不再新增规则。

   重新生成：python tools/consolidate_legacy_css.py
   ============================================================================= */
@layer legacy {
"""

FOOTER = "}\n"


def main() -> None:
    dry = "--dry" in sys.argv
    chunks = [HEADER]
    total = 0
    for name in LEGACY_FILES:
        path = SRC / name
        if not path.exists():
            print(f"skip (missing): {name}")
            continue
        body = path.read_text("utf-8", errors="replace")
        # 历史上这些文件都没有 @layer；若将来出现，剥掉声明以免嵌套语义混乱
        body = re.sub(r"@layer\s+[^;{]*;", "", body)
        total += len(body.encode("utf-8"))
        chunks.append(f"\n/* ── {name} ── */\n{body.strip()}\n")
        print(f"merged {name:20s} {len(body):>7d} chars")
    chunks.append(FOOTER)

    if dry:
        print("[dry] 未写文件")
        return
    OUT.write_text("".join(chunks), encoding="utf-8")
    print(f"\nwritten {OUT} ({OUT.stat().st_size} bytes, source {total} bytes)")


if __name__ == "__main__":
    main()
