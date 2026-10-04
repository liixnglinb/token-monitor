# -*- coding: utf-8 -*-
"""把 Token Monitor 全部源代码整合成单份 Markdown 放到桌面。

结构：版本头 + 目录树 + 按模块分区的代码（自动处理嵌套围栏）。
输出：仓库根目录下 TokenMonitor源代码_v1.9.15.md（原先写死本机桌面绝对路径，已改为仓库内相对路径）
"""
from __future__ import annotations

import datetime
import pathlib
import subprocess

ROOT = pathlib.Path(r"..\token-monitor")
OUT = ROOT / "TokenMonitor源代码_v1.9.15.md"

SECTIONS: list[tuple[str, list[str]]] = [
    ("一、后端 Python（服务 / 窗口 / 更新 / 计价 / 扫描）", [
        "main.py",
        "server.py",
        "updater.py",
        "pricing.py",
        "scan_cache.py",
        "sources_registry.py",
        "probe_v3_allsources.py",
    ]),
    ("二、前端 HTML（页面骨架）", [
        "webapp/static/index.html",
    ]),
    ("三、前端 JavaScript（核心 / 基建 / 渲染 / 交互）", [
        "webapp/static/js/core.js",
        "webapp/static/js/theme.js",
        "webapp/static/js/ui.js",
        "webapp/static/js/data.js",
        "webapp/static/js/charts.js",
        "webapp/static/js/render.js",
        "webapp/static/js/interactions.js",
        "webapp/static/js/updater.js",
        "webapp/static/js/app.js",
    ]),
    ("四、前端 CSS（设计系统四层）", [
        "webapp/static/styles/styles.css",
        "webapp/static/styles/tokens.css",
        "webapp/static/styles/base.css",
        "webapp/static/styles/components.css",
        "webapp/static/styles/layout.css",
    ]),
    ("五、打包与发布配置", [
        "requirements.txt",
        "installer.iss",
        ".github/workflows/release.yml",
    ]),
    ("六、测试", [
        "tests/test_token_detection.py",
        "tests/test_updater_preflight.py",
        "tests/test_version_file.py",
    ]),
    ("七、开发与自检工具", [
        "tools/dev_serve.py",
        "tools/ui_audit.py",
        "tools/contrast_check.py",
        "tools/ui_verify.py",
        "tools/ui_smoke.py",
        "tools/final_check.py",
        "tools/check_theme_chart.py",
        "tools/style_snapshot.py",
        "tools/class_inventory.py",
        "tools/check_ci.py",
        "tools/compare_release_exe.py",
        "tools/verify_remote.py",
        "tools/capture_release_shots.py",
    ]),
    ("八、UI 规范文档", [
        "docs/ui-spec.md",
    ]),
]


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                              text=True, encoding="utf-8", errors="replace").stdout.strip()
    except Exception:
        return "?"


def fence(text: str) -> str:
    """代码里若出现 ``` 则升级为四反引号围栏。"""
    return "````" if "```" in text else "```"


def lang_of(path: str) -> str:
    return {".py": "python", ".js": "javascript", ".css": "css", ".html": "html",
            ".md": "markdown", ".yml": "yaml", ".iss": "ini", ".txt": "text",
            ".spec": "python"}.get(pathlib.Path(path).suffix, "")


def main() -> None:
    commit = git("log", "-1", "--format=%h %s")
    version = (ROOT / "version.txt").read_text("utf-8").strip().lstrip("\ufeff")
    lines: list[str] = []
    add = lines.append
    add("# Token Monitor 源代码全集")
    add("")
    add(f"- 版本：v{version}　生成时间：{datetime.date.today().isoformat()}")
    add(f"- 仓库：liixnglinb/token-monitor　HEAD：`{commit}`")
    add(f"- 本文件由 `tools/export_source_md.py` 自动生成，共 {sum(len(fs) for _, fs in SECTIONS)} 个文件。")
    add("")

    add("## 目录结构")
    add("")
    add("```text")
    add("token-monitor/")
    add("├─ main.py               # 窗口/托盘/标题栏融合/启动")
    add("├─ server.py             # FastAPI：/api/summary|reload|settings|version|update")
    add("├─ updater.py            # 自更新（预检/下载/校验/自替换）")
    add("├─ pricing.py            # 模型计价（LiteLLM 价表 + 自定义价）")
    add("├─ scan_cache.py         # 文件级扫描缓存")
    add("├─ sources_registry.py   # 注册表驱动的 81 条数据源路径")
    add("├─ probe_v3_allsources.py# 10 个手写扫描器 + 数据源探测引擎")
    add("├─ webapp/static/        # 前端（index.html + js/ 九模块 + styles/ 四层）")
    add("├─ tests/                # pytest：数据口径 / 更新预检 / 版本号")
    add("├─ tools/                # 开发服务与 UI 自检脚本")
    add("├─ docs/ui-spec.md       # UI 设计规范")
    add("└─ installer.iss         # Inno Setup 安装包脚本")
    add("```")
    add("")

    total_files = 0
    total_lines = 0
    for title, files in SECTIONS:
        add(f"## {title}")
        add("")
        for rel in files:
            path = ROOT / rel
            if not path.exists():
                add(f"### {rel}（文件缺失，跳过）")
                add("")
                continue
            text = path.read_text("utf-8", errors="replace").replace("\r\n", "\n")
            count = text.count("\n") + (0 if text.endswith("\n") else 1)
            total_files += 1
            total_lines += count
            add(f"### `{rel}`　— {count} 行")
            add("")
            add(fence(text) + lang_of(rel))
            add(text)
            add(fence(text))
            add("")
    add("---")
    add("")
    add(f"*共 {total_files} 个文件、{total_lines:,} 行源码。*")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"written: {OUT}")
    print(f"size: {OUT.stat().st_size / 1024:.0f} KB, files={total_files}, lines={total_lines:,}")


if __name__ == "__main__":
    main()
