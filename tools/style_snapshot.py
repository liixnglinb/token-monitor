# -*- coding: utf-8 -*-
"""样式快照对比：把关键元素的计算样式抓成 JSON，用于"删除 legacy 层前后"的回归比对。

用法：
    python tools/style_snapshot.py --out output/style-before.json
    # 做完样式改动
    python tools/style_snapshot.py --out output/style-after.json --diff output/style-before.json

比对时只关心会造成"视觉明显变化"的属性（尺寸/颜色/可见性/位置量级）。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent

# 覆盖两套主题（跟随系统 + 手动浅色）与三个视图
MATRIX = [
    ("overview-dark", "dark", None),
    ("overview-light", "light", None),
    ("models-dark", "dark", "models"),
    ("settings-dark", "dark", "settings"),
    ("overview-mobile-dark", "dark", None, 390),
]

PROBE = r"""
() => {
  const props = ['display','position','flexDirection','gridTemplateColumns','width','height',
    'padding','margin','gap','fontSize','fontWeight','lineHeight','color','backgroundColor',
    'borderRadius','borderColor','boxShadow','opacity','overflowX','overflowY','textAlign'];
  const nodes = [];
  const selectors = ['body','aside','#nav a','.side-project','.side-section-head','.side-foot','.side-settings',
    'main','.topbar','.page-title','.content','.filters','.dd-btn','.kpis','.kpi','.kpi .v','.kpi .s','.k-corner',
    '.card','.chart-card','.card-head h3','.seg','.seg button','.trend-summary','.trend-stat','.daily-row',
    '.agent-panel','.ar-head','.ar-metrics','.dist','.donut-legend','.t10-row','.table-card','.table-card thead th',
    '.table-card tbody td','.model-stat','.set-card','.set-row','.set-info .t','.set-sel','.switch','.btn',
    '#tabbar','.pager','.toast-stack','#view-overview','#view-models','#view-settings'];
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (!el) { nodes.push({ sel, missing: true }); continue; }
    const cs = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    const entry = { sel, rect: [Math.round(rect.width), Math.round(rect.height)] };
    for (const p of props) entry[p] = cs[p];
    nodes.push(entry);
  }
  return nodes;
}
"""


def capture(base: str, out_path: pathlib.Path) -> dict:
    data: dict[str, list] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for case in MATRIX:
            name, theme, view = case[0], case[1], case[2]
            width = case[3] if len(case) > 3 else 1440
            page = browser.new_page(viewport={"width": width, "height": 900}, color_scheme="dark")
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base, wait_until="networkidle")
            page.wait_for_timeout(900)
            if view == "models":
                page.evaluate("window.TMUI.route('models')")
            elif view == "settings":
                page.evaluate("window.TMUI.route('settings','general')")
            page.evaluate("(t) => window.TMTheme.set(t, {announce:false})", theme)
            page.wait_for_timeout(700)
            data[name] = {"theme": theme, "view": view, "width": width,
                          "errors": errors, "nodes": page.evaluate(PROBE)}
            page.close()
        browser.close()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def diff(before: dict, after: dict) -> list[str]:
    changes: list[str] = []
    for case, snap in before.items():
        other = after.get(case)
        if not other:
            changes.append(f"[{case}] 缺失（新快照没有这一组）")
            continue
        old_nodes = {n["sel"]: n for n in snap["nodes"]}
        new_nodes = {n["sel"]: n for n in other["nodes"]}
        for sel, old in old_nodes.items():
            new = new_nodes.get(sel)
            if not new:
                changes.append(f"[{case}] {sel}: 新快照中已不存在")
                continue
            if old.get("missing") or new.get("missing"):
                if old.get("missing") != new.get("missing"):
                    changes.append(f"[{case}] {sel}: 存在性变化 {old.get('missing')} → {new.get('missing')}")
                continue
            for key, value in old.items():
                if key in ("sel", "rect"):
                    continue
                if new.get(key) != value:
                    changes.append(f"[{case}] {sel} · {key}: {value} → {new.get(key)}")
            if old["rect"] != new["rect"]:
                delta = abs(old["rect"][0] - new["rect"][0]) + abs(old["rect"][1] - new["rect"][1])
                if delta > 6:
                    changes.append(f"[{case}] {sel} · 尺寸: {old['rect']} → {new['rect']}")
    return changes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8420")
    ap.add_argument("--out", default="output/style-after.json")
    ap.add_argument("--diff", default=None)
    args = ap.parse_args()

    out_path = ROOT / args.out
    data = capture(args.base, out_path)
    print(f"snapshot -> {out_path} ({sum(len(v['nodes']) for v in data.values())} 条)")

    if args.diff:
        before = json.loads((ROOT / args.diff).read_text("utf-8"))
        changes = diff(before, data)
        report = ROOT / "output" / "style-diff.md"
        lines = ["# 样式快照差异", "",
                 f"基线：`{args.diff}`　对比：`{args.out}`", ""]
        if changes:
            lines += [f"共 **{len(changes)}** 处计算样式变化：", ""] + [f"- {c}" for c in changes]
        else:
            lines.append("无差异。")
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"diff -> {report}  变化 {len(changes)} 处")
        for line in changes[:25]:
            print("  " + line)
        if len(changes) > 25:
            print(f"  … 其余 {len(changes) - 25} 处见报告")


if __name__ == "__main__":
    sys.exit(main())
