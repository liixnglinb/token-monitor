# -*- coding: utf-8 -*-
"""UI 验证台：对运行中的 Token Monitor 页面做自动化体检，结果写成 UTF-8 报告。

能力：
  1. 打开页面（含指定主题/视口），抓截图；
  2. 收集控制台错误、页面异常、失败请求；
  3. DOM 体检：行内样式、未命名按钮、图片无 alt、标题层级、landmark；
  4. 可访问性快照：对比度粗筛（前景/背景计算）、可聚焦元素、焦点可见性；
  5. 交互冒烟：视图切换、下拉菜单、分段控件、键盘可达。

用法（需先有服务在跑，见 tools/dev_serve.py）：
    python tools/ui_verify.py --out output/ui-verify --base http://127.0.0.1:8420
    python tools/ui_verify.py --theme light --viewport 1440x900 --shot output/shots/light.png
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent

DOM_PROBE = r"""
() => {
  const out = { counts: {}, issues: [], focusables: 0, landmarks: [] };
  const q = (sel) => Array.from(document.querySelectorAll(sel));
  out.counts.inlineStyle = q('[style]').filter(el => el.getAttribute('style').trim()).length;
  out.counts.buttons = q('button').length;
  out.counts.links = q('a').length;
  out.counts.canvas = q('canvas').length;
  out.counts.images = q('img').length;
  out.counts.headings = q('h1,h2,h3,h4,h5,h6').length;
  out.counts.tables = q('table').length;

  // 未命名交互元素（读屏念不出来）
  for (const el of q('button,a[href],a[data-view],[role=button]')) {
    const name = (el.getAttribute('aria-label') || el.textContent || '').trim();
    if (!name) out.issues.push({ kind: 'unnamed-control', tag: el.tagName, cls: el.className });
  }
  for (const img of q('img')) {
    if (img.getAttribute('alt') === null) out.issues.push({ kind: 'img-no-alt', src: img.getAttribute('src') });
  }
  // 标题层级
  const h1 = q('h1').length;
  if (h1 !== 1) out.issues.push({ kind: 'h1-count', value: h1 });
  for (const h of q('h1,h2,h3,h4,h5,h6')) {
    if (!h.textContent.trim() && !h.getAttribute('aria-label')) {
      out.issues.push({ kind: 'empty-heading', cls: h.className });
    }
  }
  out.landmarks = q('main,aside,nav,header,footer,[role=main],[role=navigation]').map(el => el.tagName + (el.id ? '#' + el.id : ''));
  // 可聚焦元素与焦点可见性：逐个真实 focus 后测量，避免只看 :focus-visible 声明
  const focusables = q('a[href],button,input,select,textarea,[tabindex]:not([tabindex="-1"])')
    .filter(el => !el.disabled && el.offsetParent !== null);
  out.focusables = focusables.length;
  for (const el of focusables) {
    el.focus();
    const cs = getComputedStyle(el);
    const ring = (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || cs.boxShadow !== 'none';
    if (!ring && !el.dataset.noFocusRing) {
      out.issues.push({ kind: 'no-focus-ring', tag: el.tagName,
        cls: String(el.className || '').slice(0, 60), id: el.id || '' });
    }
  }
  if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
  // 水平溢出
  const de = document.documentElement;
  if (de.scrollWidth > de.clientWidth + 1) {
    out.issues.push({ kind: 'horizontal-overflow', scrollWidth: de.scrollWidth, clientWidth: de.clientWidth });
  }
  return out;
}
"""

A11Y_PROBE = r"""
() => {
  // 对比度：取可见文本的前景/背景，按 WCAG 公式算比值。
  // 背景取"实际合成色"——半透明背景逐层与父级混合，否则 rgba 会被误当成不透明黑/白。
  const parse = (rgb) => {
    const m = rgb.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const parts = m[1].split(',').map(s => parseFloat(s));
    return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
  };
  const over = (top, bottom) => ({
    r: top.r * top.a + bottom.r * (1 - top.a),
    g: top.g * top.a + bottom.g * (1 - top.a),
    b: top.b * top.a + bottom.b * (1 - top.a),
    a: 1,
  });
  const lum = (c) => {
    const f = (v) => {
      const x = v / 255;
      return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };
  const layerStack = (el) => {
    const stack = [];
    let node = el;
    while (node && node !== document.documentElement) {
      const cs = getComputedStyle(node);
      const bg = parse(cs.backgroundColor);
      if (bg && bg.a > 0) stack.push(bg);
      if (bg && bg.a >= 0.999) break;
      node = node.parentElement;
    }
    stack.push(parse(getComputedStyle(document.body).backgroundColor) || { r: 12, g: 12, b: 13, a: 1 });
    return stack;
  };
  const bgOf = (el) => {
    const stack = layerStack(el);
    let base = { r: 255, g: 255, b: 255, a: 1 };
    // 从最底层往上压
    for (let i = stack.length - 1; i >= 0; i--) base = over(stack[i], base);
    return base;
  };
  const results = [];
  for (const el of document.querySelectorAll('body *')) {
    if (el.closest('.skeleton') || el.classList.contains('skeleton')) continue;   // 骨架屏不承载信息
    if (el.children.length && !Array.from(el.childNodes).some(n => n.nodeType === 3 && n.textContent.trim())) continue;
    const text = el.textContent.trim();
    if (!text) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) < 0.2) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) continue;
    const fgRaw = parse(cs.color);
    if (!fgRaw) continue;
    const bg = bgOf(el);
    const fg = fgRaw.a < 1 ? over(fgRaw, bg) : fgRaw;
    const l1 = lum(fg), l2 = lum(bg);
    const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    const size = parseFloat(cs.fontSize);
    const bold = parseInt(cs.fontWeight, 10) >= 600;
    const large = size >= 24 || (size >= 18.66 && bold);
    const need = large ? 3 : 4.5;
    if (ratio < need) {
      const hexish = (c) => '#' + [c.r, c.g, c.b].map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
      results.push({ sel: el.tagName.toLowerCase() + (el.className ? '.' + String(el.className).trim().split(/\s+/).join('.') : ''),
        text: text.slice(0, 40), color: hexish(fg), bg: hexish(bg),
        ratio: Math.round(ratio * 100) / 100, need, fontSize: size });
    }
  }
  return results;
}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8420")
    ap.add_argument("--out", default="output/ui-verify")
    ap.add_argument("--theme", default=None, choices=[None, "light", "dark"])
    ap.add_argument("--viewport", default="1440x900")
    ap.add_argument("--shot", default=None)
    ap.add_argument("--label", default="")
    ap.add_argument("--wait", type=float, default=6.0)
    args = ap.parse_args()

    width, height = (int(v) for v in args.viewport.lower().split("x"))
    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    shot = pathlib.Path(args.shot) if args.shot else (out_dir / f"screen-{args.label or args.viewport}{'-' + args.theme if args.theme else ''}.png")
    shot.parent.mkdir(parents=True, exist_ok=True)

    report: dict = {"base": args.base, "viewport": args.viewport, "theme": args.theme, "shot": str(shot)}

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={"width": width, "height": height},
                                      device_scale_factor=1, color_scheme="dark")
        console_errors, page_errors, failed = [], [], []
        page = context.new_page()
        page.on("console", lambda m: console_errors.append({"type": m.type, "text": m.text}) if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on("requestfailed", lambda r: failed.append({"url": r.url, "err": r.failure}))

        page.goto(args.base, wait_until="networkidle", timeout=60000)
        if args.theme:
            page.evaluate("(t) => document.documentElement.setAttribute('data-theme', t)", args.theme)
        page.wait_for_timeout(int(args.wait * 1000))
        page.screenshot(path=str(shot), full_page=True)

        report["console"] = console_errors
        report["pageErrors"] = page_errors
        report["failedRequests"] = failed
        report["dom"] = page.evaluate(DOM_PROBE)
        report["contrast"] = page.evaluate(A11Y_PROBE)

        # 交互冒烟：切到模型页 / 设置页，再回总览
        smoke = []
        try:
            page.click('#nav a[data-view="models"]')
            page.wait_for_timeout(600)
            smoke.append({"step": "nav-models", "visible": page.is_visible("#view-models")})
            page.click("#settingsBtn")
            page.wait_for_timeout(600)
            smoke.append({"step": "nav-settings", "visible": page.is_visible("#view-settings")})
            page.click("#setBack")
            page.wait_for_timeout(400)
            smoke.append({"step": "back", "visible": page.is_visible("#view-overview")})
            page.click("#ddRange .dd-btn")
            page.wait_for_timeout(300)
            smoke.append({"step": "range-menu", "open": page.is_visible("#ddRangeMenu")})
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
            smoke.append({"step": "range-escape", "closed": not page.is_visible("#ddRangeMenu")})
        except Exception as exc:  # noqa: BLE001
            smoke.append({"step": "error", "error": str(exc)})
        report["smoke"] = smoke
        browser.close()

    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"shot={shot}")
    print(f"console={len(report['console'])} pageErrors={len(report['pageErrors'])} "
          f"failedReq={len(report['failedRequests'])} contrastIssues={len(report['contrast'])} "
          f"domIssues={len(report['dom']['issues'])} focusables={report['dom']['focusables']}")
    print(f"report={out_dir / 'report.json'}")


if __name__ == "__main__":
    main()
