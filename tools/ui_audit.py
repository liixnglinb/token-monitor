"""UI 体检：设计 token 覆盖率 + 硬编码清单 + 字号阶梯 + 无障碍/状态覆盖缺口。

输出写成 UTF-8 报告（Windows 控制台会把中文二次编码，所以只打印纯 ASCII 摘要）。
用法：
    python tools/ui_audit.py
    python tools/ui_audit.py --out output/ui-audit.md
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC = ROOT / "webapp" / "static"
OUT = ROOT / "output" / "ui-audit.md"

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")
RGBA_RE = re.compile(r"\brgba?\(\s*\d")
PX_RE = re.compile(r"(?<![\w-])(\d+(?:\.\d+)?)px\b")
FONT_PX_RE = re.compile(r"font-size:\s*(\d+(?:\.\d+)?)px")

# 组件 / 状态关键词：用来量化"规范里要求的东西，代码里有没有"
STATE_KEYS = {
    "hover": r":hover",
    "focus-visible": r":focus-visible",
    "active/pressed": r":active\b|\.is-pressing",
    "disabled": r":disabled|\[disabled\]|aria-disabled",
    "aria-busy/loading": r"aria-busy|\.is-loading|\.loading\b",
    "empty state": r"-empty|空态|暂无",
    "skeleton": r"skeleton|骨架",
    "toast": r"toast|\.snack",
    "modal": r"modal|dialog",
    "drawer": r"drawer",
    "reduced-motion": r"prefers-reduced-motion",
    "dark theme": r"data-theme|prefers-color-scheme",
    "light theme": r"data-theme=\"light\"|prefers-color-scheme:\s*light",
    "virtual scroll": r"virtual|IntersectionObserver",
    "pagination": r"pagination|分页|加载更多",
    "tooltip": r"tooltip|title=",
}


def sources(suffixes=(".js", ".css", ".html")):
    for path in sorted(STATIC.rglob("*")):
        if path.suffix.lower() not in suffixes:
            continue
        if ".mimosa" in path.parts or "vendor" in path.parts:
            continue
        # legacy.css / legacy-src/ 是历史样式归档（已不被 styles.css 引用），不计入在用的硬编码
        if path.name == "legacy.css" or "legacy-src" in path.parts:
            continue
        yield path


def inspect(path: pathlib.Path) -> dict:
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "size": len(raw),
        "cjk": len(CJK_RE.findall(text)),
        "hex": sorted(set(HEX_RE.findall(text))),
        "hex_n": len(HEX_RE.findall(text)),
        "rgba_n": len(RGBA_RE.findall(text)),
        "important_n": text.count("!important"),
        "px_n": len(PX_RE.findall(text)),
        "font_px": sorted({float(v) for v in FONT_PX_RE.findall(text)}),
        "inline_style_n": len(re.findall(r'style="', text)),
        "text": text,
    }


def main() -> None:
    out_path = OUT
    if "--out" in sys.argv:
        out_path = pathlib.Path(sys.argv[sys.argv.index("--out") + 1])

    rows = [inspect(p) for p in sources()]
    tokens_css = (STATIC / "styles" / "tokens.css").read_text("utf-8", errors="replace")
    token_names = sorted(set(re.findall(r"(--[\w-]+)\s*:", tokens_css)))
    all_text = "\n".join(r["text"] for r in rows)
    html_text = "\n".join(r["text"] for r in rows if r["path"].endswith(".html"))

    report: list[str] = []
    add = report.append
    add("# Token Monitor · UI 体检报告")
    add("")
    add("由 `tools/ui_audit.py` 生成，复跑命令：`python tools/ui_audit.py`。")
    add("")

    add("## 1. 样式规模与硬编码（设计 token 覆盖率）")
    add("")
    add("| 文件 | 字节 | #hex 种类 | #hex 次数 | rgba() | !important | px 字面量 | 行内 style |")
    add("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in sorted(rows, key=lambda r: -r["size"]):
        add(f"| `{row['path']}` | {row['size']} | {len(row['hex'])} | {row['hex_n']} |"
            f" {row['rgba_n']} | {row['important_n']} | {row['px_n']} | {row['inline_style_n']} |")
    add("")
    add("## 2. 在用的硬编码颜色（按文件拆开）")
    add("")
    add("`legacy.css` 是历史归档（不加载），不计入。")
    add("")
    add("| 文件 | #hex 次数 | 不同色值 | 说明 |")
    add("| --- | ---: | ---: | --- |")
    for row in sorted((r for r in rows if r["hex_n"]), key=lambda r: -r["hex_n"]):
        note = ""
        if row["path"].endswith("tokens.css"):
            note = "设计 token 唯一来源（调色板定义处）"
        elif row["path"].endswith("core.js"):
            note = "各软件/模型厂商品牌色（数据，不是界面配色）"
        elif row["path"].endswith("charts.js"):
            note = "取不到 CSS 变量时的兜底值"
        add(f"| `{row['path']}` | {row['hex_n']} | {len({c.lower() for c in row['hex']})} | {note} |")
    add("")
    add(f"- 全站 #hex 字面量合计：**{sum(r['hex_n'] for r in rows)}** 次，"
        f"互不相同的颜色值 **{len({c.lower() for r in rows for c in r['hex']})}** 个")
    add("")

    add("## 3. 字号阶梯（全站实际出现的 font-size）")
    add("")
    sizes: dict[float, int] = {}
    for row in rows:
        for size in row["font_px"]:
            sizes[size] = sizes.get(size, 0) + 1
    add(f"共 **{len(sizes)}** 个不同字号：")
    add("")
    add(" / ".join(f"{s:g}px×{n}" for s, n in sorted(sizes.items())))
    add("")

    add("## 4. 规范要求项在代码里的覆盖情况")
    add("")
    add("| 规范项 | 出现次数 | 判定 |")
    add("| --- | ---: | --- |")
    for label, pattern in STATE_KEYS.items():
        found = len(re.findall(pattern, all_text))
        add(f"| {label} | {found} | {'有' if found else '**缺失**'} |")
    add("")

    add("## 5. tokens.css 现有 token")
    add("")
    add(f"共 {len(token_names)} 个：`" + "`、`".join(token_names) + "`")
    add("")

    add("## 6. index.html 结构统计")
    add("")
    add(f"- 行内 style 属性：{len(re.findall(r'style=\"', html_text))} 处")
    add(f"- `aria-*` 属性：{len(re.findall(r'aria-[a-z]+=', html_text))} 处")
    add(f"- `role=` 属性：{len(re.findall(r'role=', html_text))} 处")
    add(f"- `<canvas>`：{len(re.findall(r'<canvas', html_text))} 个")
    add(f"- `hidden` 属性：{len(re.findall(r'hidden', html_text))} 处")
    add("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(report) + "\n", encoding="utf-8")

    print(f"report -> {out_path}")
    print(f"files={len(rows)} hex_literals={sum(r['hex_n'] for r in rows)} "
          f"unique_colors={len({c.lower() for r in rows for c in r['hex']})} "
          f"font_sizes={len(sizes)} tokens={len(token_names)}")
    missing = [k for k, p in STATE_KEYS.items() if not re.search(p, all_text)]
    print("missing_specs=" + ",".join(missing))


if __name__ == "__main__":
    main()
