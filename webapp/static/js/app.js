function init(){
  fetch("/api/summary").then(r=>r.json()).then(d=>{ DATA=d; renderAll();
    if (d._meta) { LAST_BUILT = d._meta.built_at || null; syncSettings(d._meta); } })
    .catch(e=>{ $("noteBox").innerHTML = `<div class="note err">数据加载失败：${esc(e.message)}</div>`; });
  if (!$("updBtn").dataset.pending) checkUpdate(true);
}

init();
