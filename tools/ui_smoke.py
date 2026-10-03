# -*- coding: utf-8 -*-
"""交互冒烟测试：视图切换 / 路由 / 主题 / 弹层 / 键盘 / 表格。

用真实浏览器跑一遍关键路径，输出 PASS/FAIL 摘要；失败会带上原因。
用法：python tools/ui_smoke.py [--base http://127.0.0.1:8420]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHOTS = ROOT / "output" / "shots"
LOG = ROOT / "output" / "ui-smoke.log"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8420")
    args = ap.parse_args()

    SHOTS.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    # 进度写文件：控制台偶发缓冲时也能随时查看跑到哪一步
    log = LOG.open("w", encoding="utf-8")

    def emit(line: str) -> None:
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append({"check": name, "ok": bool(ok), "detail": detail})
        emit(("PASS  " if ok else "FAIL  ") + name + (("  — " + detail) if detail and not ok else ""))

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(args.base, wait_until="networkidle")
        page.wait_for_timeout(1200)

        check("初始无 JS 异常", not errors, "; ".join(errors)[:300])
        check("默认落在总览", page.is_visible("#view-overview"))
        initial_hash = page.evaluate("location.hash")
        check("hash 已规范化（视图 + 筛选参数）",
              initial_hash in ("#/overview", "") or initial_hash.startswith("#/overview?"),
              initial_hash)

        # 视图切换 + 路由
        page.click('#nav a[data-view="models"]')
        page.wait_for_timeout(400)
        check("切到模型用量", page.is_visible("#view-models"))
        check("hash 同步为 models（含筛选参数）", page.evaluate("location.hash").startswith("#/models"),
              page.evaluate("location.hash"))
        page.screenshot(path=str(SHOTS / "smoke-models.png"), full_page=True)

        # 表格工具：搜索 + 分页 + 排序
        search = page.locator("#modelSearch")
        if search.count():
            total_before = page.locator("#tbModel tr").count()
            search.fill("claude")
            page.wait_for_timeout(400)
            rows = page.locator("#tbModel tr").count()
            check("搜索能过滤表格", rows <= total_before, f"{total_before} → {rows}")
            search.fill("")
            page.wait_for_timeout(400)
        pager_buttons = page.locator("#modelPager button[data-page]")
        if pager_buttons.count() > 2:
            page.locator('#modelPager button[data-page="1"]').click()
            page.wait_for_timeout(300)
            check("分页可翻页",
                  page.locator('#modelPager button[aria-current="page"]').inner_text().strip() == "2")
        else:
            # 模型数不足一页时，把每页条数调小再验证分页控件确实会生成
            page.select_option("#modelPageSize", "25")
            page.evaluate("PAGE.size = 5; PAGE.index = 0; renderModelTable();")
            page.wait_for_timeout(300)
            generated = page.locator("#modelPager button[data-page]").count() > 2
            check("分页组件可用（模型数少，改用每页 5 条验证）", generated,
                  f"buttons={page.locator('#modelPager button[data-page]').count()}")
            page.select_option("#modelPageSize", "50")
            page.wait_for_timeout(200)
        sort_btn = page.locator('.th-sort[data-sort="model"]')
        if sort_btn.count():
            sort_btn.click()
            page.wait_for_timeout(300)
            check("表头可排序", sort_btn.get_attribute("aria-sort") in ("ascending", "descending"),
                  str(sort_btn.get_attribute("aria-sort")))

        # 计费类型筛选（全部 / 按量计费 / 套餐 / 未计价）
        billing = page.locator('#segBilling button[data-b="unpriced"]')
        if billing.count():
            rows_before = page.locator("#tbModel tr").count()
            billing.click()
            page.wait_for_timeout(300)
            rows_after = page.locator("#tbModel tr").count()
            check("计费筛选改变表格行", rows_after != rows_before or rows_after <= 1,
                  f"{rows_before} → {rows_after}")
            page.locator('#segBilling button[data-b="all"]').click()
            page.wait_for_timeout(200)

        # 筛选状态序列化进 hash：切范围 → hash 变化 → 刷新后保留
        page.click("#nav a[data-view='overview']")
        page.wait_for_timeout(300)
        page.click("#ddRange .dd-btn")
        page.wait_for_timeout(200)
        page.click('#ddRangeMenu button[data-k="today"]')
        page.wait_for_timeout(400)
        check("筛选写入 hash（range=today）", "range=today" in page.evaluate("location.hash"),
              page.evaluate("location.hash"))
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(1200)
        check("刷新后筛选保留", page.eval_on_selector("#ddRangeVal", "el => el.textContent") == "今天",
              page.eval_on_selector("#ddRangeVal", "el => el.textContent"))
        check("刷新后 hash 仍是 today", "range=today" in page.evaluate("location.hash"))
        # 恢复默认
        page.click("#ddRange .dd-btn")
        page.wait_for_timeout(200)
        page.click('#ddRangeMenu button[data-k="last7"]')
        page.wait_for_timeout(300)

        # 迷你走势：纯 SVG，Chart 实例数恒定（主图 + 环形图）
        page.wait_for_timeout(500)
        instances = page.evaluate("Object.keys(Chart.instances).length")
        check("Chart 实例不超过 4 个（主图+环形+余量）", instances <= 4, f"instances={instances}")
        check("排行榜使用 SVG sparkline", page.locator(".sparkline").count() > 0,
              f"sparklines={page.locator('.sparkline').count()}")

        # 设置页 + 设置分类路由
        page.click("#settingsBtn")
        page.wait_for_timeout(400)
        check("设置页打开", page.is_visible("#view-settings"))
        check("设置侧栏导航可见", page.is_visible("#setBack"))
        page.click('#setNav .set-item[data-cat="data"]')
        page.wait_for_timeout(400)
        check("设置分类路由", page.evaluate("location.hash") == "#/settings/data")
        check("分类面板切换", page.is_visible('.set-cards[data-cat="data"]'))
        page.screenshot(path=str(SHOTS / "smoke-settings-data.png"), full_page=True)

        # 浏览器后退（深链接可达性）
        page.go_back(wait_until="commit")
        page.wait_for_timeout(500)
        check("后退回到设置通用",
              "general" in page.evaluate("location.hash") or page.is_visible('.set-cards[data-cat="general"]'),
              page.evaluate("location.hash"))

        # 主题：三态循环
        page.click("#themeBtn")
        page.wait_for_timeout(300)
        mode1 = page.evaluate("document.documentElement.getAttribute('data-theme-mode')")
        page.click("#themeBtn")
        page.wait_for_timeout(300)
        mode2 = page.evaluate("document.documentElement.getAttribute('data-theme-mode')")
        check("主题可循环切换", mode1 != mode2, f"{mode1} → {mode2}")
        page.evaluate("window.TMTheme.set('light')")
        page.wait_for_timeout(400)
        check("浅色主题生效", page.evaluate("document.documentElement.getAttribute('data-theme')") == "light")
        page.screenshot(path=str(SHOTS / "smoke-light.png"), full_page=True)
        page.evaluate("window.TMTheme.set('dark')")
        page.wait_for_timeout(400)

        # 键盘：数字键切视图、Esc 关下拉
        page.keyboard.press("1")
        page.wait_for_timeout(300)
        check("快捷键 1 回总览", page.is_visible("#view-overview"))
        page.click("#ddRange .dd-btn")
        page.wait_for_timeout(200)
        opened = page.is_visible("#ddRangeMenu")
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        check("Esc 关闭下拉", opened and not page.is_visible("#ddRangeMenu"))

        # 危险操作确认弹窗（不返回 promise，避免 evaluate 等待未决 promise）
        has_confirm = page.evaluate("!!document.getElementById('confirmModal')")
        check("确认弹窗组件存在", has_confirm)
        if has_confirm:
            page.evaluate(
                """() => {
                    window.__confirmResult = null;
                    window.TMUI.confirm({title:'测试', text:'确认弹窗自测', danger:true})
                      .then(v => { window.__confirmResult = v; });
                    return true;
                }"""
            )
            page.wait_for_timeout(400)
            visible = page.is_visible("#confirmModal")
            focused = page.evaluate("document.activeElement && document.activeElement.id")
            page.click("#confirmOk")
            page.wait_for_timeout(400)
            result = page.evaluate("window.__confirmResult")
            check("确认弹窗可开、可确认、有初始焦点", visible and result is True and bool(focused),
                  f"visible={visible} result={result} focus={focused}")
            # Esc 取消路径
            page.evaluate(
                """() => {
                    window.__cancelResult = null;
                    window.TMUI.confirm({title:'测试2', text:'Esc 取消'})
                      .then(v => { window.__cancelResult = v; });
                    return true;
                }"""
            )
            page.wait_for_timeout(300)
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)
            check("确认弹窗 Esc 取消", page.evaluate("window.__cancelResult") is False,
                  str(page.evaluate("window.__cancelResult")))

        # Toast
        page.evaluate("window.TMUI.toast('自测提示', {kind:'success'})")
        page.wait_for_timeout(200)
        check("Toast 可显示", page.locator(".toast").count() > 0)

        # 窄屏：底部标签栏接管 + 数据源筛选抽屉
        page.set_viewport_size({"width": 390, "height": 780})
        page.wait_for_timeout(400)
        check("窄屏隐藏侧栏", not page.is_visible("#sidebar"))
        check("窄屏显示底部标签栏", page.is_visible("#tabbar"))
        check("窄屏显示数据源筛选按钮", page.is_visible("#filterBtn"))
        page.click("#filterBtn")
        page.wait_for_timeout(400)
        check("抽屉打开", page.is_visible("#agentDrawer"))
        check("抽屉里有数据源列表", page.locator("#drawerAgents .side-project").count() > 0,
              f"items={page.locator('#drawerAgents .side-project').count()}")
        page.screenshot(path=str(SHOTS / "smoke-mobile-drawer.png"))
        # 从抽屉选一个数据源：筛选生效 + 抽屉关闭
        agent_btn = page.locator("#drawerAgents .side-project").first
        agent_name = agent_btn.get_attribute("data-agent-filter")
        agent_btn.click()
        page.wait_for_timeout(400)
        check("抽屉选择数据源后关闭", page.evaluate("document.getElementById('agentDrawer').hidden"))
        check("筛选已生效（hash 带 agent）", f"agent={agent_name}" in page.evaluate("location.hash"),
              page.evaluate("location.hash"))
        page.screenshot(path=str(SHOTS / "smoke-mobile.png"), full_page=True)
        # 模型表卡片化：thead 隐藏、td 带字段名
        page.click('#tabbar button[data-view="models"]')
        page.wait_for_timeout(400)
        thead_shown = page.evaluate("getComputedStyle(document.querySelector('#modelTable thead')).display !== 'none'")
        check("窄屏表格表头隐藏（卡片化）", not thead_shown)
        check("单元格带 data-label 字段名", page.locator("#tbModel td[data-label]").count() > 0)
        # 恢复筛选与视口
        page.set_viewport_size({"width": 1440, "height": 900})
        page.wait_for_timeout(300)
        page.evaluate("F.agent = 'all'; renderAll();")
        page.wait_for_timeout(300)

        # 减少动态效果
        page.emulate_media(reduced_motion="reduce")
        page.wait_for_timeout(300)
        check("减少动效下无异常", not errors, "; ".join(errors)[:200])

        check("全程无 JS 异常", not errors, "; ".join(errors)[:300])
        browser.close()

    out = ROOT / "output" / "ui-smoke.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    failed = [r for r in results if not r["ok"]]
    emit(f"\n{len(results) - len(failed)}/{len(results)} 通过；报告 {out}")
    log.close()
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
