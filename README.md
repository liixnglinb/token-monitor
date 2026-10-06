# Token Monitor

本地 Agent Token 用量统计 —— 一条命令扫描本机所有 AI 编程工具的 token 消耗与成本，全暗仪表舱风格看板。

![panel](https://img.shields.io/badge/panel-dark%20instrument-6C9BFF) ![platform](https://img.shields.io/badge/platform-Windows-blue) ![python](https://img.shields.io/badge/python-3.12%2B-green)

## 功能

- **全源扫描**：Claude Code、Codex、ZCode、OpenCode、Hermes、MHAgent、Agnes、OpenClaw、DSH、Box Agent、Cline、WorkBuddy AI 等 12 个已计入数据源，内置去重与缓存语义修正（详见 `probe_v3_allsources.py`）
- **覆盖可见**：面板列出本机检出的全部来源 —— 已计入的按用量排序，未计入的（本地不记录用量/加密/需官方 API）单独成组并注明原因
- **成本估算**：LiteLLM 价格库（1.2 万+ 模型）+ CC Switch 价格表补漏，未命中价格单独标注
- **看板**：时间粒度（今天/昨天/近7/30/90天/本月/上月/全部）× 数据源 × 模型自由筛选；按维度堆叠柱状图；按模型分解（请求 / Tokens 双迷你图）；数据源与模型成本两张明细表
- **导出**：当前筛选一键导出 CSV
- **自动更新**：内置更新器，比对 GitHub Releases，一键下载替换重启

## 使用

### 安装版（推荐）

从 [Releases](https://github.com/liixnglinb/token-monitor/releases) 下载 `TokenMonitor-setup-vX.Y.Z.exe`，安装后自动启动，**直接打开应用窗口**（内嵌 WebView2，不跳系统浏览器）。

### 从源码运行

```bash
pip install -r requirements.txt
python main.py            # 起内嵌窗口；服务在 http://127.0.0.1:8420
python tools/dev_serve.py # 只起服务不起窗口，改前端时用这个
```

## 验收（改完必须全绿才算改完）

```bash
pip install -r requirements.txt -r requirements-dev.txt
playwright install chromium          # 界面验收要真浏览器，不跑 headless 断言没意义
python -m pytest tests -q            # 单元 + HTTP 契约
python tools/dev_serve.py 8420 &     # 起服务后跑两套浏览器用例
python tools/ui_smoke.py             # 交互冒烟 38 条
python tools/final_check.py          # 主题 / 对比度 / 无障碍 / 布局 51 条
python -m pip_audit -r requirements.txt   # 依赖漏洞，必须 0 命中
```

推送 `v*` 标签时 CI 会再跑一遍 pytest + 前端语法检查 + `pip-audit --strict`，
不过就不出包。两条写下来的坑：

- **`requirements*.txt 里不能写中文注释**：`pip-audit` 按本地编码读文件，
  Windows 上是 cp936，UTF-8 注释会让扫描直接崩（`UnicodeDecodeError`）。
- **前端八个脚本共用一个全局作用域**：单个文件 `node --check` 过了不代表能跑，
  跨文件重名的 `let` 会让整块脚本静默中止（症状是"某个函数怎么就 undefined 了"）。
  必须按 `index.html` 的加载顺序拼起来再查一遍，CI 里已经是这么做的。

## 排障与留痕

| 位置（`%LOCALAPPDATA%\TokenMonitor\`） | 是什么 |
| --- | --- |
| `app.log` | 后端日志**以及界面未捕获异常**（前端经 `POST /api/client-error` 落同一份日志，只含消息/文件名/行号，不含任何用量内容） |
| `last-build.json` | 上次成功扫描的结果快照，开机直接复用（所以不会每次打开都重扫） |
| `scan-cache.json` | 文件级增量缓存与"该源无用量"判定，按文件指纹失效 |
| `settings.json` | 刷新间隔等设置，越界值在读取时钳制 |
| `custom-pricing.json` | 可选：自己补的模型价目表（仓库里有 `.example.json` 模板） |

界面里出的错会被兜住：toast 提示一次（同一条 60s 内不重复弹），摘要进 `app.log`，
数据区保留上一次的有效结果不被清空。

## 自动更新机制

启动即检查一次、此后每 30 分钟一次；发现新版本会自动**测速挑最快下载源**并下载，
顶栏出现真实进度（不是编造的百分比），下载完成后弹窗问「现在更新并重启 / 稍后」。
入口在 **设置 › 软件更新** 那张卡片（检查、下载进度、失败原因与重试都在那里），
安装是两段式：先把新版 exe 落到临时目录并校验「体积 + `.sha256`」双闸，
确认后才替换 exe 并重启，替换过程由脱离父进程的独立脚本完成。

## 界面（前端结构）

界面已按单一设计系统重建，规范全文见 [`docs/ui-spec.md`](docs/ui-spec.md)。

- **样式只有 5 个文件**：`styles.css` 是唯一入口，按 `@layer legacy < base < components < layout` 组织；
  `tokens.css` 是**唯一数值来源**（颜色 / 字号 / 间距 / 圆角 / 阴影 / 动效 / 层级，深浅两套主题）。
- **主题**：跟随系统（默认）/ 浅色 / 深色，顶栏按钮循环切换，设置页可选；选择记在 `localStorage("tm-theme")`；
  图表颜色从 CSS 变量读取，切主题即换色。
- **组件**：按钮 / 输入 / 表格 / 卡片 / 分段 / 下拉 / 弹窗 / 确认框 / Toast / 骨架屏各有统一样式与六种状态；
  数据区一律覆盖「加载 / 空 / 错误」三态。
- **导航**：hash 深链接（`#/overview`、`#/models`、`#/settings/data`），支持浏览器前进/后退；
  窄屏自动切换为底部标签栏。
- **可访问性**：统一焦点环、弹窗焦点陷阱、`aria-*` 语义、对比度按 WCAG AA 校验（深浅主题各 0 处不达标）、
  快捷键 `1/2/G//R/Esc`、尊重 `prefers-reduced-motion`。
- **性能**：排行榜迷你走势是**纯 SVG sparkline**（0 额外 Chart.js 实例，全站恒定 2 个：
  主图 + 环形图）；主题切换时图表按新 token 自动重绘；表格分页 + 本地搜索 + 表头排序 + 计费类型筛选
  （全部 / 按量计费 / 套餐 / 未计价）；Agent 排行分批渲染。
- **状态即地址**：筛选条件（range/agent/metric/grain/dim/billing）序列化进 hash 路由，
  刷新、前进后退、分享链接都不丢过滤视图。
- **窄屏**：侧栏隐藏后由底部标签栏接管导航，顶栏「筛选」按钮打开数据源抽屉（与侧栏共用同一份渲染）；
  模型表自动降级为逐行卡片，杜绝横向破版。
- **扫描真状态**：重新扫描期间按钮显示真实耗时并禁用，1s 轮询后端 `busy` 状态直到完成，
  不再出现"1 秒恢复但数据没变"的假反馈；已有扫描进行时不会重复排队。
- **原生标题栏联动**：切换主题时通过 pywebview js_api 调用 DWM 同步 Windows 标题栏明暗。

历史样式（11 个旧样式表与合并产物 legacy.css）已从仓库移除，git 历史中可回溯；
`styles.css` 里保留了 `@layer legacy` 占位与注释掉的 import 行，便于临时对比时恢复。

前端自检脚本：

```bash
python tools/dev_serve.py                  # 开发期只跑 FastAPI（127.0.0.1:8420），改前端刷新即可
python tools/ui_audit.py                   # 硬编码 / 字号阶梯 / 规范覆盖体检 → output/ui-audit.md
python tools/contrast_check.py             # 设计 token 对比度（WCAG AA）→ output/contrast.md
python tools/ui_verify.py                  # 浏览器体检：控制台错误 / DOM / 焦点 / 对比度 → output/ui-verify-*/
python tools/ui_smoke.py                   # 交互回归：路由/主题/弹窗/键盘/窄屏/抽屉/计费筛选（38 项）
python tools/final_check.py                # 收尾综合验证：主题生效/组件与三态/无障碍/焦点（36 项）
python tools/check_theme_chart.py          # 主题切换后 Chart.js 实例按新 token 重绘的专项断言
python tools/style_snapshot.py --out x.json [--diff before.json]   # 计算样式快照对比
```

## 构建（开发者）

推送 `v*` 标签即可，GitHub Actions 自动完成 PyInstaller 打包、Inno Setup 安装包，并发布 Release：

```bash
git tag v1.0.1
git push origin v1.0.1
```

本地构建（等价于 CI 的打包参数，产物在 `dist/`）：

```bash
pip install -r requirements.txt pyinstaller
python -c "open('version.txt','w').write('vX.Y.Z')"     # 无 BOM；CI 里同样这么写
pyinstaller --noconfirm --onefile --name TokenMonitor --windowed --icon icon.ico \
  --add-data "webapp/static;webapp/static" --add-data "version.txt;." --add-data "icon.ico;." \
  --hidden-import uvicorn --hidden-import uvicorn.loops --hidden-import uvicorn.loops.auto \
  --hidden-import uvicorn.protocols --hidden-import uvicorn.protocols.http \
  --hidden-import uvicorn.protocols.http.h11_impl --hidden-import uvicorn.lifespan \
  --hidden-import uvicorn.lifespan.on --hidden-import webview \
  --hidden-import webview.platforms.winforms --hidden-import webview.platforms.edgechromium \
  --hidden-import clr_loader --hidden-import pythonnet --hidden-import clr \
  --hidden-import pystray --hidden-import pystray._win32 --collect-all pystray \
  --collect-all PIL --hidden-import _cffi_backend --collect-all cffi \
  --collect-all clr_loader --collect-all pythonnet main.py
iscc /DAppVersion="vX.Y.Z" installer.iss                # Inno Setup 出安装版
```

> 仓库里**没有** `TokenMonitor.spec` —— 它是 PyInstaller 的生成物（已 gitignore），
> 参数以上面这条命令行为准（与 `.github/workflows/release.yml` 保持一致）。
> `version.txt` 必须无 BOM，带 BOM 会让更新器的版本解析抛错，出现"已是最新还提示更新"。

> 打包版把 `webapp/static` 一并打进 exe，因此**改前端必须重新打包**才会在安装版里生效；
> 开发期请用 `python tools/dev_serve.py` 或 `python main.py` 直接读源码目录。

## 数据流与扩展点（给接手的人）

单向、一处写、多处读，没有回写环：

```
本机各 Agent 日志 / sqlite
   └─ probe_v3_allsources.py      手写扫描器(ORIGINAL/NEW/EXTRA) + 注册表驱动源
        └─ scan_cache.py          文件指纹增量缓存 + "该源无用量"判定
             └─ server._build()   pricing 计价 → _aggregate() 成 (date,agent,model) 矩阵
                  │                （扫描中途每 ≥2s 回抛一次 partial）
                  └─ refresher.Refresher   后台线程：调度 / 忙碌合并 / 脏标记
                       ├─ save_snapshot() → %LOCALAPPDATA%\TokenMonitor\last-build.json
                       └─ /api/summary    → 前端 DATA（唯一写入点 app.js）
                                             └─ render.js 各 render*() 只读 DATA/F/PAGE
```

- **加一个数据源**：能在 `sources_registry.py` 里描述路径与格式就别写代码 ——
  `jsonl_generic` / sqlite 两条通用解析路径已覆盖大部分；只有语义特殊
  （累计值、分片重复、需要剥离缓存读）才在 `probe_v3_allsources.py` 里加手写扫描器，
  并登记进 `HANDLED_IDS` 防止注册表重复计入。
- **加一个指标/图表**：数据只在 `_aggregate()` 出，前端只加 `render*()` 与 `CHOICE` 表条目，
  不要在渲染层现算口径 —— 口径必须与下载页 `dist-page/export_data.py` 一致
  （它走的是同一条 `_aggregate`，这就是"网站数字与面板对得上"的保证）。
- **改设置项**：`refresher.DEFAULTS` 加键 + `_clamp()` 定边界，前端才会拿到钳制后的值。
- **下载页**：唯一生成器在 `dist-page/`（`export_data` → `capture_shots` →
  `build_assets` → `build`），**不要直接改产物 HTML**；它同时写
  `site/index.html`（本仓库存档）和网站仓库的 `public/token-monitor/`。

## 数据口径说明

- Claude Code 按 `message.id` 去重（原始记录约 65% 为重复流式分片）
- Codex/ZCode 的 `input_tokens` 已含缓存读，统计前先剥离
- 会话内累计值（如 Codex `total_token_usage`、DSH `cacheReadTokens`）每会话只取末条
- 聚合器类数据（CC Switch 的 session 导入行、MiniMax 的 opencode 导入行）已识别并排除，避免重复计数
- 未命中价格的模型不计入金额，页面顶部有占比提示

## License

MIT
