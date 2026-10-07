let summaryRequest = null;
function collectionFeedback(kind, title, message){
  const box = $("collectionState");
  if (!box) return;
  const wasKind = box.dataset.kind;
  box.hidden = !kind;
  box.dataset.kind = kind || "";
  $("collectionStateTitle").textContent = title || "";
  $("collectionStateText").textContent = message || "";
  /* 加载中不提供"重试"按钮，避免与进行中的扫描打架 */
  $("collectionRetry").hidden = kind === "loading";
  if (kind !== "loading" && $("collectionAnnouncement").textContent !== title)
    $("collectionAnnouncement").textContent = title || "";
  /* 失败要"说出来"：除了读屏播报，再给一次带重试入口的可见提示（同一错误不重复弹） */
  if (kind === "error" && wasKind !== "error" && window.TMUI){
    TMUI.toast(title + (message ? "：" + message : ""), {
      kind: "error",
      actionLabel: "重试",
      onAction: () => void loadSummary()
    });
  }
}
function setScanControls(busy){
  for (const id of ["reload","reloadTop","collectionRetry"]) {
    const button = $(id);
    if (!button) continue;
    button.disabled = busy;
    button.setAttribute("aria-busy", String(busy));
  }
}
function updateCollectionFeedback(meta){
  const shown = !!(DATA && DATA.partial && (DATA.matrix || []).length);
  if (meta && (meta.busy || meta.queued)) {
    setScanControls(true);
    /* 部分结果已经上屏：进度改由顶栏承载，不再压一条顶部横幅 */
    if (shown) collectionFeedback(null);
    else collectionFeedback("loading", meta.queued ? "扫描任务已排队" : "正在扫描本机数据",
      DATA && !DATA.building ? "上次有效结果仍可查看；新扫描完成后会自动更新。"
                             : "等待本地扫描完成，不使用虚构百分比。");
  } else if (meta && meta.error) {
    collectionFeedback("error","上次扫描未完成", String(meta.error) + "。已有结果保留；可重新读取或在设置中重新扫描。");
    setScanControls(false);
  } else if (DATA && !DATA.building) {
    setScanControls(false);
    if (!(DATA.matrix || []).length) {
      collectionFeedback("empty","未发现可统计记录","当前没有可用日志；可在设置中检查数据源路径并重新扫描。");
    } else {
      /* 扫描失败的来源改由顶栏「扫描异常」芯片承载，页面顶部不再挂横幅 */
      const wasError = $("collectionState").dataset.kind === "error" || $("collectionState").dataset.kind === "loading";
      collectionFeedback(null);
      if (wasError && window.TMUI) TMUI.toast("统计结果已更新", { kind: "success" });
    }
  }
}
function loadSummary(){
  if (summaryRequest) return summaryRequest;
  if (!(DATA && (DATA.matrix || []).length))
    collectionFeedback("loading",DATA ? "正在更新统计结果" : "正在读取本地统计",DATA ? "保留上次有效结果。" : "首次扫描完成后将显示真实用量与日期范围。");
  $("fExport").disabled = !DATA || DATA.building;
  if (!DATA && window.TMUI) TMUI.skeletonKpis();
  summaryRequest = fetch("/api/summary").then((r)=>{if(!r.ok)throw new Error("读取失败（HTTP " + r.status + "）");return r.json();}).then((d)=>{
    if (d.building) { updateCollectionFeedback({busy:true}); return false; }
    if (!Array.isArray(d.matrix) || !d.range || !Array.isArray(d.agents)) throw new Error("返回的数据结构不完整");
    DATA=d;
    if (!DATA.agents.some((a)=>a.name===F.agent)) F.agent="all";
    renderAll();
    /* 部分结果不足以导出：等完整扫描结束再放开 */
    $("fExport").disabled = !!d.partial;
    if(d._meta){LAST_BUILT=d._meta.built_at||LAST_BUILT;syncSettings(d._meta);}
    updateCollectionFeedback(d._meta || {});
    /* 首屏这次请求自己就知道"还在扫、已经有部分结果"——立刻起 3s 追进度，
       不必等 15s 后的第一轮 pollMeta */
    followScanProgress(!!(d.partial && d._meta && (d._meta.busy || d._meta.queued)));
    return true;
  }).catch((e)=>{collectionFeedback("error","统计结果读取失败",String(e.message) + (DATA ? "；上次有效结果仍可查看。" : "；请检查本地服务后重试。"));setScanControls(false);return false;}).finally(()=>{summaryRequest=null;});
  return summaryRequest;
}
$("collectionRetry").onclick=()=>void loadSummary();
function syncFilterSummary(){
  const range=RANGE_LABEL[F.rangeKey] || F.rangeKey;
  $("filterSummary").textContent=range + " · " + (F.agent==="all"?"全部来源":agentLabel(F.agent));
  $("clearFilters").hidden=F.rangeKey==="last7" && F.agent==="all";
  document.querySelectorAll("[data-agent-filter]").forEach((button)=>button.setAttribute("aria-pressed",String(button.dataset.agentFilter===F.agent)));
  persistFilters();   /* 单一写入口（定义在 core.js），展开态也一起存 */
  /* 筛选即地址：把当前过滤视图序列化进 hash，刷新/后退/分享都不丢 */
  if (typeof syncFilterHash === "function") syncFilterHash();
}
/* 「清除筛选」必须连钉住的那天一起清：否则顶栏写着"已清除"，右侧排行还只算一天 */
$("clearFilters").onclick=()=>{F.rangeKey="last7";F.agent="all";F.day=null;F.open.clear();renderAll();};
void loadSummary();
if (!$("updBtn").dataset.pending) checkUpdate(true);
