"use strict";
/* =============================================================================
   ui.js —— 交互基建层
   -----------------------------------------------------------------------------
   提供四件事，供各视图复用，避免每个模块各写一套：
   1) 文案与格式：数字/金额/百分比/日期统一口径（Intl，中文区域）
   2) 反馈：toast 轻提示、confirm 危险操作二次确认（带焦点陷阱与键盘）
   3) 路由：hash 深链接（#/overview、#/models、#/settings/data）+ 返回/前进
   4) 无障碍：焦点陷阱、ARIA 同步、骨架屏占位、键盘快捷键

   对外接口统一挂在 window.TMUI。
   ============================================================================= */
(function () {
  const $ = function (id) { return document.getElementById(id); };
  const qsa = function (selector, scope) {
    return Array.prototype.slice.call((scope || document).querySelectorAll(selector));
  };

  /* ── 1. 文案与格式 ───────────────────────────────────────────────────── */
  const nfInt = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 });
  const nf1 = new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const nf2 = new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const nf4 = new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 4 });

  const fmt = {
    int: function (value) { return nfInt.format(Math.round(Number(value) || 0)); },
    tokens: function (value) {
      const n = Number(value) || 0;
      if (n >= 1e9) return nf2.format(n / 1e9) + " B";
      if (n >= 1e6) return nf1.format(n / 1e6) + " M";
      if (n >= 1e3) return nf1.format(n / 1e3) + " k";
      return fmt.int(n);
    },
    cny: function (value, digits) {
      const n = Number(value) || 0;
      const formatter = digits === 4 ? nf4 : nf2;
      return "¥" + formatter.format(n);
    },
    usd: function (value) { return "$" + nf2.format(Number(value) || 0) + " USD"; },
    percent: function (value, digits) {
      const n = Number(value) || 0;
      return (digits === 0 ? nfInt.format(n) : (digits === 1 ? nf1.format(n) : nf2.format(n))) + "%";
    },
    date: function (value, withTime) {
      const date = value instanceof Date ? value : new Date(value);
      if (isNaN(date)) return String(value == null ? "—" : value);
      const options = withTime
        ? { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }
        : { year: "numeric", month: "2-digit", day: "2-digit" };
      return date.toLocaleString("zh-CN", options);
    },
    shortDateTime: function (value) {
      const date = value instanceof Date ? value : new Date(value);
      if (isNaN(date)) return String(value == null ? "—" : value).slice(11, 16);
      return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
    },
    duration: function (ms) {
      const seconds = Math.max(0, Math.round((Number(ms) || 0) / 1000));
      if (seconds < 60) return seconds + " 秒";
      const minutes = Math.floor(seconds / 60);
      if (minutes < 60) return minutes + " 分 " + (seconds % 60) + " 秒";
      return Math.floor(minutes / 60) + " 小时 " + (minutes % 60) + " 分";
    },
    // 大数字紧凑显示；表格里用完整千分位，KPI 用紧凑
    compact: function (value) {
      const n = Math.abs(Number(value) || 0);
      if (n >= 1e8) return nf1.format(n / 1e8) + " 亿";
      if (n >= 1e4) return nf1.format(n / 1e4) + " 万";
      return fmt.int(n);
    }
  };

  /* ── 2. 轻提示（toast） ─────────────────────────────────────────────── */
  const TOAST_ICON = {
    success: "M2.5 8.5 6 12 13.5 4.5",
    error: "M4.5 4.5l7 7M11.5 4.5l-7 7",
    warn: "M8 2.5v7M8 12.5h.01",
    info: "M8 7.2v5M8 4h.01"
  };
  let toastSeq = 0;

  function toast(message, options) {
    const opts = options || {};
    const stack = $("toastStack");
    if (!stack) return null;
    const kind = TOAST_ICON[opts.kind] ? opts.kind : "info";
    const node = document.createElement("div");
    node.className = "toast toast-" + kind;
    node.dataset.toastId = String(++toastSeq);
    node.setAttribute("role", kind === "error" ? "alert" : "status");
    node.innerHTML =
      '<svg class="toast-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" '
      + 'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="'
      + TOAST_ICON[kind] + '"/></svg>'
      + '<span class="toast-text"></span>'
      + (opts.actionLabel ? '<button class="toast-action" type="button"></button>' : "")
      + '<button class="toast-close" type="button" aria-label="关闭提示">'
      + '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.6" '
      + 'stroke-linecap="round" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"/></svg></button>';
    node.querySelector(".toast-text").textContent = String(message == null ? "" : message);
    if (opts.actionLabel) {
      const action = node.querySelector(".toast-action");
      action.textContent = opts.actionLabel;
      action.addEventListener("click", function () {
        if (typeof opts.onAction === "function") opts.onAction();
        dismiss();
      });
    }

    let timer = null;
    function dismiss() {
      if (timer) clearTimeout(timer);
      node.classList.add("toast-out");
      window.setTimeout(function () { node.remove(); }, 220);
    }
    node.querySelector(".toast-close").addEventListener("click", dismiss);
    stack.appendChild(node);
    const ttl = Number.isFinite(opts.duration) ? opts.duration : (kind === "error" ? 8000 : 4000);
    if (ttl > 0) timer = window.setTimeout(dismiss, ttl);
    return { dismiss: dismiss, node: node };
  }

  /* ── 3. 焦点陷阱 + 焦点归还（弹窗通用） ─────────────────────────────── */
  const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

  function trapFocus(container, options) {
    const opts = options || {};
    const previous = document.activeElement;
    function onKeydown(event) {
      if (event.key === "Escape" && opts.onEscape) {
        event.preventDefault();
        opts.onEscape();
        return;
      }
      if (event.key !== "Tab") return;
      const items = qsa(FOCUSABLE, container).filter(function (el) { return el.offsetParent !== null; });
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    container.addEventListener("keydown", onKeydown);
    const firstItem = qsa(FOCUSABLE, container).filter(function (el) { return el.offsetParent !== null; })[0];
    if (firstItem) firstItem.focus();
    return function release() {
      container.removeEventListener("keydown", onKeydown);
      if (previous && typeof previous.focus === "function" && document.contains(previous)) previous.focus();
    };
  }

  /* ── 4. 危险操作二次确认 ───────────────────────────────────────────── */
  let confirmRelease = null;

  function confirmAction(options) {
    const opts = options || {};
    return new Promise(function (resolve) {
      const modal = $("confirmModal");
      if (!modal) { resolve(window.confirm(opts.text || "确认执行该操作？")); return; }
      const title = $("confirmTitle"), text = $("confirmText");
      const ok = $("confirmOk"), cancel = $("confirmCancel"), icon = $("confirmIcon");
      if (title) title.textContent = opts.title || "确认操作";
      if (text) text.textContent = opts.text || "";
      if (ok) ok.textContent = opts.okLabel || "确认";
      if (cancel) cancel.textContent = opts.cancelLabel || "取消";
      if (icon) {
        icon.dataset.kind = opts.danger === false ? "info" : "danger";
        icon.innerHTML = '<svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" '
          + 'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="'
          + (opts.danger === false ? "M10 2.5l7.5 13h-15zM10 7.5v4M10 14h.01" : "M10 3.2l7 12.6H3zM10 8v4.4M10 14.6h.01")
          + '"/></svg>';
      }
      modal.hidden = false;
      confirmRelease = trapFocus(modal, {
        onEscape: function () { close(false); }
      });
      function onOk() { close(true); }
      function onCancel() { close(false); }
      function close(result) {
        modal.hidden = true;
        if (ok) ok.removeEventListener("click", onOk);
        if (cancel) cancel.removeEventListener("click", onCancel);
        modal.removeEventListener("click", onBackdrop);
        if (confirmRelease) { confirmRelease(); confirmRelease = null; }
        resolve(result);
      }
      function onBackdrop(event) { if (event.target === modal) close(false); }
      if (ok) ok.addEventListener("click", onOk);
      if (cancel) cancel.addEventListener("click", onCancel);
      modal.addEventListener("click", onBackdrop);
    });
  }

  /* ── 5. 骨架屏：加载态占位 ─────────────────────────────────────────── */
  function showSkeleton(id, lines) {
    const node = $(id);
    if (!node) return;
    const count = Math.max(1, lines || 1);
    const widths = ["92%", "78%", "86%", "64%", "72%", "58%", "80%", "68%"];
    node.innerHTML = Array.from({ length: count }, function (_, index) {
      return '<div class="skeleton skeleton-line" style="--w:' + widths[index % widths.length] + '"></div>';
    }).join("");
    node.setAttribute("aria-busy", "true");
  }

  function clearSkeleton(id) {
    const node = $(id);
    if (node) node.removeAttribute("aria-busy");
  }

  /* 首屏 Hero 占位：数据到达前显示骨架而不是"—" */
  function skeletonKpis() {
    ["heroValAbbr", "heroReq", "heroAvg", "heroCost", "heroEquiv"].forEach(function (id) {
      const node = $(id);
      if (!node || node.dataset.loaded === "1") return;
      node.classList.add("skeleton");
      node.textContent = "";
    });
  }

  function clearKpiSkeleton() {
    ["heroValAbbr", "heroReq", "heroAvg", "heroCost", "heroEquiv"].forEach(function (id) {
      const node = $(id);
      if (node) node.classList.remove("skeleton");
    });
  }

  /* ── 6. hash 路由：深链接 + 返回/前进 ─────────────────────────────── */
  const ROUTES = {
    "/overview": { view: "overview", cat: "general" },
    "/models": { view: "models", cat: "general" },
    "/settings": { view: "settings", cat: "general" },
    "/settings/general": { view: "settings", cat: "general" },
    "/settings/data": { view: "settings", cat: "data" },
    "/settings/about": { view: "settings", cat: "about" }
  };
  const PATH_OF = {
    overview: "/overview",
    models: "/models",
    settings: "/settings"
  };

  function parseHash(hash) {
    const raw = String(hash || "").replace(/^#/, "");
    if (!raw || raw === "/") return null;
    const qIndex = raw.indexOf("?");
    const path = qIndex === -1 ? raw : raw.slice(0, qIndex);
    const base = ROUTES[path] || null;
    if (!base) return null;
    /* 筛选参数随视图一起走：#/overview?range=last7&agent=codex */
    const params = {};
    if (qIndex !== -1) {
      new URLSearchParams(raw.slice(qIndex + 1)).forEach(function (value, key) {
        if (["range", "agent", "metric", "grain", "dim", "billing", "lens"].includes(key)) params[key] = value;
      });
    }
    return Object.assign({}, base, { params: params });
  }

  function currentView() {
    const route = parseHash(location.hash);
    return route ? route.view : "overview";
  }

  function currentPath() {
    return "#" + (parseHash(location.hash) ? location.hash.replace(/^#/, "") : "/overview");
  }

  function onRoute(handler) {
    window.addEventListener("hashchange", function () {
      const route = parseHash(location.hash);
      if (route) handler(route);
    });
  }

  /* ── 7. ARIA 同步：视图/控件状态变化后补齐语义 ───────────────────── */
  function syncAria() {
    // 主导航与设置分类
    qsa("#nav a[data-view]").forEach(function (item) {
      const on = item.classList.contains("active");
      item.setAttribute("aria-current", on ? "page" : "false");
    });
    qsa("#setNav a[data-cat]").forEach(function (item) {
      const on = item.classList.contains("active");
      item.setAttribute("aria-current", on ? "true" : "false");
    });
    qsa("#tabbar button").forEach(function (item) {
      const on = item.classList.contains("active");
      if (on) item.setAttribute("aria-current", "page");
      else item.removeAttribute("aria-current");
    });
    // 分段控件
    qsa(".seg").forEach(function (group) {
      const multi = group.id === "themeSeg";
      qsa("button", group).forEach(function (button) {
        const on = button.classList.contains("on");
        button.setAttribute("aria-pressed", String(on));
        button.tabIndex = multi ? 0 : (on ? 0 : -1);
      });
    });
    // 下拉菜单
    qsa(".dd").forEach(function (group) {
      const button = group.querySelector(".dd-btn");
      const menu = group.querySelector(".dd-menu");
      if (!button || !menu) return;
      const open = !menu.hidden;
      button.setAttribute("aria-expanded", String(open));
      if (!menu.id) menu.id = group.id + "Menu";
      button.setAttribute("aria-controls", menu.id);
      button.setAttribute("aria-haspopup", "menu");
      menu.setAttribute("role", "menu");
      qsa("button", menu).forEach(function (option) {
        option.setAttribute("role", "menuitemradio");
        option.setAttribute("aria-checked", String(option.classList.contains("on")));
        option.tabIndex = -1;
      });
    });
    // 折叠行
    qsa(".ar-head").forEach(function (head) {
      const open = head.parentElement && head.parentElement.classList.contains("open");
      head.setAttribute("aria-expanded", String(!!open));
    });
    // 图表：给读屏一个可理解的替代描述
    qsa("canvas[role=img]").forEach(function (canvas) {
      const section = canvas.closest(".card,.agent-panel,.agent-entry");
      const heading = section && section.querySelector("h3,h4");
      const label = (heading && heading.textContent.trim()) || "统计图";
      canvas.setAttribute("aria-label", label + "。精确数值见同一区域的文字与明细表。");
    });
  }

  /* ── 8. 键盘：分段控件方向键 + 全局快捷键 ──────────────────────────── */
  function initKeyboard() {
    // 分段控件：左右键在组内移动
    document.addEventListener("keydown", function (event) {
      const insideField = /^(INPUT|SELECT|TEXTAREA)$/.test(event.target.tagName) || event.target.isContentEditable;
      const seg = event.target.closest && event.target.closest(".seg");
      if (seg && ["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
        const items = qsa("button:not([disabled])", seg);
        const index = items.indexOf(document.activeElement);
        if (index === -1) return;
        event.preventDefault();
        const next = event.key === "Home" ? 0
          : event.key === "End" ? items.length - 1
            : event.key === "ArrowRight" ? (index + 1) % items.length
              : (index - 1 + items.length) % items.length;
        items[next].focus();
        // 分段控件是"选择即生效"，方向键直接切换更符合桌面端习惯
        items[next].click();
        return;
      }
      if (insideField) return;
      if (event.ctrlKey || event.metaKey || event.altKey) return;

      const key = event.key.toLowerCase();
      if (key === "1" || key === "2" || key === "g" || key === "/" || key === "r") {
        if (event.key === "/" || key === "/") {
          const search = $("modelSearch");
          if (search && $("view-models") && !$("view-models").hidden) {
            event.preventDefault();
            search.focus();
            search.select();
            return;
          }
        }
        if (key === "1") { event.preventDefault(); window.TMUI.route("overview"); return; }
        if (key === "2") { event.preventDefault(); window.TMUI.route("models"); return; }
        if (key === "g") { event.preventDefault(); window.TMUI.route("settings", "general"); return; }
        if (key === "r") {
          const button = $("reload");
          if (button && !button.disabled) { event.preventDefault(); button.click(); }
          return;
        }
      }
      if (event.key === "Escape") {
        const modal = $("updModal");
        if (modal && !modal.hidden) return;   // 更新弹窗自己处理
        qsa(".dd.open").forEach(function (group) { group.classList.remove("open"); });
        qsa(".dd-menu").forEach(function (menu) { menu.hidden = true; });
      }
    });
  }

  /* ── 9. 滚动进入视图时才渲染的懒加载（性能） ─────────────────────── */
  function lazyOnVisible(node, callback, options) {
    if (!node) return;
    if (!("IntersectionObserver" in window)) { callback(); return; }
    const observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          observer.disconnect();
          callback();
        }
      });
    }, Object.assign({ rootMargin: "200px 0px" }, options || {}));
    observer.observe(node);
  }

  /* 视图从隐藏切回可见时，画布需要重新量尺寸（Chart.js 在 display:none 下算不出尺寸） */
  function resizeChartsIn(root) {
    if (!window.Chart) return;
    const scope = root || document;
    scope.querySelectorAll("canvas").forEach(function (canvas) {
      const chart = Chart.getChart(canvas);
      if (chart) chart.resize();
    });
  }

  /* ── 10. 对外接口 ─────────────────────────────────────────────────── */
  let routeHandler = null;

  function route(view, cat) {
    const path = view === "settings"
      ? "/settings/" + (cat || "general")
      : (PATH_OF[view] || "/overview");
    if (location.hash === "#" + path) {
      if (routeHandler) routeHandler({ view: view, cat: cat || "general" }, true);
      return;
    }
    location.hash = path;
  }

  function initRouter(handler) {
    routeHandler = handler;
    const initial = parseHash(location.hash);
    handler(initial || { view: "overview", cat: "general" }, true);
    onRoute(function (target) { handler(target, false); });
  }

  function init() {
    skeletonKpis();
    syncAria();
    initKeyboard();
    let frame = 0;
    const observer = new MutationObserver(function () {
      if (frame) return;
      frame = requestAnimationFrame(function () { frame = 0; syncAria(); });
    });
    const main = document.querySelector("main");
    if (main) observer.observe(main, { attributes: true, attributeFilter: ["class", "hidden"], childList: true, subtree: true });
    window.addEventListener("tm:render", syncAria);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();

  window.TMUI = {
    fmt: fmt,
    toast: toast,
    confirm: confirmAction,
    trapFocus: trapFocus,
    showSkeleton: showSkeleton,
    clearSkeleton: clearSkeleton,
    skeletonKpis: skeletonKpis,
    clearKpiSkeleton: clearKpiSkeleton,
    syncAria: syncAria,
    route: route,
    initRouter: initRouter,
    currentView: currentView,
    lazyOnVisible: lazyOnVisible,
    resizeChartsIn: resizeChartsIn,
    $: $,
    qsa: qsa
  };
})();
