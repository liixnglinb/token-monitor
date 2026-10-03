# -*- coding: utf-8 -*-
"""把前端用到的 class / id 全量抽出来，作为重写样式表时的覆盖面清单。

来源：index.html 的静态标记 + js/ 里字符串拼接的 class（render/updater/app/interactions）。
输出：output/class-inventory.md（UTF-8）
用法：python tools/class_inventory.py
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC = ROOT / "webapp" / "static"
OUT = ROOT / "output" / "class-inventory.md"

# index.html 里 class="a b c"
HTML_CLASS_RE = re.compile(r'class="([^"]+)"')
# JS 里 class="..." / className = "..." / classList.add('x')
JS_CLASS_ATTR_RE = re.compile(r'''class(?:Name)?\s*=\s*["'`]([^"'`]+)["'`]''')
JS_CLASS_ADD_RE = re.compile(r'''classList\.(?:add|toggle|remove)\(([^)]*)\)''')
JS_QUOTE_RE = re.compile(r'''["'`]([a-z][a-z0-9-]*(?:\s+[a-z][a-z0-9-]*)*)["'`]''')
# querySelector / closest / getElementById 里出现的类选择器
SEL_RE = re.compile(r'''[.#]([a-zA-Z][\w-]*)''')
ID_RE = re.compile(r'''getElementById\("([^"]+)"\)|\$\("([^"]+)"\)''')


def collect() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    classes: dict[str, set[str]] = {}
    ids: dict[str, set[str]] = {}

    def note(bucket: dict[str, set[str]], name: str, src: str) -> None:
        bucket.setdefault(name, set()).add(src)

    html = (STATIC / "index.html").read_text("utf-8", errors="replace")
    for group in HTML_CLASS_RE.findall(html):
        for cls in group.split():
            note(classes, cls, "index.html")
    for m in ID_RE.finditer(html.replace("$(", "$(")):
        pass
    for m in re.finditer(r'id="([^"]+)"', html):
        note(ids, m.group(1), "index.html")

    for js in sorted((STATIC / "js").glob("*.js")):
        text = js.read_text("utf-8", errors="replace")
        src = f"js/{js.name}"
        for group in JS_CLASS_ATTR_RE.findall(text):
            for cls in group.split():
                if re.fullmatch(r"[a-z][\w-]*", cls):
                    note(classes, cls, src)
        for arg in JS_CLASS_ADD_RE.findall(text):
            for lit in JS_QUOTE_RE.findall(arg):
                for cls in lit.split():
                    note(classes, cls, src)
        for m in SEL_RE.finditer(text):
            token = m.group(1)
            if m.group(0).startswith("#"):
                note(ids, token, src)
        for a, b in ID_RE.findall(text):
            note(ids, a or b, src)
    return classes, ids


def css_selectors() -> set[str]:
    found: set[str] = set()
    for css in sorted((STATIC / "styles").glob("*.css")):
        text = css.read_text("utf-8", errors="replace")
        for m in re.finditer(r"\.([a-zA-Z][\w-]*)", text):
            found.add(m.group(1))
    return found


def main() -> None:
    classes, ids = collect()
    styled = css_selectors()

    lines = ["# 前端 class / id 覆盖清单", "",
             "由 `tools/class_inventory.py` 生成。重写样式表时必须覆盖下面所有 class，",
             "否则动态渲染出来的节点会掉样式。", ""]

    unused = sorted(c for c in styled if c not in classes)
    lines += [f"## 1. 代码里实际用到的 class（{len(classes)} 个）", "",
              "| class | 出现位置 | 现有 CSS 是否覆盖 |", "| --- | --- | --- |"]
    for cls in sorted(classes):
        lines.append(f"| `{cls}` | {', '.join(sorted(classes[cls]))} | {'是' if cls in styled else '**否**'} |")
    lines += ["", f"## 2. CSS 里定义了但代码没用的 class（{len(unused)} 个，可清理）", ""]
    lines.append("、".join(f"`{c}`" for c in unused) if unused else "（无）")
    lines += ["", f"## 3. 代码引用的 id（{len(ids)} 个）", "",
              "| id | 出现位置 |", "| --- | --- |"]
    for key in sorted(ids):
        lines.append(f"| `{key}` | {', '.join(sorted(ids[key]))} |")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"report -> {OUT}")
    print(f"classes={len(classes)} ids={len(ids)} css_only={len(unused)}")
    missing = sorted(c for c in classes if c not in styled)
    print("classes_without_css=" + ",".join(missing[:40]))


if __name__ == "__main__":
    main()
