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
```

## 自动更新机制

应用启动与页面加载时会请求 GitHub Releases 最新版本；发现新版后侧边栏出现「⬆ 更新到 vX.Y.Z」，点击后：

1. 下载新版 exe 到临时目录
2. 生成自替换脚本，等待当前进程退出
3. 替换 exe 并自动重启，应用窗口自动打开新版本

整个过程无需重新下载安装包。

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
- **大数据量**：模型表分页 + 本地搜索 + 表头排序；Agent 排行分批渲染、迷你图滚动进入视口才绘制。

历史样式（11 个旧样式表）归档在 `webapp/static/styles/legacy-src/`，
可用 `python tools/consolidate_legacy_css.py` 重新生成 `legacy.css` 并在 `styles.css` 中取消注释回滚。

前端自检脚本：

```bash
python tools/dev_serve.py                  # 开发期只跑 FastAPI（127.0.0.1:8420），改前端刷新即可
python tools/ui_audit.py                   # 硬编码 / 字号阶梯 / 规范覆盖体检 → output/ui-audit.md
python tools/contrast_check.py             # 设计 token 对比度（WCAG AA）→ output/contrast.md
python tools/ui_verify.py                  # 浏览器体检：控制台错误 / DOM / 焦点 / 对比度 → output/ui-verify-*/
python tools/ui_smoke.py                   # 交互回归：路由 / 主题 / 弹窗 / 键盘 / 窄屏（26 项）
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
python -m PyInstaller --noconfirm --clean TokenMonitor.spec
```

> 打包版把 `webapp/static` 一并打进 exe，因此**改前端必须重新打包**才会在安装版里生效；
> 开发期请用 `python tools/dev_serve.py` 或 `python main.py` 直接读源码目录。

## 数据口径说明

- Claude Code 按 `message.id` 去重（原始记录约 65% 为重复流式分片）
- Codex/ZCode 的 `input_tokens` 已含缓存读，统计前先剥离
- 会话内累计值（如 Codex `total_token_usage`、DSH `cacheReadTokens`）每会话只取末条
- 聚合器类数据（CC Switch 的 session 导入行、MiniMax 的 opencode 导入行）已识别并排除，避免重复计数
- 未命中价格的模型不计入金额，页面顶部有占比提示

## License

MIT
