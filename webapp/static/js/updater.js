/* ---------- 更新状态机：左上角小按钮 + tooltip ---------- */
const UPD = window.__UPD_STATE = {
  state: "idle",
  latest: null,
  ver: null,
  body: "",
  date: "",
  percent: 0,
  progressState: "idle",
  source: null,
  message: "",
};
let tipPinned = false, tipHovered = false;
let progressTimer = null, progressInFlight = false;

/* 把 /api/version 的结果回写进状态机。
   此前 checkUpdate 只刷新设置页按钮、从不回写 UPD —— 悬停提示与
   红点指示整条链路处于死状态（v1.2.x 改版时断线），这里补上 */
function syncUpd(v){
  UPD.ver = v.version || null;
  UPD.latest = v.latest || null;
  UPD.body = v.body || "";
  UPD.date = v.date || "";
  if (v.has_update && v.latest){
    UPD.state = "update";
  } else if (UPD.state !== "dl" && UPD.state !== "done"){
    UPD.state = v.checking ? "checking" : "idle";
  }
  setUpdUI();
}

/* release notes 轻量排版：**小节** → 彩色标题、- 列表 → 圆点、行内 **加粗** 与 `代码`。
   先整体 HTML 转义再套结构，防注入（对齐 ZCode 更新浮层的阅读体验） */
function fmtReleaseBody(t){
  const inline = s => esc(s)
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
  let html = "";
  for (const raw of String(t).split(/\r?\n/)){
    const line = raw.trim();
    if (!line) continue;
    const sec = line.match(/^\*\*(.+?)\*\*:?$/);
    if (sec){ html += '<div class="sec">' + inline(sec[1]) + "</div>"; continue; }
    const li = line.match(/^[-*•]\s+(.*)$/);
    if (li){ html += '<div class="li">' + inline(li[1]) + "</div>"; continue; }
    html += '<div class="p">' + inline(line) + "</div>";
  }
  return html;
}

function setUpdUI(){
  const dot = $("updBadge"), mini = $("updMini"), pctEl = $("updPct");
  const st = UPD.state;
  const pctNow = Math.max(0, Math.min(100, Math.round(UPD.percent || 0)));
  if (dot){
    dot.hidden = !(st === "update" || st === "ready" || st === "done");
    dot.className = "dot " + (st === "update" ? "update" : st === "ready" ? "ready" : "done");
  }
  /* 下载中：小框本身是进度环 + 百分比数字（无箭头）；就绪：绿点亮起 */
  if (mini){
    mini.classList.toggle("is-dl", st === "dl");
    mini.style.setProperty("--p", String(pctNow));
    mini.title = st === "update" ? "发现新版本 v" + (UPD.latest || "") + "，悬停查看更新内容"
      : st === "dl" ? ((UPD.source ? "正在从 " + UPD.source + " 下载 " : "正在测速并选择最快下载源 ") + pctNow + "%")
      : st === "ready" ? "v" + (UPD.latest || "") + " 已下载完成，点击安装"
      : st === "done" ? "更新完成，正在重启" : "检查更新";
  }
  if (pctEl){
    pctEl.hidden = st !== "dl";
    if (st === "dl") pctEl.textContent = String(pctNow);
  }

  const pct = pctNow;
  /* 设置页「软件更新」卡片里的下载进度行 */
  const row = $("updProgressRow"), bar = $("updProgressBar"), txt = $("updProgressText");
  if (row) row.hidden = st !== "dl";
  if (bar) bar.style.width = pct + "%";
  if (txt) txt.textContent = (UPD.source ? "正在从 " + UPD.source + " 下载 " : "正在测速并选择最快下载源 ")
    + pct + "%";
  /* 有新版本时把更新日志内联展示在卡片里（原侧栏悬停浮层的替代） */
  const notes = $("updNotes");
  if (notes){
    if (st === "update" && UPD.latest){
      notes.hidden = false;
      notes.innerHTML = '<div class="un-t">v' + esc(UPD.latest) + ' 更新日志</div>'
        + (UPD.date ? '<div class="un-date">' + esc(UPD.date) + '</div>' : "")
        + (UPD.body ? '<div class="un-body">' + fmtReleaseBody(UPD.body) + '</div>' : "");
    } else {
      notes.hidden = true;
      notes.innerHTML = "";
    }
  }

  const btn = $("updBtn");
  if (btn){
    /* 状态化按钮：类名驱动样式（无箭头，下载时按钮本身就是进度条） */
    btn.classList.toggle("is-update", st === "update");
    btn.classList.toggle("is-ready", st === "ready");
    btn.classList.toggle("is-downloading", st === "dl");
    btn.classList.toggle("is-done", st === "done" || st === "applying");
    btn.classList.toggle("is-error", st === "error");
    if (st === "dl"){
      btn.style.setProperty("--p", pct + "%");
      btn.textContent = "下载中 " + pct + "%";
    } else if (st === "ready" && !btn.dataset.confirming){
      btn.textContent = "更新已就绪 · 点击安装";
    }
  }
}

window.startUpdate = function(){
  const btn = $("updBtn");
  if (btn && btn.dataset.pending === "1") btn.click();
};

async function pollUpdateProgress(){
  if (progressInFlight || UPD.state !== "dl") return;
  progressInFlight = true;
  try {
    const r = await fetch("/api/update/progress", { cache: "no-store" });
    const p = await r.json();
    UPD.percent = Number(p.percent || 0);
    UPD.progressState = p.state || "downloading";
    UPD.source = p.source || null;
    UPD.message = p.message || "";
    if (p.version) UPD.latest = p.version;
    setUpdUI();
  } catch (_) {
    /* The process may exit during the final replacement. */
  } finally {
    progressInFlight = false;
    if (UPD.state === "dl") {
      progressTimer = window.setTimeout(pollUpdateProgress, 250);
    }
  }
}

function startProgressPolling(){
  window.clearTimeout(progressTimer);
  pollUpdateProgress();
}

function stopProgressPolling(){
  window.clearTimeout(progressTimer);
  progressTimer = null;
}

/* ---------- 自动更新（两段式：下载 → 确认 → 安装重启） ---------- */
async function checkUpdate(silent){
  const btn = $("updBtn");
  if (!silent){
    btn.disabled = true;
    btn.className = "btn is-checking";
    btn.textContent = "检查中";
  }
  try {
    const v = await (await fetch("/api/version")).json();
    syncUpd(v);
    $("verLine").textContent = "版本 " + (v.version ? "v" + v.version : "dev") +
      (v.has_update && v.latest ? " · 可更新 v" + v.latest : "");
    if (v.has_update){
      btn.disabled = false;
      btn.className = "btn is-update";
      btn.textContent = "更新到 v" + v.latest;
      btn.dataset.pending = "1";
    } else {
      btn.disabled = false;
      btn.className = "btn";
      btn.textContent = v.latest ? "已是最新" : (v.version ? "已是最新" : "开发模式");
      btn.dataset.pending = "";
    }
  } catch(e){
    btn.disabled = false;
    btn.className = "btn";
    btn.textContent = "检查更新";
    btn.dataset.pending = "";
  }
}

/* 第一段：下载到暂存（不替换、不重启），完成即进入「就绪」态 */
async function downloadUpdate(){
  const btn = $("updBtn");
  btn.disabled = true;
  btn.className = "btn is-downloading";
  btn.style.setProperty("--p", "0%");
  btn.textContent = "下载中 0%";
  UPD.state = "dl";
  UPD.percent = 0;
  UPD.source = null;
  UPD.message = "正在测速并选择最快下载源";
  setUpdUI();
  startProgressPolling();
  try {
    const r = await (await fetch("/api/update", { method: "POST" })).json();
    if (!r.ok) throw new Error(r.error || "下载失败");
    stopProgressPolling();
    UPD.percent = 100;
    UPD.state = "ready";
    if (r.latest) UPD.latest = r.latest;
    btn.disabled = false;
    btn.className = "btn is-ready";
    btn.textContent = "更新已就绪 · 点击安装";
    setUpdUI();
  } catch(e){
    stopProgressPolling();
    btn.disabled = false;
    UPD.state = "error";
    UPD.source = null;
    UPD.message = String(e && e.message ? e.message : e);
    btn.className = "btn is-error";
    btn.textContent = "下载失败 · 重试";
  }
}

/* 确认弹窗：点更新按钮/小框就直接问「是否现在更新并重启」。
   确认后走 runUpdate：需要时先下载（有进度），下载成功即自动替换重启。 */
function confirmInstall(){
  const m = $("updModal"); if (!m) return;
  const txt = $("updModalText");
  if (txt){
    txt.textContent = UPD.state === "ready"
      ? "v" + (UPD.latest || "") + " 已下载完成，是否现在更新并重启？"
      : "v" + (UPD.latest || "") + " 将自动下载并安装，随后重启软件。是否现在更新并重启？";
  }
  m.hidden = false;
}
window.confirmInstall = confirmInstall;

/* 确认后：下载（带进度）→ 成功后自动安装并重启（无需再点第二次） */
async function runUpdate(){
  const m = $("updModal"); if (m) m.hidden = true;
  if (UPD.state === "ready"){ await applyUpdate(); return; }   // 已下载过 → 直接安装
  await downloadUpdate();
  if (UPD.state === "ready") await applyUpdate();
}
window.runUpdate = runUpdate;

/* 第二段：确认后替换 exe 并重启 */
async function applyUpdate(){
  const m = $("updModal"); if (m) m.hidden = true;
  const btn = $("updBtn");
  UPD.state = "applying";
  if (btn){
    btn.disabled = true;
    btn.className = "btn is-done";
    btn.textContent = "正在更新并重启…";
  }
  setUpdUI();
  try {
    const r = await (await fetch("/api/update/apply", { method: "POST" })).json();
    if (!r.ok) throw new Error(r.error || "安装失败");
    /* 当前进程约 1 秒后退出、新进程接管：轮询版本，新版本回来自动刷新 */
    let tries = 0;
    const t = setInterval(async () => {
      tries++;
      try {
        const v = await (await fetch("/api/version")).json();
        clearInterval(t);
        $("verLine").textContent = "版本 v" + v.version;
        UPD.state = "idle";
        if (btn){ btn.disabled = false; btn.className = "btn"; btn.textContent = "已是最新"; btn.dataset.pending = ""; }
        location.reload();
      } catch(_){ /* 新进程未就绪，继续等 */ }
      if (tries > 45){ clearInterval(t); if (btn) btn.textContent = "更新超时，请重启应用"; }
    }, 2000);
  } catch(e){
    UPD.state = "error";
    UPD.message = String(e && e.message ? e.message : e);
    if (btn){ btn.disabled = false; btn.className = "btn is-error"; btn.textContent = "安装失败 · 重试"; }
  }
}

$("updBtn").onclick = function(){
  /* 有更新（或已下载待安装）→ 直接弹「是否现在更新并重启」；确认后才下载/安装 */
  if (UPD.state === "ready" || this.dataset.pending === "1"){ confirmInstall(); return; }
  if (UPD.state === "error"){ UPD.state = "idle"; checkUpdate(false); return; }
  checkUpdate(false);
};

/* 确认弹窗按钮 */
(function(){
  const m = $("updModal"); if (!m) return;
  const later = $("updLater"), go = $("updConfirm");
  if (later) later.onclick = () => { m.hidden = true; };
  if (go) go.onclick = runUpdate;                              // 确认 → 下载/安装/重启一条龙
  m.addEventListener("click", e => { if (e.target === m) m.hidden = true; });
  document.addEventListener("keyup", e => { if (e.key === "Escape") m.hidden = true; });
})();

/* 页面刷新后若服务端仍有「已下载待安装」，恢复就绪态（别让用户白等一次下载） */
(async function(){
  try {
    const p = await (await fetch("/api/update/progress", { cache: "no-store" })).json();
    if (p && p.state === "ready"){
      UPD.state = "ready";
      UPD.percent = 100;
      if (p.version) UPD.latest = p.version;
      const btn = $("updBtn");
      if (btn){
        btn.disabled = false;
        btn.className = "btn is-ready";
        btn.textContent = "更新已就绪 · 点击安装";
        btn.dataset.pending = "";
      }
      setUpdUI();
      if (UPD.latest) $("verLine").textContent = "版本 " + (UPD.ver ? "v" + UPD.ver : "dev") + " · 已下载 v" + UPD.latest;
    }
  } catch(_){}
})();
