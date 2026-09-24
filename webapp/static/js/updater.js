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
  const dot = $("updBadge"), spin = $("updSpin"), mini = $("updMini");
  const st = UPD.state;
  if (dot){
    dot.hidden = !(st === "update" || st === "done");
    dot.className = "dot " + (st === "update" ? "update" : st === "done" ? "done" : "");
  }
  if (spin) spin.hidden = st !== "dl";
  if (mini){
    mini.title = st === "update" ? "发现新版本 v" + (UPD.latest || "") + "，点击查看"
      : st === "dl" ? (UPD.source ? "正在从 " + UPD.source + " 下载更新…" : "正在测速并选择最快下载源…")
      : st === "done" ? "更新完成，正在重启" : "检查更新";
  }

  const pct = Math.max(0, Math.min(100, Math.round(UPD.percent || 0)));
  const progress = $("updateProgress");
  if (progress){
    progress.hidden = st !== "dl";
    progress.textContent = pct + "%";
    progress.title = (UPD.source ? "正在从 " + UPD.source + " 下载 " : "正在选择最快下载源 ")
      + pct + "%";
  }

  const btn = $("updBtn");
  if (btn){
    btn.classList.toggle("is-downloading", st === "dl");
    btn.classList.toggle("is-done", st === "done");
    if (st === "dl") btn.textContent = pct + "%";
  }
}

function renderUpdTip(confirmed){
  const tip = $("updTip"); if (!tip) return;
  let html;
  if (UPD.state === "dl"){
    const pct = Math.max(0, Math.min(100, Math.round(UPD.percent || 0)));
    const source = UPD.source
      ? '<div class="dl-source">下载源：' + esc(UPD.source) + '</div>'
      : '<div class="dl-source">正在测速并选择最快下载源…</div>';
    html = '<div class="t1">正在下载新版本 ' + pct + '%</div>'
      + '<div class="dl-progress"><i style="width:' + pct + '%"></i></div>'
      + source
      + '<div class="dl-row">下载完成后会提示你确认安装，期间可正常使用。</div>';
  } else if (UPD.state === "update" && UPD.latest){
    /* 悬停即展示完整更新日志（对齐 ZCode）；点击图标才钉住并出现确认按钮 */
    html = '<div class="t1">v' + esc(UPD.latest) + ' 更新日志</div>'
      + (UPD.date ? '<div class="date">' + esc(UPD.date) + '</div>' : "")
      + (UPD.body ? '<div class="body">' + fmtReleaseBody(UPD.body) + '</div>' : "")
      + (confirmed
          ? '<button class="go" onclick="startUpdate()">立即更新</button>'
            + '<button class="later" onclick="hideUpdTip()">稍后</button>'
          : '<div class="hint">点击图标确认更新</div>');
  } else {
    html = '<div class="t1">' + (UPD.ver ? "当前 v" + esc(UPD.ver) : "Token Monitor") + '</div>'
      + '<div style="color:#8A8A90;margin-top:3px">'
      + (UPD.state === "checking" ? "正在检查更新…" : "已是最新版本") + '</div>';
  }
  tip.innerHTML = html;
  tip.hidden = false;
  const r = $("updMini").getBoundingClientRect();
  tip.style.left = Math.max(8, Math.min(r.left, window.innerWidth - 350)) + "px";
  tip.style.top = (r.bottom + 8) + "px";
}
function hideUpdTip(){ const t = $("updTip"); if (t) t.hidden = true; }
window.hideUpdTip = hideUpdTip;

window.startUpdate = function(){
  hideUpdTip();
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

/* 左上角小按钮：悬停简提示 / 点击展开确认 */
const miniEl = $("updMini");
if (miniEl){
  miniEl.addEventListener("mouseenter", () => {
    if (UPD.state === "update" && !tipPinned) renderUpdTip(false);
    else if (UPD.state === "dl") renderUpdTip(false);
  });
  miniEl.addEventListener("mouseleave", () => {
    setTimeout(() => { if (!tipPinned && !tipHovered) hideUpdTip(); }, 150);
  });
  miniEl.addEventListener("click", () => {
    if (UPD.state === "update"){ tipPinned = !tipPinned; renderUpdTip(true); }
    else if (UPD.state === "dl"){ tipPinned = !tipPinned; renderUpdTip(false); }
    else { checkUpdate(false); }
  });
  document.addEventListener("click", e => {
    if (!e.target.closest(".upd-tip") && !e.target.closest("#updMini")){
      tipPinned = false; hideUpdTip();
    }
  });
  document.addEventListener("keyup", e => { if (e.key === "Escape") hideUpdTip(); });
}

/* ---------- 自动更新 ---------- */
async function checkUpdate(silent){
  const btn = $("updBtn");
  if (!silent){ btn.disabled = true; btn.textContent = "检查中…"; }
  try {
    const v = await (await fetch("/api/version")).json();
    syncUpd(v);
    $("verLine").textContent = "版本 " + (v.version ? "v" + v.version : "dev") +
      (v.has_update && v.latest ? " · 可更新 v" + v.latest : "");
    if (v.has_update){
      btn.disabled = false;
      btn.textContent = "⬆ 更新到 v" + v.latest;
      btn.dataset.pending = "1";
    } else {
      btn.disabled = false;
      btn.textContent = v.latest ? "已是最新" : (v.version ? "已是最新" : "开发模式");
      btn.dataset.pending = "";
    }
  } catch(e){
    btn.disabled = false;
    btn.textContent = "检查更新";
    btn.dataset.pending = "";
  }
}
$("updBtn").onclick = async function(){
  if (this.dataset.pending !== "1"){ checkUpdate(false); return; }
  this.disabled = true;
  this.textContent = "0%";
  UPD.state = "dl";
  UPD.percent = 0;
  UPD.source = null;
  UPD.message = "正在测速并选择最快下载源";
  setUpdUI();
  startProgressPolling();
  try {
    const r = await (await fetch("/api/update", { method: "POST" })).json();
    if (!r.ok) throw new Error(r.error || "更新失败");
    UPD.percent = 100;
    UPD.state = "done";
    UPD.message = "";
    this.textContent = "更新完成，应用即将重启…";
    setUpdUI();
    stopProgressPolling();
    let tries = 0;
    const t = setInterval(async () => {
      tries++;
      try {
        const v = await (await fetch("/api/version")).json();
        clearInterval(t);
        $("verLine").textContent = "版本 v" + v.version;
        this.disabled = false;
        this.textContent = "已是最新";
        this.dataset.pending = "";
        location.reload();
      } catch(_){ /* 新进程未就绪，继续等 */ }
      if (tries > 45){ clearInterval(t); this.textContent = "更新超时，请重启应用"; }
    }, 2000);
  } catch(e){
    stopProgressPolling();
    this.disabled = false;
    UPD.state = "error";
    UPD.source = null;
    UPD.message = String(e && e.message ? e.message : e);
    this.textContent = "更新失败：重试";
  }
};
