let summaryRequest = null;
function collectionFeedback(kind, title, message){
  const box = $("collectionState");
  if (!box) return;
  box.hidden = !kind;
  box.dataset.kind = kind || "";
  $("collectionStateTitle").textContent = title || "";
  $("collectionStateText").textContent = message || "";
  $("collectionRetry").hidden = kind === "loading" || kind === "partial";
  if (kind !== "loading" && $("collectionAnnouncement").textContent !== title) $("collectionAnnouncement").textContent = title || "";
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
  if (meta && (meta.busy || meta.queued)) {
    collectionFeedback("loading", meta.queued ? "扫描任务已排队" : "正在扫描本机数据", DATA && !DATA.building ? "上次有效结果仍可查看；新扫描完成后会自动更新。" : "等待本地扫描完成，不使用虚构百分比。");
    setScanControls(true);
  } else if (meta && meta.error) {
    collectionFeedback("error","上次扫描未完成", String(meta.error) + "。已有结果保留；可重新读取或在设置中重新扫描。");
    setScanControls(false);
  } else if (DATA && !DATA.building) {
    setScanControls(false);
    if (!(DATA.matrix || []).length) collectionFeedback("empty","未发现可统计记录","当前没有可用日志；可在设置中检查数据源路径并重新扫描。");
    else if ((DATA.scan_errors || []).length) collectionFeedback("partial","部分来源扫描失败","可用来源仍参与统计；失败来源及影响范围请查看扫描说明。");
    else collectionFeedback(null);
  }
}
function loadSummary(){
  if (summaryRequest) return summaryRequest;
  collectionFeedback("loading",DATA ? "正在更新统计结果" : "正在读取本地统计",DATA ? "保留上次有效结果。" : "首次扫描完成后将显示真实用量与日期范围。");
  $("fExport").disabled = !DATA || DATA.building;
  summaryRequest = fetch("/api/summary").then((r)=>{if(!r.ok)throw new Error("读取失败（HTTP " + r.status + "）");return r.json();}).then((d)=>{
    if (d.building) { updateCollectionFeedback({busy:true}); return false; }
    if (!Array.isArray(d.matrix) || !d.range || !Array.isArray(d.agents)) throw new Error("返回的数据结构不完整");
    DATA=d;
    if (!DATA.agents.some((a)=>a.name===F.agent)) F.agent="all";
    renderAll();
    $("fExport").disabled = false;
    if(d._meta){LAST_BUILT=d._meta.built_at||LAST_BUILT;syncSettings(d._meta);}
    updateCollectionFeedback(d._meta || {});
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
  try {sessionStorage.setItem("voyra-token-filters",JSON.stringify({rangeKey:F.rangeKey,agent:F.agent,metric:F.metric,grain:F.grain,dim:F.dim}));}catch{ /* UI state only */ }
}
$("clearFilters").onclick=()=>{F.rangeKey="last7";F.agent="all";F.open.clear();renderAll();};
void loadSummary();
if (!$("updBtn").dataset.pending) checkUpdate(true);
