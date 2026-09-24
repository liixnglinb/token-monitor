/* ---------- 事件 ---------- */
function switchView(view){
  const isSet = view === "settings";
  const chrome = {
    overview:["用量总览","本机 AI 编程工具 Token 与成本"],
    models:["模型成本","按模型查看用量与估算金额"],
    settings:["设置","应用偏好、扫描与更新状态"],
  }[view] || ["用量总览","本机 AI 编程工具 Token 与成本"];
  if ($("pageTitle")) $("pageTitle").textContent = chrome[0];
  if ($("pageSubtitle")) $("pageSubtitle").textContent = chrome[1];
  if ($("settingsBtn")) $("settingsBtn").classList.toggle("active", isSet);
  document.body.classList.toggle("mode-set", isSet);
  document.querySelectorAll("#nav a").forEach(x=>x.classList.toggle("active", x.dataset.view===view));
  document.querySelectorAll("#tabbar button").forEach(x=>
    x.classList.toggle("active", isSet ? !!x.dataset.settings : x.dataset.view===view));
  $("view-overview").hidden = view !== "overview";
  $("view-models").hidden   = view !== "models";
  $("view-settings").hidden = !isSet;
  if (isSet){
    const cur = document.querySelector("#setNav .set-item.active");
    setCat((cur && cur.dataset.cat) || "general");
  }
}
function setCat(cat){
  document.querySelectorAll("#setNav .set-item").forEach(x=>x.classList.toggle("active", x.dataset.cat===cat));
  document.querySelectorAll(".set-cards[data-cat]").forEach(c=>c.hidden = c.dataset.cat !== cat);
  const titles = { general:"通用偏好", data:"扫描与缓存", about:"关于" };
  const t = $("setTitle"); if (t) t.textContent = titles[cat] || "设置";
}
$("nav").addEventListener("click", e=>{
  const a = e.target.closest("a[data-view]"); if (!a) return;
  switchView(a.dataset.view);
});
$("sideAgentBox").addEventListener("click", e => {
  const b = e.target.closest("[data-agent-filter]");
  if (!b) return;
  const name = b.dataset.agentFilter;
  F.agent = name === "all" || F.agent === name ? "all" : name;
  renderAll();
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
  if (recent) switchView(recent.dataset.view);
});
if ($("sideReload")) $("sideReload").onclick = () => $("reloadTop").click();
/* 窄屏底部标签栏：复用同一套视图切换逻辑；"设置"与 #settingsBtn 共用入口 */
$("tabbar").addEventListener("click", e=>{
  const b = e.target.closest("button"); if (!b) return;
  if (b.dataset.settings){ switchView("settings"); return; }
  if (b.dataset.view) switchView(b.dataset.view);
});
$("settingsBtn").onclick = () => switchView("settings");
$("setNav").addEventListener("click", e=>{
  const a = e.target.closest(".set-item"); if (!a) return;
  setCat(a.dataset.cat);
});
$("setBack").onclick = () => switchView("overview");
bindDropdown("ddRange", "ddRangeMenu", k => { F.rangeKey = k; renderAll(); });
$("segDim").onclick = e => { const b=e.target.closest("button"); if(!b) return;
  F.dim=b.dataset.d;
  document.querySelectorAll("#segDim button").forEach(x=>x.classList.toggle("on",x===b));
  renderMain(); };
$("segMetric").onclick = e => { const b=e.target.closest("button"); if(!b) return;
  F.metric=b.dataset.m;
  document.querySelectorAll("#segMetric button").forEach(x=>x.classList.toggle("on",x===b));
  renderMain(); };
$("segGrain").onclick = e => { const b=e.target.closest("button"); if(!b) return;
  F.grain=b.dataset.g;
  document.querySelectorAll("#segGrain button").forEach(x=>x.classList.toggle("on",x===b));
  renderMain(); };
$("fExport").onclick = function(){
  const btn = this;
  const rows = rowsFor(true);
  const head = "date,agent,model,session,tokens,input,output,cache_read,cache_write,requests,cost_usd,cost_cny";
  const lines = rows.map(r=>[r.date,r.agent,r.model,r.session,r.tokens,r.inp,r.out,r.cr,r.cw,
    r.requests,(r.cost).toFixed(6),(r.cost*DATA.cny_rate).toFixed(4)].join(","));
  const blob = new Blob(["\uFEFF"+head+"\n"+lines.join("\n")], {type:"text/csv;charset=utf-8"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `token-usage-${F.rangeKey}.csv`;
  a.click(); URL.revokeObjectURL(a.href);
  btn.classList.add("is-done");
  setTimeout(() => btn.classList.remove("is-done"), 900);
};
async function reloadData(btn, idleText, label){
  const target = label || btn;
  const old = target.textContent;
  btn.disabled = true; target.textContent = "扫描中…";
  try { await fetch("/api/reload"); } finally {
    setTimeout(() => { btn.disabled = false; target.textContent = idleText || old; }, 1200);
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
}
async function pollMeta(){
  try {
    const r = await (await fetch("/api/settings")).json();
    syncSettings(r);
    if (r.built_at && r.built_at !== LAST_BUILT){
      LAST_BUILT = r.built_at;
      DATA = await (await fetch("/api/summary")).json();
      renderAll();
      const b = $("reload");
      if (b){ b.disabled = false; b.textContent = "重新扫描数据源"; }
    }
  } catch(e){ /* 后端重启中，下一轮再试 */ }
}
setInterval(pollMeta, POLL_MS);
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
  } catch(e){}
  pollMeta();
};
