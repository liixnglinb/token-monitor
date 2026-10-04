# -*- coding: utf-8 -*-
"""下载页 v1.9.15 兜底版本与 alt 文案更新（带命中数断言，铁律 4）。"""
from __future__ import annotations

import pathlib

p = pathlib.Path(r"D:\Voyra 个人网站\public\token-monitor\index.html")
raw = p.read_bytes()
before = raw.count(b"v1.9.12")
assert before == 6, f"预期 6 处 v1.9.12，实际 {before}"
data = raw.replace(b"v1.9.12", b"v1.9.15")
assert data.count(b"v1.9.15") == 6, "替换后应有 6 处 v1.9.15"
assert data.count(b"v1.9.12") == 0, "不应残留 v1.9.12"

PAIRS = [
    ("alt=\"用量总览：金额、请求、Tokens、缓存命中与每日曲线\"",
     "alt=\"用量总览：Token 吞吐全景舱、物理构成条、每日趋势与缓存杠杆视角\""),
    ("alt=\"模型成本：每个模型的 token、请求、金额与均价\"",
     "alt=\"模型用量：模型明细表、计费三态徽标、搜索排序与分页\""),
    ("alt=\"扫描与缓存：命中、重扫、跳过与口径说明\"",
     "alt=\"设置：扫描与缓存、主题切换与软件更新\""),
]
for old, new in PAIRS:
    old_b, new_b = old.encode(), new.encode()
    assert data.count(old_b) == 1, f"alt 定位失败: {old[:30]}"
    data = data.replace(old_b, new_b)

p.write_bytes(data)
print("OK: 6 处版本兜底 + 3 处 alt 更新，断言全过")
