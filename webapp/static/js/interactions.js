/* ---------- 视图切换：单一入口，与 hash 深链接双向同步 ---------- */
const VIEW_CHROME = {
  overview: ["用量总览", "本机 AI 软件的 Token 消耗与请求统计"],
  models:   ["模型用量", "按模型查看 Token 消耗与参考金额"],
  settings: ["设置", "应用偏好、数据扫描与软件更新"],
};
const SET_TITLE = { general:"通用偏好", data:"扫描与缓存", about:"关于" };
const SET_LEAD = {
  general: "外观、刷新间隔与软件更新",
  data: "重新扫描本机数据源，查看扫描开销与统计口径",
  about: "版本、仓库、隐私与快捷键",
};

function switchView(view, cat){
  const isSet = view === "settings";
  const chrome = VIEW_CHROME[view] || VIEW_CHROME.overview;
  if ($("pageTitle")) $("pageTitle").textContent = chrome[0];
  if ($("pageSubtitle")) $("pageSubtitle").textContent = chrome[1];
  if ($("crumbCurrent")) $("crumbCurrent").textContent = chrome[0];
  if ($("settingsBtn")) $("settingsBtn").classList.toggle("active", isSet);
  document.body.classList.toggle("mode-set", isSet);
  document.body.dataset.mode = isSet ? "settings" : "dashboard";
  document.title = chrome[0] + " · Token Monitor";
  document.querySelectorAll("#nav a").forEach(x=>x.classList.toggle("active", x.dataset.view===view));
  document.querySelectorAll("#tabbar button").forEach(x=>
    x.classList.toggle("active", isSet ? !!x.dataset.settings : x.dataset.view===view));
  const views = { overview: $("view-overview"), models: $("view-models"), settings: $("view-settings") };
  Object.keys(views).forEach(key => { if (views[key]) views[key].hidden = key !== view; });
  /* 从隐藏切回可见时画布尺寸会失效，这里补一次重算 */
  if (window.TMUI && TMUI.resizeChartsIn) requestAnimationFrame(() => TMUI.resizeChartsIn(views[view]));
  try { sessionStorage.setItem("voyra-token-view", view); } catch { /* UI state */ }
  if (isSet) setCat(cat || "general");
  if (window.TMUI) TMUI.syncAria();
}

function setCat(cat){
  document.querySelectorAll("#setNav .set-item").forEach(x=>x.classList.toggle("active", x.dataset.cat===cat));
  document.querySelectorAll(".set-cards[data-cat]").forEach(c=>c.hidden = c.dataset.cat !== cat);
  const t = $("setTitle"); if (t) t.textContent = SET_TITLE[cat] || "设置";
  const lead = $("setLead"); if (lead) lead.textContent = SET_LEAD[cat] || SET_LEAD.general;
  if (window.TMUI) TMUI.syncAria();
}

/* 路由桥：hash 是唯一"地址"，TMUI.route 写 hash，hashchange 触发渲染。
   筛选参数（range/agent/metric/grain/dim/billing）也序列化进 hash，
   刷新、前进后退、分享链接都不会丢过滤视图。 */
const FILTER_KEYS = ["range", "agent", "metric", "grain", "dim", "billing"];
function applyRoute(route, replace){
  /* hash 里带的筛选参数优先级最高（超过 sessionStorage 恢复值） */
  if (route.params && Object.keys(route.params).length){
    const p = route.params;
    if (["today","yesterday","last7","last30","last90","thismonth","lastmonth","all"].includes(p.range)) F.rangeKey = p.range;
    if (typeof p.agent === "string" && p.agent.length < 128) F.agent = p.agent || "all";
    if (["cost","tokens","requests"].includes(p.metric)) F.metric = p.metric;
    if (["day","month"].includes(p.grain)) F.grain = p.grain;
    if (["total","agent","model"].includes(p.dim)) F.dim = p.dim;
    if (["all","metered","plan","unpriced"].includes(p.billing)) F.billing = p.billing;
    if (["entity","composition","cache"].includes(p.lens)) F.lens = p.lens;
    /* 已存在的视图已渲染过旧筛选：让数据按新筛选重算一遍 */
    if (DATA && !DATA.building && DATA.range) renderAll();
  }
  switchView(route.view, route.cat);
  /* 路由切换后把当前筛选补写回 hash：保证 #/overview 始终携带完整过滤视图 */
  if (route.view !== "settings") syncFilterHash();
  if (!replace && route.view !== "settings") window.scrollTo({ top: 0, behavior: "auto" });
}
/* 把当前筛选写回 hash（replaceState：不产生历史垃圾）；settings 无筛选不写 */
function syncFilterHash(){
  const view = (window.TMUI && TMUI.currentView) ? TMUI.currentView() : "overview";
  if (view === "settings") return;
  const params = new URLSearchParams();
  params.set("range", F.rangeKey);
  if (F.agent !== "all") params.set("agent", F.agent);
  params.set("metric", F.metric);
  params.set("grain", F.grain);
  params.set("dim", F.dim);
  if (F.billing !== "all") params.set("billing", F.billing);
  if (F.lens !== "entity") params.set("lens", F.lens);
  const target = "#/" + view + "?" + params.toString();
  if (location.hash !== target){
    try { history.replaceState(null, "", target); } catch { /* 沙箱环境忽略 */ }
  }
}
$("nav").addEventListener("click", e=>{
  const a = e.target.closest("a[data-view]"); if (!a) return;
  e.preventDefault();
  go(a.dataset.view);
});
/* 统一切视图入口：优先走 hash 路由（可分享、可后退），失败则直接切换 */
function go(view, cat){
  try {
    if (window.TMUI && TMUI.route) { TMUI.route(view, cat); return; }
  } catch (err) { /* 路由不可用时退回直接切换 */ }
  switchView(view, cat);
}
/* 数据源筛选：侧栏与窄屏抽屉共用 */
function applyAgentFilter(name){
  F.agent = name === "all" || F.agent === name ? "all" : name;
  renderAll();
}
$("sideAgentBox").addEventListener("click", e => {
  const b = e.target.closest("[data-agent-filter]");
  if (!b) return;
  applyAgentFilter(b.dataset.agentFilter);
});
document.querySelector("aside").addEventListener("click", e => {
  const toggle = e.target.closest("[data-side-toggle]");
  if (toggle){
    const section = toggle.closest(".side-section");
    const collapsed = section.classList.toggle("collapsed");
    toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    return;
  }
  const recent = e.target.closest(".side-recent[data-view]");
  if (recent) go(recent.dataset.view);
});
if ($("sideReload")) $("sideReload").onclick = () => $("reloadTop").click();
/* 窄屏底部标签栏：复用同一套视图切换逻辑；"设置"与 #settingsBtn 共用入口 */
$("tabbar").addEventListener("click", e=>{
  const b = e.target.closest("button"); if (!b) return;
  if (b.dataset.settings){ go("settings", "general"); return; }
  if (b.dataset.view) go(b.dataset.view);
});
$("settingsBtn").onclick = () => go("settings", "general");
$("setNav").addEventListener("click", e=>{
  const a = e.target.closest(".set-item"); if (!a) return;
  e.preventDefault();
  go("settings", a.dataset.cat);
});
$("setBack").onclick = () => go("overview");
bindDropdown("ddRange", "ddRangeMenu", k => { F.rangeKey = k; renderAll(); syncFilterHash(); });
$("segDim").onclick = e => { const b=e.target.closest("button"); if(!b) return;
  F.dim=b.dataset.d;
  document.querySelectorAll("#segDim button").forEach(x=>x.classList.toggle("on",x===b));
  renderMain(); syncFilterHash(); };
$("segMetric").onclick = e => { const b=e.target.closest("button"); if(!b) return;
  F.metric=b.dataset.m;
  document.querySelectorAll("#segMetric button").forEach(x=>x.classList.toggle("on",x===b));
  renderMain(); syncFilterHash(); };
$("segGrain").onclick = e => { const b=e.target.closest("button"); if(!b) return;
  F.grain=b.dataset.g;
  document.querySelectorAll("#segGrain button").forEach(x=>x.classList.toggle("on",x===b));
  renderMain(); syncFilterHash(); };
/* 主图视角：实体堆叠 / 物理构成 / 缓存杠杆（结构视角自动停用指标与维度切换） */
if ($("segLens")) $("segLens").onclick = e => {
  const b = e.target.closest("button[data-lens]"); if (!b) return;
  F.lens = b.dataset.lens;
  document.querySelectorAll("#segLens button").forEach(x=>{
    const on = x === b;
    x.classList.toggle("on", on);
    x.setAttribute("aria-pressed", String(on));
  });
  renderMain();
  syncFilterHash();
};

/* 计费类型筛选：全部 / 按量计费 / 套餐 / 未计价（只影响模型表） */
if ($("segBilling")) $("segBilling").onclick = e => {
  const b = e.target.closest("button[data-b]"); if (!b) return;
  F.billing = b.dataset.b;
  document.querySelectorAll("#segBilling button").forEach(x=>{
    const on = x === b;
    x.classList.toggle("on", on);
    x.setAttribute("aria-pressed", String(on));
  });
  PAGE.index = 0;
  renderModelTable();
  syncFilterHash();
};

/* ---------- 窄屏数据源筛选抽屉 ---------- */
let drawerRelease = null;
function openAgentDrawer(){
  const drawer = $("agentDrawer"), btn = $("filterBtn");
  if (!drawer || drawer.hidden === false) return;
  drawer.hidden = false;
  if (btn) btn.setAttribute("aria-expanded", "true");
  if (window.TMUI){
    drawerRelease = TMUI.trapFocus(drawer.querySelector(".drawer-panel"), { onEscape: closeAgentDrawer });
  }
}
function closeAgentDrawer(){
  const drawer = $("agentDrawer"), btn = $("filterBtn");
  if (!drawer || drawer.hidden) return;
  drawer.hidden = true;
  if (btn){ btn.setAttribute("aria-expanded", "false"); btn.focus(); }
  if (drawerRelease){ drawerRelease(); drawerRelease = null; }
}
if ($("filterBtn")) $("filterBtn").onclick = openAgentDrawer;
if ($("agentDrawer")) $("agentDrawer").addEventListener("click", e => {
  if (e.target.closest("[data-drawer-close]")){ closeAgentDrawer(); return; }
  const b = e.target.closest("[data-agent-filter]");
  if (b){ applyAgentFilter(b.dataset.agentFilter); closeAgentDrawer(); }
});
$("fExport").onclick = function(){
  if (!DATA || DATA.building) {
    collectionFeedback("error","尚不能导出","请等待第一次成功读取统计结果。");
    if (window.TMUI) TMUI.toast("还没有可导出的数据，请等待首次扫描完成", { kind: "warn" });
    return;
  }
  if (this.disabled) return;                 // 防重复提交
  const btn = this;
  const rows = rowsFor(true);
  if (!rows.length){
    if (window.TMUI) TMUI.toast("当前筛选下没有可导出的行", { kind: "info" });
    return;
  }
  const head = "date,agent,model,session,tokens,input,output,cache_read,cache_write,requests,cost_usd,cost_cny";
  const lines = rows.map(r=>[r.date,r.agent,r.model,r.session,r.tokens,r.inp,r.out,r.cr,r.cw,
    r.requests,(r.cost).toFixed(6),(r.cost*DATA.cny_rate).toFixed(4)].join(","));
  const blob = new Blob(["\uFEFF"+head+"\n"+lines.join("\n")], {type:"text/csv;charset=utf-8"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `token-usage-${F.rangeKey}.csv`;
  a.click();
  setTimeout(()=>URL.revokeObjectURL(a.href), 2000);
  btn.classList.add("is-done");
  btn.disabled = true;
  setTimeout(() => { btn.classList.remove("is-done"); btn.disabled = false; }, 900);
  if (window.TMUI) TMUI.toast("已导出 " + fmtInt(rows.length) + " 行 CSV", { kind: "success" });
};
/* 等待后台扫描真正完成：1s 轮询 /api/settings，直到 busy=false 且未排队。
   期间 syncSettings 会同步顶部状态与提示条；超时则交还给 15s 全局轮询。 */
async function waitScanDone(maxMs){
  const deadline = Date.now() + (maxMs || 180000);
  while (Date.now() < deadline){
    await new Promise(r => setTimeout(r, 1000));
    let meta = null;
    try { meta = await (await fetch("/api/settings")).json(); }
    catch { continue; }                        /* 网络抖动：继续等 */
    syncSettings(meta);
    if (meta && !meta.busy && !meta.queued) return meta;
  }
  return null;
}
async function reloadData(btn, idleText, label){
  const target = label || btn;
  const old = target.textContent;
  btn.disabled = true;
  btn.setAttribute("aria-busy", "true");
  /* 按钮上显示真实耗时：扫描通常 20~30s，绝不能假装 1 秒完成 */
  let seconds = 0;
  target.textContent = "扫描中 0s";
  const ticker = setInterval(() => { seconds += 1; target.textContent = "扫描中 " + seconds + "s"; }, 1000);
  setScanControls(true);
  collectionFeedback("loading","正在扫描本机数据","结果会在扫描完成后自动更新，期间可继续查看上次数据。");
  try {
    /* 已有扫描在进行时不再重复排队，直接等它完成（防连点导致重复全量扫描） */
    let meta = null;
    try { meta = await (await fetch("/api/settings")).json(); } catch { /* 服务暂时不可达，走正常请求路径报错 */ }
    if (meta && (meta.busy || meta.queued)){
      if (window.TMUI) TMUI.toast("已有扫描在进行，正在等待其完成", { kind: "info" });
    } else {
      const response = await fetch("/api/reload");
      if (!response.ok) throw new Error("扫描请求失败（HTTP " + response.status + "）");
    }
    const done = await waitScanDone();
    await loadSummary();
    if (done && done.built_at) LAST_BUILT = done.built_at;
    if (window.TMUI){
      TMUI.toast(done ? "数据源扫描完成，统计已更新（用时 " + seconds + "s）"
                      : "扫描仍在后台进行，完成后会自动刷新看板",
                 { kind: done ? "success" : "info" });
    }
  } catch (e) {
    setScanControls(false);
    collectionFeedback("error","扫描请求未完成",String(e.message) + "；请检查本地服务后重试。");
    if (window.TMUI) TMUI.toast("扫描请求失败：" + e.message, { kind: "error" });
  } finally {
    clearInterval(ticker);
    target.textContent = idleText || old;
    btn.removeAttribute("aria-busy");
    btn.disabled = false;
  }
}
$("reload").onclick = function(){ reloadData(this, "重新扫描"); };
if ($("reloadTop")) $("reloadTop").onclick = function(){
  const label = this.querySelector("span");
  reloadData(this, "重新扫描", label);
};

/* 统一点击反馈：鼠标、触控和键盘操作都得到一致的按下效果。 */
document.addEventListener("pointerdown", e => {
  const el = e.target.closest(
    "button,a[data-view],.side-project,.side-recent,.side-section-head,.set-item,.t10-row,.ar-head");
  if (el) el.classList.add("is-pressing");
}, { passive: true });
function clearPressed(e){
  const el = e.target && e.target.closest ? e.target.closest(".is-pressing") : null;
  if (el) el.classList.remove("is-pressing");
}
document.addEventListener("pointerup", clearPressed);
document.addEventListener("pointercancel", clearPressed);
document.addEventListener("pointerleave", clearPressed, true);

/* ---------- 自动刷新：只轮询轻量的 /api/settings，built_at 变了才拉数据 ---------- */
let LAST_BUILT = null, POLL_MS = 15000;
function syncSettings(s){
  if (!s) return;
  const minutes = (s.settings && (s.settings.refresh_minutes ?? 0)) || 0;
  const el = $("autoMin");
  if (el && document.activeElement !== el)
    el.value = String(minutes);
  const chk = $("autoChk");
  if (chk){
    chk.checked = minutes > 0;
    if (el) el.disabled = minutes === 0;
  }
  const ba = $("builtAt");
  if (ba && s.built_at){
    const d = new Date(s.built_at);
    const short = isNaN(d) ? String(s.built_at).slice(11, 16)
      : d.toLocaleString("zh-CN", {month:"2-digit", day:"2-digit",
        hour:"2-digit", minute:"2-digit", hour12:false});
    ba.textContent = short;
    if ($("sideBuiltAt")) $("sideBuiltAt").textContent = short;
  }
  const st = $("scanState");
  if (st) st.textContent = s.busy ? "正在后台扫描…"
    : (s.queued ? "已排队，等待当前扫描完成…" : (s.error ? "上次扫描失败：" + s.error : ""));
  const topState = $("topScanState"), dot = $("syncDot");
  if (topState) topState.textContent = s.busy ? "正在扫描本机数据"
    : (s.queued ? "扫描任务已排队" : (s.error ? "上次扫描失败" : "数据已同步"));
  if (dot){
    dot.classList.toggle("busy", !!(s.busy || s.queued));
    dot.classList.toggle("error", !!s.error);
  }
  updateCollectionFeedback(s);
}
let metaRequest = null;
async function pollMeta(){
  if (metaRequest) return metaRequest;
  metaRequest = (async () => {
  try {
    const response = await fetch("/api/settings");
    if (!response.ok) throw new Error("本地服务返回 HTTP " + response.status);
    const r = await response.json();
    syncSettings(r);
    if (r.built_at && r.built_at !== LAST_BUILT && !r.busy){
      const ok = await loadSummary();
      if (ok) LAST_BUILT = r.built_at;
    }
  } catch(e){
    collectionFeedback("error","暂时无法连接本地服务",DATA ? "上次有效结果已保留。服务恢复后自动重试，也可重新读取。" : "请确认本地服务已启动后重新读取。");
    setScanControls(false);
  }
  })().finally(()=>{metaRequest=null;});
  return metaRequest;
}
setInterval(()=>{if(!document.hidden)void pollMeta();}, POLL_MS);
document.addEventListener("visibilitychange",()=>{if(!document.hidden)void pollMeta();});
$("autoMin").onchange = async function(){
  const m = parseInt(this.value, 10) || 0;
  try {
    await fetch("/api/settings", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_minutes: m }) });
  } catch(e){}
  pollMeta();
};
async function pushSettings(patch){
  try {
    await fetch("/api/settings", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch) });
  } catch(e){}
  pollMeta();
}
$("autoChk").onchange = async function(){
  const el = $("autoMin");
  const on = this.checked;
  if (el){
    if (on && (parseInt(el.value, 10) || 0) === 0) el.value = "30";
    el.disabled = !on;
  }
  const m = on ? (parseInt(el && el.value, 10) || 0) : 0;
  try {
    await fetch("/api/settings", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_minutes: m }) });
    if (window.TMUI) TMUI.toast(on ? "已开启自动刷新" : "已关闭自动刷新", { kind: "success" });
  } catch(e){
    if (window.TMUI) TMUI.toast("设置保存失败，请检查本地服务", { kind: "error" });
  }
  pollMeta();
};

/* ---------- 模型表格：本地搜索 + 分页（大数据量不卡） ---------- */
const debounce = (fn, wait) => { let t = 0; return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), wait); }; };
if ($("modelSearch")) $("modelSearch").oninput = debounce(function(){
  PAGE.query = this.value || "";
  PAGE.index = 0;
  renderModelTable();
}, 180);
if ($("modelPageSize")) $("modelPageSize").onchange = function(){
  PAGE.size = parseInt(this.value, 10) || 0;
  PAGE.index = 0;
  renderModelTable();
};

/* ---------- 页面路由：hash 是唯一地址（可分享、可前进后退） ---------- */
window.TMUI && TMUI.initRouter((route /*, initial */) => applyRoute(route, false));
