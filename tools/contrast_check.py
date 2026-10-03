# -*- coding: utf-8 -*-
"""设计 token 颜色对比度校验（WCAG 2.1）。

从 webapp/static/styles/tokens.css 解析变量，按深浅两套主题展开 var() 引用，
对所有"文字色 × 表面色"组合计算对比度，输出 UTF-8 报告并判定 AA/AAA。

解析策略（与浏览器级联一致）：
  1. 先剥掉 @media (prefers-contrast: ...) 块（增强对比度是可选分支，不参与基准判定）；
  2. 再剥掉 @media (prefers-color-scheme: light) 块 —— 它只在用户没手动选主题时生效，
     所以它属于 light 主题的补充来源；
  3. 剩下的 :root / :root[data-theme="..."] 块按出现顺序合并，后出现的覆盖先出现的。

用法：python tools/contrast_check.py [--out output/contrast.md]
"""
from __future__ import annotations

import itertools
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOKENS = ROOT / "webapp" / "static" / "styles" / "tokens.css"
OUT = ROOT / "output" / "contrast.md"

HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
VAR_RE = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^)]+))?\)")

TEXT_TOKENS = ["--ink", "--text", "--text-2", "--muted", "--m-dim",
               "--brand", "--brand-strong", "--pos", "--warn", "--neg", "--info",
               "--m-token", "--m-cost", "--m-req", "--m-avg", "--m-cache"]
SURFACE_TOKENS = ["--canvas", "--surface", "--surface-2", "--surface-3", "--side", "--inset"]


def strip_media(text: str, pattern: str) -> str:
    """剥掉匹配 pattern 的 @media 块（处理嵌套花括号）。"""
    out, index = [], 0
    while True:
        match = re.search(r"@media[^{]*" + pattern + r"[^{]*\{", text[index:])
        if not match:
            out.append(text[index:])
            break
        start = index + match.start()
        cursor = index + match.end()
        depth = 1
        while cursor < len(text) and depth:
            if text[cursor] == "{":
                depth += 1
            elif text[cursor] == "}":
                depth -= 1
            cursor += 1
        out.append(text[index:start])
        index = cursor
    return "".join(out)


def blocks_of(text: str) -> list[tuple[str, dict[str, str]]]:
    found = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", text, re.S):
        selector = " ".join(match.group(1).split())
        body = match.group(2)
        if "--" not in body:
            continue
        variables = {k: v.strip() for k, v in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body)}
        found.append((selector, variables))
    return found


def theme_table(base_blocks, auto_light_blocks, want: str) -> dict[str, str]:
    table: dict[str, str] = {}
    for selector, variables in base_blocks:
        low = selector.lower()
        if "light" in low and want != "light":
            continue
        if want == "dark" and "light" in low:
            continue
        if want == "light" and "light" not in low:
            continue
        table.update(variables)
    if want == "light":
        for _selector, variables in auto_light_blocks:
            table.update(variables)
    return table


def resolve(name: str, table: dict[str, str], depth: int = 0) -> str:
    if depth > 8:
        return "#000000"
    value = table.get(name, "")
    if not value:
        return ""
    var = VAR_RE.search(value)
    if var:
        return resolve(var.group(1), table, depth + 1) or (var.group(2) or "").strip()
    return value.strip()


def to_rgb(color: str):
    color = color.strip()
    if not HEX_RE.match(color):
        return None
    body = color[1:]
    if len(body) == 3:
        body = "".join(c * 2 for c in body)
    if len(body) == 8:
        body = body[:6]
    return tuple(int(body[i:i + 2], 16) for i in (0, 2, 4))


def luminance(rgb) -> float:
    def channel(value: float) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(fg: str, bg: str):
    a, b = to_rgb(fg), to_rgb(bg)
    if a is None or b is None:
        return None
    l1, l2 = luminance(a), luminance(b)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def main() -> None:
    out_path = OUT
    if "--out" in sys.argv:
        out_path = pathlib.Path(sys.argv[sys.argv.index("--out") + 1])

    raw = TOKENS.read_text("utf-8", errors="replace")
    base = strip_media(strip_media(raw, r"prefers-color-scheme"), r"prefers-contrast")
    auto_light = strip_media(raw, r"prefers-contrast")
    base_blocks = blocks_of(base)
    light_auto_blocks = blocks_of(auto_light)
    # 自动浅色块也包含了 base 的内容，这里只保留 light 媒体查询里的部分
    light_auto_only = [b for b in light_auto_blocks if b not in base_blocks]

    lines = ["# 设计 token 对比度校验（WCAG 2.1）", "",
             "来源：`webapp/static/styles/tokens.css`，生成器：`tools/contrast_check.py`。", "",
             "判定：正文（<18.66px 或 <24px）需 ≥ 4.5:1；大字与图形化元素需 ≥ 3:1。", "",
             "表中只列出**不达标**的组合，全部通过即表示没有行。", ""]
    summary = []
    for theme in ("dark", "light"):
        table = theme_table(base_blocks, light_auto_only, theme)
        fails = 0
        rows = []
        for fg_name, bg_name in itertools.product(TEXT_TOKENS, SURFACE_TOKENS):
            fg, bg = resolve(fg_name, table), resolve(bg_name, table)
            value = ratio(fg, bg)
            if value is None or value >= 4.5:
                continue
            fails += 1
            rows.append(f"| `{fg_name}` {fg} | `{bg_name}` {bg} | {value:.2f} | "
                        f"{'大字/图形可用' if value >= 3 else '**不达标**'} |")
        lines += [f"## {theme} 主题", ""]
        if rows:
            lines += ["| 文字 token | 表面 token | 比值 | 判定 |", "| --- | --- | ---: | --- |", *rows]
        else:
            lines.append("全部组合通过 AA 正文标准。")
        lines += ["", f"- 不达标组合：**{fails}** 组", ""]
        summary.append(f"{theme}: fails={fails}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"report -> {out_path}")
    print(" | ".join(summary))


if __name__ == "__main__":
    main()
