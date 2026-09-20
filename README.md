# Token Monitor

本地 Agent Token 用量统计 —— 一条命令扫描本机所有 AI 编程工具的 token 消耗与成本，DeepSeek 风格的深色看板。

![panel](https://img.shields.io/badge/panel-DeepSeek%20style-4D6BFE) ![platform](https://img.shields.io/badge/platform-Windows-blue) ![python](https://img.shields.io/badge/python-3.12%2B-green)

## 功能

- **全源扫描**：Claude Code、Codex、ZCode、OpenCode、Hermes、MHAgent、Agnes、OpenClaw、DSH 等 9 个数据源，内置去重与缓存语义修正（详见 `probe_v3_allsources.py`）
- **成本估算**：LiteLLM 价格库（1.2 万+ 模型）+ CC Switch 价格表补漏，未命中价格单独标注
- **看板**：时间粒度（今天/昨天/近7/30/90天/本月/上月/全部）× 数据源 × 模型自由筛选；按维度堆叠柱状图；按模型分解（请求 / Tokens 双迷你图）；数据源与模型成本两张明细表
- **导出**：当前筛选一键导出 CSV
- **自动更新**：内置更新器，比对 GitHub Releases，一键下载替换重启（安装版 / 便携版通用）

## 使用

### 安装版（推荐）

从 [Releases](https://github.com/liixnglinb/token-monitor/releases) 下载 `TokenMonitor-setup-vX.Y.Z.exe`，安装后自动启动，**直接打开应用窗口**（内嵌 WebView2，不跳系统浏览器）。

### 便携版

下载 `TokenMonitor-portable-vX.Y.Z.zip` 解压，双击 `TokenMonitor.exe` 即可；更新器与安装版共用，软件内可直接升级。

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

## 构建（开发者）

推送 `v*` 标签即可，GitHub Actions 自动完成 PyInstaller 打包、Inno Setup 安装包、便携 zip，并发布 Release：

```bash
git tag v1.0.1
git push origin v1.0.1
```

本地构建：`pip install -r requirements.txt pyinstaller && pyinstaller --onefile --name TokenMonitor main.py`。

## 数据口径说明

- Claude Code 按 `message.id` 去重（原始记录约 65% 为重复流式分片）
- Codex/ZCode 的 `input_tokens` 已含缓存读，统计前先剥离
- 会话内累计值（如 Codex `total_token_usage`、DSH `cacheReadTokens`）每会话只取末条
- 聚合器类数据（CC Switch 的 session 导入行、MiniMax 的 opencode 导入行）已识别并排除，避免重复计数
- 未命中价格的模型不计入金额，页面顶部有占比提示

## License

MIT
