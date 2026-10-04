# -*- coding: utf-8 -*-
"""为下载页截取 v1.9.15 新 UI 图（尺寸对齐旧资产），输出 PNG + WebP。

资产对应（主仓库 public/token-monitor/）：
  shots/overview.webp 1320x806 · shots/models.webp 1320x806 ·
  shots/scan.webp 1320x403    · app-shot.webp 1168x645
"""
from __future__ import annotations

import pathlib

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "output" / "shots" / "v1915"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:8421"

SHOTS = [
    ("overview", 1320, 806, None),
    ("models", 1320, 806, "models"),
    ("scan", 1320, 403, "settings-data"),
    ("app-shot", 1168, 645, None),
]

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for name, width, height, view in SHOTS:
        page = browser.new_page(viewport={"width": width, "height": height})
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_function(
            "() => typeof DATA !== 'undefined' && DATA && !DATA.building && DATA.range",
            timeout=30000)
        page.wait_for_timeout(900)
        if view == "models":
            page.evaluate("window.TMUI.route('models')")
        elif view == "settings-data":
            page.evaluate("window.TMUI.route('settings','data')")
        page.evaluate("window.TMTheme.set('dark', {announce:false})")
        page.wait_for_timeout(900)
        png = OUT / f"{name}.png"
        page.screenshot(path=str(png))
        Image.open(png).convert("RGB").save(OUT / f"{name}.webp", "WEBP", quality=85)
        print(f"{name}: {png.stat().st_size//1024}KB png -> "
              f"{(OUT / (name + '.webp')).stat().st_size//1024}KB webp", flush=True)
        page.close()
    browser.close()
print("done ->", OUT)
