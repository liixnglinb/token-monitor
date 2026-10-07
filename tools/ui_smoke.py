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
        def wait_full_data(pg):
            """等真正的完整结果：partial 也有 matrix，但来源可能一个都没并进来。"""
            pg.wait_for_function(
                "typeof DATA !== 'undefined' && DATA && !DATA.partial && !DATA.building"
                " && (DATA.matrix || []).length > 0 && (DATA.agents || []).length > 0",
                timeout=300000)
            # 这里刻意不用 wait_for_selector("#agentList ...")：reload 会按 hash
            # 恢复到「模型用量」视图，总览那一屏是 hidden 的，侧栏行虽然一直在 DOM 里，
            # 但选择器等待在这种上下文里不稳（实测 30s 超时）。数据到位后再给 1.2s
            # 让各 render*() 收尾，就够了 —— 原来那条 null.range 抛异常的竞态
            # 是"数据没到"造成的，等数据才是对症的修法。
            pg.wait_for_timeout(1200)

        page.goto(args.base, wait_until="networkidle")
        # 等服务端把数据交出来再开始点：首扫期间 DATA 仍是 null，此时直接
        # evaluate renderModelTable() 会读到 null.range 抛异常（实测偶发）。
        # 必须等到"完整结果"而不是部分结果：首扫期间的 partial 也有 matrix，
        # 但来源少、多数 agent 不足两天 —— 排行榜迷你图与抽屉来源列表会是空的，
        # 那几条纹案在扫描中跑就会假红（实测偶发 36/38）。
        page.wait_for_function(
            "typeof DATA !== 'undefined' && DATA && !DATA.partial && !DATA.building"
            " && (DATA.matrix || []).length > 0 && (DATA.agents || []).length > 0",
            timeout=300000)
        page.wait_for_timeout(1200)

        check("初始无 JS 异常", not errors, "; ".join(errors)[:300])
        check("默认落在总览", page.is_visible("#view-overview"))
        initial_hash = page.evaluate("location.hash")
        check("hash 已规范化（视图 + 筛选参数）",
              initial_hash in ("#/overview", "") or initial_hash.startswith("#/overview?"),
              initial_hash)

        # 左侧栏：导航项文字直显（不再靠悬停浮层），左下角是"软件名 + 版本号"身份块
        rail = page.evaluate("""() => {
          const links = [...document.querySelectorAll('#nav a')];
          const id = document.getElementById('settingsBtn');
          const logo = id.querySelector('img');
          const de = document.documentElement;
          return {
            labels: links.map(a => (a.querySelector('.rail-label') || {}).textContent || ''),
            tips: document.querySelectorAll('.rail-tip').length,
            clipped: links.map(a => { const l = a.querySelector('.rail-label');
                                       return l ? l.scrollWidth > l.clientWidth + 1 : true; }),
            idText: id.innerText.replace(/\\s+/g, ' ').trim(),
            logoOk: !!(logo && logo.complete && logo.naturalWidth > 0),
            title: id.title,
            over: de.scrollWidth - de.clientWidth,
          };
        }""")
        check("导航三项都带可见文字标签", len(rail["labels"]) == 3 and all(rail["labels"]),
              str(rail["labels"]))
        check("悬停浮层已移除（不再靠 hover 才知道是什么）", rail["tips"] == 0, str(rail["tips"]))
        check("标签未被截断", not any(rail["clipped"]), str(rail["clipped"]))
        check("左下角显示软件名与版本号",
              "Token Monitor" in rail["idText"] and rail["idText"].startswith("Token Monitor v"),
              rail["idText"])
        check("身份块官方 logo 加载成功", rail["logoOk"])
        check("身份块悬停文字含真实状态", "本机只读模式" in rail["title"] or "扫描" in rail["title"],
              rail["title"])
        check("整页无横向溢出", rail["over"] <= 0, str(rail["over"]))
        pill = page.evaluate("""() => {
          const out = {};
          for (const st of ['update', 'ready', 'done', 'idle']) {
            UPD.state = st; setUpdUI();
            const p = document.getElementById('updBadge');
            out[st] = [p.hidden, p.textContent.trim()];
          }
          UPD.state = 'idle'; setUpdUI();
          return out;
        }""")
        check("更新状态是带字的胶囊而不是孤点",
              pill["update"][1] == "可更新" and pill["ready"][1] == "已下载"
              and pill["done"][1] == "待重启" and pill["idle"][0] is True, str(pill))

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
        # reload 之后必须重新等"完整数据 + 侧栏已渲染"：服务端这时可能正在后台重扫，
        # 直接往下跑会让后面所有依赖排行/抽屉的纹案拿到空列表（实测假红 36/38，
        # 且一次挂两条：排行榜走势 + 抽屉来源列表，都是同一个因）。
        wait_full_data(page)
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

        # ── 趋势图交互：tooltip 逐源拆分 + 点柱"钉住那一天"（只影响右侧排行）──
        tip = page.evaluate("""() => {
          const ch = Chart.getChart('mainChart');
          const labels = ch.data.labels;
          return ch.options.plugins.tooltip.callbacks.afterBody(
            [{ label: labels[labels.length - 1] }]);
        }""")
        check("tooltip 追加当天各数据源拆分", len(tip) >= 3 and "各数据源" in "".join(tip),
              str(tip)[:140])
        dim_agent = page.evaluate("""() => {
          const prev = F.dim; F.dim = 'agent'; renderMain();
          const ch = Chart.getChart('mainChart');
          const labels = ch.data.labels;
          const out = ch.options.plugins.tooltip.callbacks.afterBody(
            [{ label: labels[labels.length - 1] }]);
          F.dim = prev; renderMain();
          return out;
        }""")
        check("维度已是数据源时不重复列", dim_agent == [], str(dim_agent)[:80])

        hit = page.evaluate("""() => {
          const ch = Chart.getChart('mainChart');
          const i = ch.data.labels.length - 1;
          const r = ch.canvas.getBoundingClientRect();
          return { x: r.left + ch.getDatasetMeta(0).data[i].x,
                   y: r.top + (ch.chartArea.top + ch.chartArea.bottom) / 2,
                   label: ch.data.labels[i] };
        }""")
        page.mouse.click(hit["x"], hit["y"])
        page.wait_for_timeout(600)
        pinned = page.evaluate("""() => ({ day: F.day,
          chip: document.getElementById('railDay').innerText,
          hash: location.hash })""")
        check("点柱钉住那一天", pinned["day"] == hit["label"],
              f"{pinned['day']} vs {hit['label']}")
        check("排行卡头出现日期芯片", ("当天" in pinned["chip"]) or ("当月" in pinned["chip"]),
              pinned["chip"])
        check("钉住写入 hash", "day=" + str(hit["label"]) in pinned["hash"], pinned["hash"][:140])
        check("点击过程中无未捕获异常", not errors, "; ".join(errors)[:220])
        # 排行口径必须真的等于图上那一天的量（同一份 rowsFor + 同一个桶）
        same = page.evaluate("""(label) => {
          const ch = Chart.getChart('mainChart');
          const i = ch.data.labels.indexOf(label);
          const chartVal = ch.data.datasets.reduce((s, d) => s + (d.data[i] || 0), 0);
          const sum = railRows().reduce((s, r) => s + r.tokens, 0);
          return { chartVal, sum };
        }""", hit["label"])
        check("钉住后排行口径 = 图上那一天", abs(same["chartVal"] - same["sum"]) <= 1, str(same))
        page.mouse.click(hit["x"], hit["y"])
        page.wait_for_timeout(500)
        check("再点同一天取消钉住", page.evaluate("F.day") is None, str(page.evaluate("F.day")))

        row = page.locator("#dailyList .daily-row[data-day]").first
        day_attr = row.get_attribute("data-day")
        row.press("Enter")
        page.wait_for_timeout(500)
        check("每日明细行 Enter 也能钉住", page.evaluate("F.day") == day_attr,
              f"{page.evaluate('F.day')} vs {day_attr}")
        check("钉住的行带 pinned 态与 aria-pressed",
              page.locator('#dailyList .daily-row.pinned[aria-pressed="true"]').count() == 1)
        heights = page.evaluate("""() => [...document.querySelectorAll('#dailyList .daily-row')]
          .slice(0, 6).map(el => Math.round(el.getBoundingClientRect().height))""")
        check("钉住不会把那一行撑高（等高）", len(set(heights)) == 1, str(heights))
        page.reload(wait_until="networkidle")
        wait_full_data(page)
        page.wait_for_timeout(800)
        check("刷新后钉住状态恢复", page.evaluate("F.day") == day_attr,
              str(page.evaluate("F.day")))
        page.evaluate("() => { F.day = null; persistFilters(); renderAll(); }")
        page.wait_for_timeout(400)

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
        # 上一步的 Toast 浮在右下角，正好压在 #filterBtn 上 —— 先等它消失
        try:
            page.wait_for_selector(".toast", state="detached", timeout=6000)
        except Exception:
            pass
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
