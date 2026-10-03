# -*- coding: utf-8 -*-
"""验证主题切换后 Chart.js 实例真的重绘（tooltip/网格/坐标轴用新主题色）。"""
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:8421", wait_until="networkidle")

    # 等 DATA 真正加载（图表建出来），而不是盲等固定时长
    # 注意：DATA/MAIN 是顶层 let 声明，不挂 window，必须用裸标识符访问
    page.wait_for_function("() => typeof DATA !== 'undefined' && DATA && !DATA.building && DATA.range && Object.keys(Chart.instances).length >= 2",
                           timeout=30000)
    page.wait_for_timeout(400)

    def chart_colors():
        return page.evaluate(
            """() => Object.keys(Chart.instances).map(id => {
                const c = Chart.instances[id];
                const s = c.options.scales || {};
                const yTick = s.y && s.y.ticks ? s.y.ticks.color : null;
                const grid = s.y && s.y.grid ? s.y.grid.color : null;
                const tip = c.options.plugins.tooltip || {};
                return { type: c.config.type, yTick, grid,
                         tipBg: tip.backgroundColor, tipTitle: tip.titleColor };
            })"""
        )

    page.evaluate("window.TMTheme.set('dark', {announce:false})")
    page.wait_for_timeout(700)
    dark = chart_colors()
    page.screenshot(path="output/shots/r2-theme-dark-chart.png")

    page.evaluate("window.TMTheme.set('light', {announce:false})")
    page.wait_for_timeout(900)     # 等 tm:theme 触发的重绘完成
    light = chart_colors()
    page.screenshot(path="output/shots/r2-theme-light-chart.png")

    print("dark :", dark)
    print("light:", light)
    main_dark, main_light = dark[0], light[0]
    recolored = (main_dark["yTick"] != main_light["yTick"]
                 or main_dark["tipBg"] != main_light["tipBg"]
                 or main_dark["grid"] != main_light["grid"])
    print("主题切换后图表配色已重绘:", recolored)
    print("errors:", errors if errors else "none")
    browser.close()
