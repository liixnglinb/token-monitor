# -*- coding: utf-8 -*-
"""为 UI 设计规范文档（docs/ui-spec.md）截取实拍图，输出到 docs/shots/。

与 tools/capture_release_shots.py 的区别：那个出的是下载页用的固定尺寸资产（1320×806 等），
本脚本出的是规范文档「多端与主题实拍」表里引用的四张图（整页/单屏/浅色/窄屏）。

用法：
    python tools/capture_spec_shots.py                    # 默认 127.0.0.1:8421
    python tools/capture_spec_shots.py --base http://127.0.0.1:8433
"""
from __future__ import annotations

import argparse
import pathlib

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "shots"

# (文件名, 视口宽, 视口高, 视图, 主题, 是否整页)
SHOTS = [
    ("overview-dark", 1440, 900, "overview", "dark", True),
    ("models-dark", 1440, 900, "models", "dark", False),
    ("settings-light", 1440, 900, "settings", "light", False),
    ("overview-mobile", 390, 844, "overview", "dark", True),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8421")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for name, width, height, view, theme, full in SHOTS:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(args.base, wait_until="networkidle")
            # 等真实数据渲染完成，避免截到骨架屏
            page.wait_for_function(
                "() => typeof DATA !== 'undefined' && DATA && !DATA.building && DATA.range",
                timeout=30000)
            page.evaluate(
                "([t, v]) => { window.TMTheme.set(t, {announce:false}); window.TMUI.route(v); }",
                [theme, view])
            page.wait_for_timeout(1200)
            png = OUT / f"{name}.png"
            page.screenshot(path=str(png), full_page=full)
            print(f"{name}: {width}x{height} theme={theme} full={full} -> {png.stat().st_size // 1024}KB",
                  flush=True)
            page.close()
        browser.close()
    print("done ->", OUT)


if __name__ == "__main__":
    main()
