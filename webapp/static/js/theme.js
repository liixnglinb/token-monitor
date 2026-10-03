"use strict";
/* =============================================================================
   theme.js —— 主题控制器（跟随系统 / 浅色 / 深色）
   -----------------------------------------------------------------------------
   规则：
   · 用户没手动选过 → 跟随系统（不给 <html> 写 data-theme，由 tokens.css 的
     prefers-color-scheme 分支决定）；
   · 手动选过 → 写 <html data-theme="light|dark"> 并记到 localStorage("tm-theme")；
   · 系统偏好变化时只对"跟随系统"生效，且不需要刷新页面。
   对外接口：window.TMTheme = { mode, get, set, cycle, apply, options }
   ============================================================================= */
(function () {
  const STORAGE_KEY = "tm-theme";
  const MODES = ["system", "light", "dark"];
  const LABEL = { system: "跟随系统", light: "浅色", dark: "深色" };
  const root = document.documentElement;
  const media = window.matchMedia("(prefers-color-scheme: dark)");

  function read() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      return MODES.includes(saved) ? saved : "system";
    } catch (e) {
      return "system";
    }
  }

  function effective(mode) {
    return mode === "system" ? (media.matches ? "dark" : "light") : mode;
  }

  function apply(mode) {
    if (mode === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", mode);
    root.setAttribute("data-theme-mode", mode);
    // 通知图表等需要按主题取色的模块
    window.dispatchEvent(new CustomEvent("tm:theme", {
      detail: { mode: mode, resolved: effective(mode) }
    }));
    syncControls(mode);
  }

  function set(mode, options) {
    if (!MODES.includes(mode)) mode = "system";
    try { localStorage.setItem(STORAGE_KEY, mode); } catch (e) { /* 隐私模式下忽略 */ }
    apply(mode);
    if (!options || options.announce !== false) {
      const text = "主题已切换为" + LABEL[mode];
      if (window.TMUI && typeof TMUI.toast === "function") TMUI.toast(text, { kind: "info" });
    }
    return mode;
  }

  function cycle() {
    const next = MODES[(MODES.indexOf(read()) + 1) % MODES.length];
    return set(next);
  }

  function syncControls(mode) {
    const seg = document.getElementById("themeSeg");
    if (seg) {
      seg.querySelectorAll("button[data-theme-choice]").forEach(function (button) {
        const on = button.dataset.themeChoice === mode;
        button.classList.toggle("on", on);
        button.setAttribute("aria-pressed", String(on));
      });
    }
    const icon = document.getElementById("themeIcon");
    if (icon) {
      // 12/16 线性图标：跟随系统=显示器、浅色=太阳、深色=月亮
      const paths = {
        system: '<rect x="2.5" y="3.5" width="11" height="7.5" rx="1.4"/><path d="M6 13.5h4M8 11v2.5"/>',
        light: '<circle cx="8" cy="8" r="3"/><path d="M8 1.6v1.8M8 12.6v1.8M1.6 8h1.8M12.6 8h1.8M3.5 3.5l1.3 1.3M11.2 11.2l1.3 1.3M12.5 3.5l-1.3 1.3M4.8 11.2l-1.3 1.3"/>',
        dark: '<path d="M12.8 9.6A5.2 5.2 0 0 1 6.4 3.2a5.2 5.2 0 1 0 6.4 6.4z"/>'
      };
      icon.innerHTML = '<svg viewBox="0 0 16 16" width="15" height="15" fill="none" '
        + 'stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">'
        + (paths[mode] || paths.system) + "</svg>";
    }
    const button = document.getElementById("themeBtn");
    if (button) {
      button.title = "主题：" + LABEL[mode] + "（点击切换）";
      button.setAttribute("aria-label", "切换主题，当前" + LABEL[mode]);
    }
  }

  function initControls() {
    const seg = document.getElementById("themeSeg");
    if (seg) {
      seg.addEventListener("click", function (event) {
        const button = event.target.closest("button[data-theme-choice]");
        if (button) set(button.dataset.themeChoice);
      });
    }
    const top = document.getElementById("themeBtn");
    if (top) top.addEventListener("click", function () { cycle(); });
    syncControls(read());
  }

  // 系统偏好变化：只在"跟随系统"时改变实际外观
  const onSystemChange = function () {
    if (read() === "system") apply("system");
    else syncControls(read());
  };
  if (typeof media.addEventListener === "function") media.addEventListener("change", onSystemChange);
  else if (typeof media.addListener === "function") media.addListener(onSystemChange);

  // 跨标签/跨窗口同步
  window.addEventListener("storage", function (event) {
    if (event.key === STORAGE_KEY) apply(read());
  });

  apply(read());
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initControls);
  else initControls();

  window.TMTheme = {
    modes: MODES,
    label: LABEL,
    get: read,
    resolved: function () { return effective(read()); },
    set: set,
    cycle: cycle,
    apply: apply
  };
})();
