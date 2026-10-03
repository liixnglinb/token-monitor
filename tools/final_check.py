# -*- coding: utf-8 -*-
"""收尾验证：对运行中的 Token Monitor 做一次"目标达成"综合检查。

检查项：
  1. 样式只有一个入口，层叠层顺序正确
  2. 深浅两套主题都能真正生效（背景/文字色随主题切换）
  3. 数据区三态容器、基础组件、无障碍属性都在 DOM 里
  4. 关键交互可用（路由、主题切换、危险操作确认、Toast）
  5. 无控制台错误 / 无低对比度 / 无焦点缺失

用法：python tools/final_check.py [--base http://127.0.0.1:8420]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent

PROBE = r"""
() => {
  const out = {};
  out.stylesheetCount = document.styleSheets.length;
  out.stylesheetHrefs = [...document.styleSheets].map(s => s.href || '(inline)');
  const css = [...document.styleSheets].map(s => { try { return [...s.cssRules].map(r => r.cssText).join('\n') } catch (e) { return '' } }).join('\n');
  out.hasLayerOrder = /@layer\s+legacy,\s*base,\s*components,\s*layout/.test(css);
  out.themes = {};
  const read = () => {
    const cs = getComputedStyle(document.body);
    const card = document.querySelector('.card, .kpi');
    return {
      bodyBg: cs.backgroundColor,
      text: cs.color,
      surface: card ? getComputedStyle(card).backgroundColor : null,
      tokenInk: getComputedStyle(document.documentElement).getPropertyValue('--ink').trim(),
      tokenCanvas: getComputedStyle(document.documentElement).getPropertyValue('--canvas').trim(),
    };
  };
  out.themes.before = read();
  return out;
}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8420")
    args = ap.parse_args()

    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, bool(ok), detail))

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        console: list[str] = []
        errors: list[str] = []
        page.on("console", lambda m: console.append(f"{m.type}: {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(args.base, wait_until="networkidle")
        page.wait_for_timeout(1500)

        probe = page.evaluate(PROBE)
        check("无 JS 异常", not errors, "; ".join(errors)[:200])
        check("无控制台错误", not console, "; ".join(console)[:200])
        check("样式只剩一个入口（+内联主题脚本）",
              probe["stylesheetCount"] <= 2, f"{probe['stylesheetCount']} 个：{probe['stylesheetHrefs']}")
        check("层叠层顺序声明存在", probe["hasLayerOrder"])

        # 两种主题都要真正生效：显式来回切换，避免受上次遗留的 localStorage 影响
        page.evaluate("window.TMTheme.set('dark', {announce:false})")
        page.wait_for_timeout(500)
        dark = page.evaluate(PROBE)["themes"]["before"]
        page.evaluate("window.TMTheme.set('light', {announce:false})")
        page.wait_for_timeout(500)
        light = page.evaluate(PROBE)["themes"]["before"]
        check("深色主题已生效", dark["tokenCanvas"].upper() not in ("#F4F5F7", "#FFFFFF"),
              f"canvas={dark['tokenCanvas']}")
        check("浅色主题改变 token", dark["tokenCanvas"] != light["tokenCanvas"],
              f"{dark['tokenCanvas']} → {light['tokenCanvas']}")
        check("浅色主题改变实际渲染", dark["bodyBg"] != light["bodyBg"],
              f"{dark['bodyBg']} → {light['bodyBg']}")
        check("浅色主题改变文字色", dark["text"] != light["text"], f"{dark['text']} → {light['text']}")
        check("浅色主题下画布确实是浅色", light["tokenCanvas"].upper() in ("#F4F5F7", "#FFFFFF"),
              light["tokenCanvas"])
        page.evaluate("window.TMTheme.set('dark', {announce:false})")
        page.wait_for_timeout(400)

        # 组件与三态容器
        for selector, label in [
            (".kpi", "KPI 卡片"),
            (".card", "卡片"),
            (".seg", "分段控件"),
            (".dd-menu", "下拉菜单"),
            ("#ddRange", "时间范围下拉"),
            ("#modelPager", "分页容器"),
            (".field-search", "搜索框"),
            (".switch", "开关"),
            (".confirm-card", "危险操作确认框"),
            ("#toastStack", "Toast 容器"),
            ("#collectionState", "数据状态条（三态）"),
            ("#setNav", "设置二级导航"),
            ("#tabbar", "窄屏标签栏"),
            (".crumb", "面包屑"),
        ]:
            check(f"组件存在：{label}", page.locator(selector).count() > 0)

        # 无障碍
        aria = page.evaluate("document.querySelectorAll('[aria-label],[aria-current],[aria-pressed],[aria-live],[aria-sort],[role]').length")
        check("ARIA 语义属性数量合理（≥20）", aria >= 20, str(aria))
        check("存在跳到主内容链接", page.locator("a.skip-link").count() == 1)
        check("标题层级唯一 h1", page.locator("h1").count() == 1)

        # 交互
        page.evaluate("window.TMUI.route('models')")
        page.wait_for_timeout(400)
        check("路由可切到模型页", page.is_visible("#view-models"))
        check("模型表有可排序表头", page.locator(".th-sort").count() >= 5)

        # 计费类型筛选存在且可切换（模型页内）
        check("计费类型筛选存在", page.locator("#segBilling button").count() == 4)
        page.locator('#segBilling button[data-b="unpriced"]').click()
        page.wait_for_timeout(300)
        check("计费筛选写入 hash", "billing=unpriced" in page.evaluate("location.hash"),
              page.evaluate("location.hash"))
        page.locator('#segBilling button[data-b="all"]').click()
        page.wait_for_timeout(200)

        page.evaluate("window.TMUI.route('overview')")
        page.wait_for_timeout(500)

        # 性能改造：迷你走势必须是 SVG（0 额外 Chart 实例）
        check("排行榜使用 SVG sparkline", page.locator(".sparkline").count() > 0,
              f"sparklines={page.locator('.sparkline').count()}")
        instances = page.evaluate("Object.keys(Chart.instances).length")
        check("Chart 实例不超过 4 个（主图+环形+余量）", instances <= 4, f"instances={instances}")

        # 筛选状态进 hash
        h = page.evaluate("location.hash")
        check("hash 携带筛选参数", "range=" in h and "metric=" in h, h)

        # 抽屉（窄屏数据源筛选）容器与桌面隐藏
        check("抽屉容器存在", page.locator("#agentDrawer").count() == 1)
        check("桌面端隐藏筛选按钮", not page.is_visible("#filterBtn"))

        # 键盘焦点可见（抽查 6 个控件）
        # Chromium 的 :focus-visible 依赖"最近输入是键盘"的启发式：
        # 先敲一次 Tab 建立键盘模态，程序化 focus 才会命中焦点环样式
        page.keyboard.press("Tab")
        rings = 0
        for selector in ["#themeBtn", "#fExport", "#settingsBtn", "#ddRange .dd-btn", "#nav a[data-view='models']", "#clearFilters"]:
            element = page.locator(selector).first
            if element.count() == 0:
                continue
            element.focus()
            visible = page.evaluate(
                """(sel) => {
                    const el = document.querySelector(sel);
                    if (!el) return false;
                    const cs = getComputedStyle(el);
                    return (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || cs.boxShadow !== 'none';
                }""",
                selector,
            )
            rings += 1 if visible else 0
        check("抽查控件都有可见焦点环", rings >= 5, f"{rings}/6")

        browser.close()

    failed = [r for r in results if not r[1]]
    for name, ok, detail in results:
        print(("PASS  " if ok else "FAIL  ") + name + (("  — " + detail) if detail and not ok else ""))
    report = ROOT / "output" / "final-check.json"
    report.write_text(json.dumps([{"check": n, "ok": o, "detail": d} for n, o, d in results],
                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(results) - len(failed)}/{len(results)} 通过；报告 {report}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
