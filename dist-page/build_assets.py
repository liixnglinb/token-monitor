# -*- coding: utf-8 -*-
"""下载页静态资产：把软件里那套真实品牌图/截图处理成站点用的尺寸，并同步到两处站点目录。

来源（改图标只需改这里 + 软件内的同一份文件，保证"网站图标 = 软件图标"）：
  - 品牌图：webapp/static/logos/*  （与 App 内 AGENT_LOGOS 同一批文件）
  - 截图：  dist-page/_shots/*.png （由 capture_shots.mjs 起真实服务后抓取）
输出：
  - site/agent-icons/*.png、site/shots/*.webp
  - D:/Voyra 个人网站/public/token-monitor/agent-icons/*、.../shots/*
用法：python token-monitor/dist-page/build_assets.py
"""
import io
import os
import shutil
import sys

from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(BASE)
LOGOS = os.path.join(APP, "webapp", "static", "logos")
SHOTS_IN = os.path.join(BASE, "_shots")
SITE = os.path.join(APP, "site")
VOYRA = r"D:\Voyra 个人网站\public\token-monitor"

# 页面 12 个数据源 → 软件同一套映射（AGENT_LOGOS；无品牌图的走字母徽标，见 build.py）
# 2026-10-05：codex 不再借用 openai.svg —— Codex 有自己的官方标志（见软件 core.js 同一条目）
ICONS = {
    "codex": "codex.png", "claude-code": "claude.svg", "opencode": "opencode.svg",
    "cline": "cline.svg", "zcode": "zcode.png", "hermes": "hermes.png",
    "workbuddy-ai": "workbuddy.png", "dsh": "dsh.png",
    # 2026-10-07：Qoder CN 第一次有真实用量，页面排行会露出它 → 与 App 同一张官方标
    "qoder": "qoder.png",
}
ICON_SIZE = 64          # 排行行内显示 18px，64 足够 2x/3x 屏
SHOT_W = 1320           # 导览图统一宽度，高度按裁切结果

# 截图裁切：源图是 1440x950 视口实拍（页面区，无窗口边框），按内容留白裁掉空区
SHOTS = {
    "overview": dict(src="overview.png", box=(0, 0, 1440, 880)),   # KPI + 每日 Token 折线 + 明细
    "models":   dict(src="models.png",   box=(0, 0, 1440, 880)),   # 成本明细表
    "scan":     dict(src="settings.png", box=(0, 0, 1440, 440)),   # 扫描与缓存 + 口径三行
}


def ensure(d):
    if not os.path.isdir(d):
        os.makedirs(d)


def out_dirs(sub):
    return [os.path.join(SITE, sub), os.path.join(VOYRA, sub)]


def build_icons():
    made = []
    for sid, fname in ICONS.items():
        src = os.path.join(LOGOS, fname)
        if not os.path.isfile(src):
            print("!! 缺品牌图:", src)
            sys.exit(1)
        ext = os.path.splitext(fname)[1].lower()
        for d in out_dirs("agent-icons"):
            ensure(d)
            dst = os.path.join(d, sid + ext)
            if ext == ".svg":
                shutil.copyfile(src, dst)       # 矢量直接搬，页面按 18px 显示，任意 DPI 都锐
            else:
                im = Image.open(src).convert("RGBA")
                if im.width != ICON_SIZE or im.height != ICON_SIZE:
                    im = im.resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
                im.save(dst, "PNG", optimize=True)
        made.append(sid + ext)
    print("品牌图 %d 个 → agent-icons/  %s" % (len(made), " ".join(made)))
    return made


def build_shots():
    n = 0
    for name, cfg in SHOTS.items():
        src = os.path.join(SHOTS_IN, cfg["src"])
        if not os.path.isfile(src):
            print("!! 缺截图:", src)
            sys.exit(1)
        im = Image.open(src).convert("RGB")
        if cfg["box"]:
            im = im.crop(cfg["box"])
        if im.width > SHOT_W:
            im = im.resize((SHOT_W, round(im.height * SHOT_W / im.width)), Image.LANCZOS)
        for d in out_dirs("shots"):
            ensure(d)
            im.save(os.path.join(d, name + ".webp"), "WEBP", quality=86, method=6)
        n += 1
    print("界面截图 %d 张 → shots/ (宽 %dpx, webp)" % (n, SHOT_W))
    return n


if __name__ == "__main__":
    build_icons()
    build_shots()
    for d in out_dirs("agent-icons"):
        print("  ->", d, "%d 个文件" % len(os.listdir(d)))
    for d in out_dirs("shots"):
        print("  ->", d, "%d 个文件" % len(os.listdir(d)))
