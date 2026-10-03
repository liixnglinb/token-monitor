/* ---------- 主流程 ---------- */
/* 模型表格的分页 / 搜索状态（纯前端，不改后端契约） */
const PAGE = { index: 0, size: 50, query: "" };
function renderAll(){
  /* 首扫期间 /api/summary 返回 building 占位（无 range/matrix），此时不渲染也不报错，
     等后台扫描完成后 pollMeta 会拉到真数据再走一遍这里 */
  if (!DATA || DATA.building || !DATA.range) return;
  /* 套餐模型集合先行设置：renderAgentList / renderModelDist 都要用它区分「套餐」与「缺价」 */
  window.PLAN_SET = new Set(((DATA.kpi_all && DATA.kpi_all.plan_models) || [])
    .map(x => String(x).toLowerCase()));
  renderSideAgents();
  renderRangeMenu();
  renderHero(); renderMain(); renderAgentList();
  renderModelDist(); renderModelTable(); renderNote(); renderScanInfo();
  syncFilterSummary();
  if (window.TMUI){
    TMUI.clearKpiSkeleton();
    ["heroValAbbr", "heroReq", "heroAvg", "heroCost", "heroEquiv"].forEach(id => { const el = $(id); if (el) el.dataset.loaded = "1"; });
    TMUI.syncAria();
    window.dispatchEvent(new Event("tm:render"));
  }
}

/* 主题切换 → Chart.js 图表重绘：MAIN/DONUT 的颜色在构造时从 CSS 变量解析成
   真实色值，切主题后必须按新 token 重建；SVG 走势（currentColor）与表格占比条
   （var()）会自动适配，无需处理。 */
window.addEventListener("tm:theme", () => {
  if (!DATA || DATA.building || !DATA.range) return;
  renderMain();
  renderModelDist();
});

/* 扫描开销：命中/未命中/判定跳过，让"这次为什么慢"有处可看 */
function renderScanInfo(){
  const el = $("scanInfo"); if (!el) return;
  const c = DATA && DATA.cache_stats;
  if (!c) { el.textContent = ""; return; }
  el.textContent = "扫描：命中 " + (c.hit||0) + " · 重扫 " + (c.miss||0)
    + " · 跳过 " + (c.verdict||0);
  el.title = "命中=文件未变化直接复用上次解析；重扫=本次真正解析；跳过=此前判定无可用数据";
}

/* ---------- 下拉菜单 ---------- */
function renderRangeMenu(){
  const menu = $("ddRangeMenu");
  menu.innerHTML = RANGES.map(([k, label]) =>
    `<button data-k="${k}" class="${F.rangeKey===k ? "on" : ""}"><span>${label}</span><span class="ck">✓</span></button>`).join("");
  $("ddRangeVal").textContent = RANGE_LABEL[F.rangeKey];
  const hint = $("rangeHint");
  if (hint){
    const text = {
      today:"仅显示今天的数据",
      yesterday:"仅显示昨天的数据",
      last7:"仅显示最近 7 天的数据",
      last30:"仅显示最近 30 天的数据",
      last90:"仅显示最近 90 天的数据",
      thismonth:"仅显示本月数据",
      lastmonth:"仅显示上月数据",
      all:"显示全部历史数据",
    };
    hint.textContent = text[F.rangeKey] || "";
  }
}

function renderSideAgents(){
  if (!DATA || !Array.isArray(DATA.agents)) return;
  const allBtn = document.querySelector('[data-agent-filter="all"]');
  if (allBtn) allBtn.classList.toggle("active", F.agent === "all");
  /* 侧栏与窄屏抽屉共用同一份列表：一处渲染、两处注入 */
  const sideWrap = $("sideAgents"), drawerWrap = $("drawerAgents");
  const totalEls = [$("sideAgentTotal"), $("drawerAgentTotal")];
  totalEls.forEach(el => { if (el) el.textContent = String(DATA.agents.length); });
  if (!DATA.agents.length){
    const empty = '<div class="side-empty">未发现用量数据 · 点顶部「重新扫描」</div>';
    if (sideWrap) sideWrap.innerHTML = empty;
    if (drawerWrap) drawerWrap.innerHTML = empty;
  } else {
    const html = DATA.agents.map(a => {
      const name = String(a.name);
      const active = F.agent === name;
      return '<button class="side-project' + (active ? ' active' : '') + '" type="button" data-agent-filter="' + esc(name) + '" aria-pressed="' + active + '" title="' + esc(agentLabel(name)) + '">'
        + '<span class="side-project-icon">' + agentIcon(name) + '</span>'
        + '<span class="side-project-name">' + esc(agentLabel(name)) + '</span>'
        + '<em>' + esc(fmtTok(a.tokens)) + '</em></button>';
    }).join("");
    if (sideWrap) sideWrap.innerHTML = html;
    if (drawerWrap) drawerWrap.innerHTML = html;
  }
  /* 未计入分组：本机检出、但拿不到可用用量（或体量超预算）的来源 —— 让覆盖情况可见 */
  const unc = $("sideUncounted"), drawerUnc = $("drawerUncounted");
  const counted = new Set(DATA.agents.map(a => String(a.name)));
  const norm = s => String(s).toLowerCase().replace(/[\s\-_]+/g, "");
  const labels = DATA.agents.map(a => norm(agentLabel(a.name)));
  const rows = (DATA.coverage || []).filter(c => {
    const id = String(c.id), nm = norm(c.name || id);
    if (counted.has(id)) return false;
    /* 同一应用的旧目录别重复出现（如已计入 WorkBuddy AI，就别再列 WorkBuddy 旧库） */
    return !labels.some(l => l === nm || l.startsWith(nm) || nm.startsWith(l));
  });
  const uncHtml = rows.length
    ? '<div class="side-unc-head">未计入 · ' + rows.length + '</div>'
      + rows.map(c => '<div class="side-unc" title="' + esc(c.name + '：' + (c.note || '')) + '">'
          + '<span class="side-unc-ico">' + agentIcon(String(c.id)) + '</span>'
          + '<span>' + esc(c.name) + '</span></div>').join('')
    : "";
  if (unc) unc.innerHTML = uncHtml;
  if (drawerUnc) drawerUnc.innerHTML = uncHtml;
}
function bindDropdown(ddId, menuId, onPick){
  const dd = $(ddId), menu = $(menuId);
  dd.querySelector(".dd-btn").onclick = e => {
    e.stopPropagation();
    const wasOpen = dd.classList.contains("open");
    closeAllDropdowns();
    if (!wasOpen){ dd.classList.add("open"); menu.hidden = false; }
  };
  menu.onclick = e => {
    const b = e.target.closest("button[data-k]"); if (!b) return;
    onPick(b.dataset.k);
    closeAllDropdowns();
  };
}
function closeAllDropdowns(){
  document.querySelectorAll(".dd.open").forEach(d => d.classList.remove("open"));
  document.querySelectorAll(".dd-menu").forEach(m => m.hidden = true);
}
document.addEventListener("click", closeAllDropdowns);

function renderNote(){
  /* 说明性内容移到侧栏「设置」浮层，主区只保留扫描错误 —— 顶部不再有大段说明 */
  const main = $("noteBox"), side = $("sideNotes");
  if (!main || !side) return;
  const k = DATA.kpi_all;
  window.PLAN_SET = new Set((k.plan_models || []).map(x => String(x).toLowerCase()));
  let side_html = "";
  if (k.plan_tokens > 0)
    side_html += `<div class="note plan">其中 ${fmtTok(k.plan_tokens)} tokens 来自套餐/订阅制模型（商汤小浣熊、Agnes、OX、火山方舟等）—— 按口径只记用量，不计金额。</div>`;
  if (k.unpriced_tokens > 0)
    side_html += `<div class="note unpriced">另有 ${fmtTok(k.unpriced_tokens)} tokens 走 API 但单价不在价表中（${(k.unpriced_tokens/k.tokens*100).toFixed(1)}%），未计入金额 — 实际成本会更高。</div>`;
  const range = rangeDates();
  if (range){
    const t = DATA.matrix.filter(r=>r.date==="unknown").reduce((s,r)=>s+r.tokens,0);
    if (t > 0) side_html += `<div class="note time">时间筛选生效中：另有 ${fmtTok(t)} tokens 因日志缺失日期戳，仅在「全部」时计入</div>`;
  }
  main.innerHTML = (DATA.scan_errors && DATA.scan_errors.length)
    ? `<div class="note err">部分数据源扫描失败：${esc(DATA.scan_errors.map(e=>e.agent).join("、"))}</div>` : "";
  side.innerHTML = side_html;
}


/* ---------- Hero：Token 吞吐全景（宏观指标 + 物理构成 + 经济账本） ---------- */
/* 缓存经济学的典型比例：读取按输入价 10%、写入按 125%。仅用于"等效计费量/节省"
   的估算展示，真实金额仍由后端按各模型价格计算。 */
const CR_RATIO = 0.1, CW_RATIO = 1.25;

function renderHero(){
  const rows = rowsFor(true);
  const sum = key => rows.reduce((s,r)=>s+(r[key]||0),0);
  const tokens = sum("tokens");
  const inp = sum("inp"), out = sum("out"), cr = sum("cr"), cw = sum("cw");
  const think = rows.reduce((s,r)=>s+(r.think||0),0);
  const req = sum("requests");
  const cost = sum("cost");
  const planSet = window.PLAN_SET || new Set();
  const planTokens = rows.reduce((s,r)=>s+(planSet.has(String(r.model).toLowerCase())?r.tokens:0),0);
  const compTotal = inp + out + cr + cw;

  /* 大数：缩写 ↔ 完整（点击锁定，悬停预览） */
  const fullText = fmtInt(compTotal);
  $("heroValAbbr").textContent = fmtTok(compTotal);
  $("heroValFull").textContent = fullText;
  const numBtn = $("heroNum");
  if (numBtn && !numBtn.dataset.bound){
    numBtn.dataset.bound = "1";
    numBtn.onclick = () => {
      const mode = numBtn.dataset.mode === "abbr" ? "full" : "abbr";
      numBtn.dataset.mode = mode;
      $("heroValFull").hidden = mode !== "full";
      $("heroValAbbr").hidden = mode === "full";
    };
  }

  /* 计费拆分 pill（按 Token 占比） */
  const pillM = $("heroPillMetered"), pillP = $("heroPillPlan");
  const meteredTokens = Math.max(compTotal - planTokens, 0);
  if (planTokens > 0){
    pillP.hidden = false;
    pillP.textContent = "套餐覆盖 " + fmtTok(planTokens) + " · " + (planTokens/compTotal*100).toFixed(0) + "%";
    pillM.hidden = false;
    pillM.textContent = "按量计费 " + fmtTok(meteredTokens) + " · " + (meteredTokens/compTotal*100).toFixed(0) + "%";
  } else { pillP.hidden = true; pillM.hidden = true; }

  /* 缓存命中与等效计费量 */
  const cacheBase = inp + cw + cr;
  $("heroCache").textContent = cacheBase > 0
    ? "缓存命中 " + (cr/cacheBase*100).toFixed(1) + "%" : "缓存命中 —";
  const equiv = inp + CR_RATIO*cr + CW_RATIO*cw;
  $("heroEquiv").textContent = compTotal > 0 ? fmtTok(equiv) + " tok" : "—";
  $("heroSavingPct").textContent = compTotal > 0
    ? "较全量直连节省 " + Math.max(0, (1 - equiv/compTotal)*100).toFixed(1) + "%" : "";

  /* 物理构成分段条（think 属于输出的子段，不参与总和） */
  const seg = $("heroSegBar");
  const parts = [
    ["cr",  "缓存读取", cr],
    ["inp", "基础输入", inp],
    ["cw",  "缓存写入", cw],
    ["out", "输出生成", out],
  ].filter(p => p[2] > 0);
  const pct = v => compTotal > 0 ? (v/compTotal*100) : 0;
  seg.innerHTML = parts.map(([cls, label, val]) => {
    const w = pct(val);
    const sub = (cls === "out" && think > 0)
      ? '<div class="seg-sub seg-think" style="--sub-w:' + (think/Math.max(val,1)*100).toFixed(1)
        + '%" title="其中深度思考: ' + esc(fmtTok(think)) + ' (' + esc(fmtInt(think/Math.max(val,1)*100)) + '% of 输出)"></div>'
      : "";
    return '<div class="seg seg-' + cls + '" style="--w:' + w.toFixed(1) + '%" title="'
      + label + ': ' + esc(fmtTok(val)) + ' (' + w.toFixed(1) + '%)">' + sub + '</div>';
  }).join("") || '<div class="seg seg-empty" style="--w:100%" title="暂无数据"></div>';
  seg.setAttribute("aria-label", "Token 物理构成：" + parts.map(([l,v])=>l+" "+(pct(v)).toFixed(1)+"%").join("、"));

  /* 图例网格 */
  $("heroLegend").innerHTML = parts.map(([cls, label, val]) =>
    '<div class="legend-item"><i class="dot dot-' + cls + '"></i><span>' + label
    + (cls === "out" && think > 0 ? '<small class="legend-think">含思考 ' + esc(fmtTok(think)) + '</small>' : "")
    + '</span><b>' + esc(fmtTok(val)) + '</b><em>' + pct(val).toFixed(1) + '%</em></div>'
  ).join("") || '<div class="legend-item"><span>暂无构成数据</span></div>';

  /* 经济账本 */
  const unpricedTokens = rows.reduce((s,r)=>s+((r.cost<=0 && !planSet.has(String(r.model).toLowerCase()))?r.tokens:0),0);
  const planOnly = tokens > 0 && planTokens >= tokens * 0.995;
  const costEl = $("heroCost");
  costEl.textContent = cost > 0 ? fmtCNY(cost * DATA.cny_rate)
    : (planOnly ? "套餐" : (unpricedTokens > 0 ? "未计价" : fmtCNY(0)));
  costEl.title = cost > 0 ? "按各模型价格估算，不代表实际账单 · 等效 $" + fmtUSD(cost).slice(1)
    : "套餐模型不计费；单价缺失的用量不记为免费";
  $("heroCostSub").textContent = cost > 0 ? "$" + fmtUSD(cost).slice(1) + " · 汇率 " + DATA.cny_rate : "";
  /* 节省资金：被缓存吸收的那部分输入 × 输入等效价（比例法估算） */
  const savedTokens = cr * (1 - CR_RATIO) - cw * (CW_RATIO - 1);
  const perTokPrice = compTotal > 0 ? (cost * DATA.cny_rate) / compTotal : 0;
  $("heroSave").textContent = savedTokens > 0 && cost > 0
    ? "≈ " + fmtCNY(savedTokens * perTokPrice) : "—";
  $("heroSave").title = savedTokens > 0
    ? "按典型比例估算：读取省下的约 " + fmtTok(Math.max(savedTokens,0)) + " tokens × 平均输入单价"
    : "当前缓存写入开销高于读取收益或无缓存数据";
  const range = rangeDates();
  const days = range ? Math.round((new Date(range[1]) - new Date(range[0]))/864e5) + 1
    : (DATA.range.max && DATA.range.min
      ? Math.round((new Date(DATA.range.max) - new Date(DATA.range.min))/864e5)+1 : 0);
  $("heroReq").textContent = fmtInt(req);
  $("heroReqSub").textContent = days ? "日均 " + (req/days < 1 ? "<1" : fmtInt(req/days)) : "全部时间";
  $("heroAvg").textContent = req ? fmtInt(Math.round(tokens / req)) : "—";
  $("heroAvgSub").textContent = req ? "tokens / 请求" : "无记录";
}

/* ---------- 主图与每日统计 ---------- */
function metricNumber(rows, metric){
  return rows.reduce((sum, row) => sum + cellVal(row, metric), 0);
}
function metricText(value, metric){
  if (metric === "cost") return fmtCNY(value * DATA.cny_rate);
  if (metric === "tokens") return fmtTok(value) + " tok";
  return fmtInt(value) + " 次";
}
function weekdayCN(label){
  const d = new Date(label + "T00:00:00");
  return Number.isNaN(d.getTime()) ? "" : "周" + "日一二三四五六"[d.getDay()];
}
function renderTrendSummary(list, metric){
  const box = $("trendSummary");
  if (!box) return;
  const total = list.reduce((sum, item) => sum + item.value, 0);
  const active = list.filter(item => item.value > 0);
  const peak = list.reduce((best, item) => item.value > best.value ? item : best,
    { label:"", value:0 });
  const average = list.length ? total / list.length : 0;
  const first = list.length ? list[0].label : "";
  const last = list.length ? list[list.length - 1].label : "";
  const rangeText = first && last ? (F.grain === "month"
    ? fmtMonth(first) + " - " + fmtMonth(last)
    : md(first) + " - " + md(last)) : "暂无日期";
  const peakText = peak.label
    ? (F.grain === "month" ? fmtMonth(peak.label) : md(peak.label)) : "—";
  const items = [
    ["区间总量", metricText(total, metric), rangeText],
    ["日均", metricText(average, metric), list.length + " 个周期"],
    ["峰值", metricText(peak.value, metric), peakText + " 最高"],
    ["活跃", fmtInt(active.length) + (F.grain === "month" ? " 个月" : " 天"),
      list.length ? "覆盖率 " + Math.round(active.length / list.length * 100) + "%" : ""],
  ];
  box.innerHTML = items.map(item =>
    '<div class="trend-stat"><span>' + esc(item[0]) + '</span>'
    + '<b>' + item[1] + '</b><small>' + esc(item[2]) + '</small></div>').join("");
}
/* 空态图标：与文案一起出现，避免"只有一行灰字"的干瘪空态 */
const EMPTY_ICON = '<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" '
  + 'stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
  + '<rect x="3.5" y="5" width="17" height="13" rx="2.5"/><path d="M7 12.5h4M7 9h7M7 15.5h2.5"/></svg>';
function emptyBlock(title, hint, action){
  return '<div class="empty">' + EMPTY_ICON
    + '<div class="t1">' + esc(title) + '</div>'
    + (hint ? '<div class="t2">' + esc(hint) + '</div>' : '')
    + (action ? '<button type="button" class="btn btn-sm" data-empty-action>' + esc(action) + '</button>' : '')
    + '</div>';
}
function renderDailyDetail(rows, list, metric){
  const box = $("dailyList");
  const count = $("dailyCount");
  const title = $("dailyTitle");
  const hint = $("dailyHint");
  if (!box) return;
  const isMonth = F.grain === "month";
  if (title) title.textContent = isMonth ? "每月明细" : "每日明细";
  if (hint) hint.textContent = isMonth
    ? "按月查看用量、成本和请求次数"
    : "按日期查看用量、成本和请求次数";
  if (count) count.textContent = list.length + " " + (isMonth ? "个月" : "天");
  if (!list.length){
    box.innerHTML = '<div class="daily-empty">'
      + '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.4" '
      + 'stroke-linecap="round" aria-hidden="true"><rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M3.5 9.5h17M8 3.5v3M16 3.5v3M8.5 14h7"/></svg>'
      + '<span>当前筛选下没有可展示的' + (isMonth ? "月份" : "日期") + '数据</span>'
      + '<button type="button" class="btn btn-sm" data-empty-action="range-all">查看全部时间</button>'
      + '</div>';
    const action = box.querySelector("[data-empty-action]");
    if (action) action.onclick = () => { F.rangeKey = "all"; renderAll(); };
    return;
  }
  const byPeriod = new Map();
  for (const row of rows){
    if (!row.date || row.date === "unknown") continue;
    const key = isMonth ? row.date.slice(0,7) : row.date;
    const item = byPeriod.get(key) || { tokens:0, cost:0, requests:0 };
    item.tokens += row.tokens; item.cost += row.cost; item.requests += row.requests;
    byPeriod.set(key, item);
  }
  const values = list.map(item => item.value);
  const max = Math.max(...values, 1);
  const total = values.reduce((sum, value)=>sum+value, 0) || 1;
  const ordered = list.slice().reverse().slice(0, 14);
  box.innerHTML = ordered.map(item => {
    const extra = byPeriod.get(item.label) || { tokens:0, cost:0, requests:0 };
    const pct = item.value / max * 100;
    const share = item.value / total * 100;
    const dayLabel = isMonth ? fmtMonth(item.label) : md(item.label);
    const daySub = isMonth ? item.label.slice(0,4) : weekdayCN(item.label);
    return '<div class="daily-row">'
      + '<div class="daily-date"><b>' + esc(dayLabel) + '</b><small>' + esc(daySub) + '</small></div>'
      + '<div class="daily-primary"><b>' + metricText(item.value, metric) + '</b><span>占 ' + share.toFixed(1) + '%</span></div>'
      + '<div class="daily-track"><i style="width:' + Math.max(item.value ? 2 : 0, pct).toFixed(1) + '%"></i></div>'
      + '<div class="daily-meta">'
      + (F.metric !== "tokens" ? '<span>' + fmtTok(extra.tokens) + ' tok</span>' : '')
      + (F.metric !== "cost" && extra.cost > 0
          ? '<span>' + fmtCNY(extra.cost * DATA.cny_rate) + '</span>' : '')
      + (F.metric !== "requests" ? '<span>' + fmtInt(extra.requests) + ' 次</span>' : '')
      + '</div>'
      + '</div>';
  }).join("");
}
function renderMain(){
  const rows = rowsFor(false);
  const range = rangeDates();
  const theme = refreshChartTokens();
  refreshPalette();
  syncSegAvailability();
  if (F.lens === "composition"){
    $("chartHint").textContent = "按 Token 物理构成（读取/写入/输入/输出）堆叠，观察上下文膨胀与生成强度";
    return renderComposition(rows, range, theme);
  }
  if (F.lens === "cache"){
    $("chartHint").textContent = "上轨=全量等效输入（虚线），下轨=真实付费输入；阴影区为缓存吸收的开销";
    return renderCacheLeverage(rows, range, theme);
  }
  $("chartHint").textContent = "按日聚合的 Token 趋势，可切换数据源与模型拆分";

  const fmt = fmtTick[F.metric];
  const suffix = F.grain === "month" ? "（按月）" : "";
  const title = F.grain === "month"
    ? (F.metric === "tokens" ? "Tokens 趋势" : METRIC_NAME[F.metric]) + suffix
    : (F.metric === "tokens" ? "每日 Token" : F.metric === "cost" ? "每日消耗金额" : "每日请求次数");
  $("mainTitle").textContent = title;

  const raw = groupSeries(rows, F.metric, F.grain);
  /* 月份轴至少铺满最近 12 个月：没用过的月份也显示，按月统计才有环比意义 */
  let data;
  if (F.grain === "day"){
    data = fillDays(raw, range && range[0]);
  } else {
    const endSrc = (range && range[1]) || DATA.range.max;
    const startSrc = (range && range[0]) || DATA.range.min;
    const endM = endSrc ? endSrc.slice(0, 7) : null;
    const startM = startSrc ? startSrc.slice(0, 7) : null;
    const floorM = endM ? addMonths(endM, -11) : null;   // 最近 12 个月的起点
    const axisStart = (startM && floorM && startM < floorM) ? startM : (floorM || startM);
    data = fillMonths(raw, axisStart, endM);
  }
  const labels = data.map(d=>d[0]);
  const list = data.map(([label, value]) => ({ label, value }));
  const total = list.reduce((sum, item) => sum + item.value, 0);
  $("mainSum").textContent = DIM_NAME[F.dim] + " · " + metricText(total, F.metric);
  /* 摘要与明细只统计筛选区间内的月份，零填充月份不稀释"日均/覆盖率" */
  let sumList = list;
  if (F.grain === "month"){
    const sM = ((range && range[0]) || DATA.range.min || "").slice(0, 7);
    const eM = ((range && range[1]) || DATA.range.max || "").slice(0, 7);
    if (sM && eM) sumList = list.filter(item => item.label >= sM && item.label <= eM);
  }
  renderTrendSummary(sumList, F.metric);
  renderDailyDetail(rows, sumList.length ? sumList : list, F.metric);

  const emp = $("mainEmpty");
  if (total === 0){
    const hasTok = rows.some(r=>r.tokens > 0);
    let t1 = "当前筛选下无记录";
    let t2 = "试试把时间范围切换到近 7 天或全部";
    if (F.metric === "cost" && hasTok){
      t1 = "消耗金额为 ¥0.00";
      t2 = "这些模型的单价不在价格库中，未计入金额 · 切换到 Tokens / 请求可查看用量";
    } else if (hasTok){
      t1 = "当前筛选下无" + (F.metric === "tokens" ? " Token" : "请求") + "记录";
      t2 = "试试切换时间范围或指标";
    }
    emp.innerHTML = '<div class="t1">' + t1 + '</div><div class="t2">' + t2 + '</div>';
    emp.hidden = false;
  } else {
    emp.hidden = true;
  }

  let members;
  if (F.dim === "total"){
    members = [{ name: METRIC_NAME[F.metric], rows }];
  } else {
    const tot = new Map();
    for (const r of rows) tot.set(r[F.dim], (tot.get(r[F.dim])||0) + cellVal(r, F.metric));
    const topNames = [...tot.entries()].sort((a,b)=>b[1]-a[1]).slice(0,6).map(e=>e[0]);
    const others = rows.filter(r=>!topNames.includes(r[F.dim]));
    members = topNames.map(name=>({ name, rows: rows.filter(r=>r[F.dim]===name) }));
    if (others.length) members.push({ name: "其他", rows: others });
  }
  const series = members.map(m=>{
    const mm = new Map(groupSeries(m.rows, F.metric, F.grain));
    return { name: m.name, data: labels.map(l=>mm.get(l)||0) };
  });

  const lineMode = F.metric === "tokens" && F.dim === "total";
  const opts = baseOpts(fmt, F.metric==="cost"?"¥":"");
  opts.scales.x.stacked = !lineMode;
  opts.scales.y.stacked = !lineMode;
  if (F.grain === "day") opts.scales.x.ticks.callback = (v, i) => md(labels[i] || v);
  else if (F.grain === "month") opts.scales.x.ticks.callback = (v, i) => fmtMonth(labels[i] || v);
  opts.plugins.tooltip.callbacks.title = items => {
    if (!items || !items.length) return "";
    const k = items[0].label;
    const tot2 = items.reduce((s,i)=>s+(i.parsed.y||0),0);
    return (F.grain === "month" ? fmtMonth(k) : k) + "    " + metricText(tot2, F.metric);
  };
  opts.plugins.tooltip.callbacks.label = c => {
    return " " + c.dataset.label + "   " + metricText(c.parsed.y, F.metric);
  };

  if (MAIN) MAIN.destroy();
  MAIN = new Chart($("mainChart"), {
    type: lineMode ? "line" : "bar",
    data: { labels, datasets: series.map((s,i)=>{
      const color = PAL[i % PAL.length];
      if (lineMode) return {
        label: s.name, data: s.data, borderColor: color,
        backgroundColor: context => lineGradient(context, color),
        fill: true, tension: .34, borderWidth: 2.2,
        pointRadius: labels.length <= 12 ? 2.6 : 0,
        pointHoverRadius: 5, pointBackgroundColor: theme.surface,
        pointBorderColor: color, pointBorderWidth: 2,
      };
      return {
        label: s.name, data: s.data, backgroundColor: context => barGradient(context, i),
        stack: "s", maxBarThickness: 28, barPercentage: .66, categoryPercentage: .78,
        borderRadius: 5, borderSkipped: false,
      };
    }) },
    options: opts,
    plugins: [crosshair]
  });
}

/* ---------- 视角：实体 / 物理构成 / 缓存杠杆 ----------
   composition：Token 五态分流堆叠（cr/cw/inp/out，颜色取 --tok-*）；
   cache：缓存杠杆效益双轨（上轨=全量等效输入，下轨=真实付费输入）。
   两个视角都是 Token 口径，故自动停用「指标/维度」切换。 */
const COMP_META = [
  ["cr",  "缓存读取", "--tok-cr"],
  ["cw",  "缓存写入", "--tok-cw"],
  ["inp", "基础输入", "--tok-inp"],
  ["out", "输出生成", "--tok-out"],
];
function syncSegAvailability(){
  const structured = F.lens !== "entity";
  ["segMetric", "segDim"].forEach(id => {
    const seg = $(id);
    if (!seg) return;
    seg.classList.toggle("seg-disabled", structured);
    seg.querySelectorAll("button").forEach(b => { b.disabled = structured; });
  });
}
function seriesAxis(raw, range){
  if (F.grain === "day") return fillDays(raw, range && range[0]);
  const endSrc = (range && range[1]) || DATA.range.max;
  const startSrc = (range && range[0]) || DATA.range.min;
  const endM = endSrc ? endSrc.slice(0, 7) : null;
  const startM = startSrc ? startSrc.slice(0, 7) : null;
  const floorM = endM ? addMonths(endM, -11) : null;
  const axisStart = (startM && floorM && startM < floorM) ? startM : (floorM || startM);
  return fillMonths(raw, axisStart, endM);
}
function axisTickCallback(opts, labels){
  if (F.grain === "day") opts.scales.x.ticks.callback = (v, i) => md(labels[i] || v);
  else opts.scales.x.ticks.callback = (v, i) => fmtMonth(labels[i] || v);
}
function rebuildMain(labels, datasets, opts, type){
  if (MAIN) MAIN.destroy();
  MAIN = new Chart($("mainChart"), {
    type, data: { labels, datasets }, options: opts, plugins: [crosshair]
  });
}
function renderComposition(rows, range, theme){
  const labels = seriesAxis([], range).map(d => d[0]);
  const series = COMP_META.map(([key, label]) => {
    const map = new Map(groupSeries(rows, key, F.grain));
    return { key, label, data: labels.map(l => map.get(l) || 0) };
  }).filter(s => s.data.some(v => v > 0));
  const totalTok = series.reduce((acc, s) => acc + s.data.reduce((a, b) => a + b, 0), 0);
  const thinkTotal = rows.reduce((s, r) => s + (r.think || 0), 0);

  $("mainTitle").textContent = "Token 物理构成" + (F.grain === "month" ? "（按月）" : "");
  $("mainSum").textContent = "总量 · " + fmtTok(totalTok) + " tok";
  const opts = baseOpts(fmtTick.tokens, "");
  opts.scales.x.stacked = true;
  opts.scales.y.stacked = true;
  opts.plugins.tooltip.callbacks.title = items => items && items.length
    ? (F.grain === "month" ? fmtMonth(items[0].label) : items[0].label) + "    "
      + fmtTok(items.reduce((s, i) => s + (i.parsed.y || 0), 0)) + " tok" : "";
  opts.plugins.tooltip.callbacks.label = c => " " + c.dataset.label + "   " + fmtTok(c.parsed.y) + " tok";
  axisTickCallback(opts, labels);
  rebuildMain(labels, series.map((s, i) => ({
    label: s.label, data: s.data,
    backgroundColor: context => barGradient(context, i),
    stack: "comp", maxBarThickness: 28, barPercentage: .66, categoryPercentage: .78,
    borderRadius: 4, borderSkipped: false,
  })), opts, "bar");

  $("trendSummary").innerHTML = COMP_META.map(([key, label]) => {
    const total = rows.reduce((s, r) => s + (r[key] || 0), 0);
    return '<div class="trend-stat"><span>' + label + '</span><b>' + esc(fmtTok(total))
      + '</b><small>' + (totalTok > 0 ? (total / totalTok * 100).toFixed(1) + "%" : "—") + '</small></div>';
  }).join("");
  renderDailyDetail(rows, [], "tokens");
  const emp = $("mainEmpty");
  emp.hidden = totalTok > 0;
  if (totalTok === 0) emp.innerHTML = '<div class="t1">当前筛选下无 Token 记录</div>'
    + '<div class="t2">试试把时间范围切换到近 7 天或全部</div>';
  void thinkTotal;
}
function renderCacheLeverage(rows, range, theme){
  const perDay = new Map();
  for (const r of rows){
    if (r.date === "unknown") continue;
    const o = perDay.get(r.date) || { inp: 0, cr: 0, cw: 0 };
    o.inp += r.inp || 0; o.cr += r.cr || 0; o.cw += r.cw || 0;
    perDay.set(r.date, o);
  }
  const raw = [...perDay.entries()].sort((a, b) => a[0] < b[0] ? -1 : 1)
    .map(([d, o]) => [d, o.inp + o.cr + o.cw]);
  const labels = seriesAxis(raw, range).map(d => d[0]);
  const byDate = new Map([...perDay.entries()]);
  const full = [], paid = [];
  for (const l of labels){
    const o = byDate.get(l) || { inp: 0, cr: 0, cw: 0 };
    full.push(o.inp + o.cr);
    paid.push(o.inp + CR_RATIO * o.cr + CW_RATIO * o.cw);
  }
  const totFull = full.reduce((a, b) => a + b, 0);
  const totPaid = paid.reduce((a, b) => a + b, 0);
  const saved = Math.max(totFull - totPaid, 0);

  $("mainTitle").textContent = "缓存杠杆效益" + (F.grain === "month" ? "（按月）" : "");
  $("mainSum").textContent = "等效输入 " + fmtTok(totFull) + " · 实付 " + fmtTok(totPaid);
  const fmtT = v => v >= 1e9 ? (v/1e9).toFixed(1)+"B" : v >= 1e6 ? (v/1e6).toFixed(1)+"M" : v >= 1e3 ? (v/1e3).toFixed(0)+"k" : String(Math.round(v));
  const opts = baseOpts(fmtT, "");
  opts.scales.y.stacked = false;
  opts.plugins.tooltip.callbacks.title = items => items && items.length
    ? (F.grain === "month" ? fmtMonth(items[0].label) : items[0].label) : "";
  opts.plugins.tooltip.callbacks.label = c => c.datasetIndex === 0
    ? " 全量等效输入   " + fmtTok(c.parsed.y) + " tok"
    : " 真实付费输入   " + fmtTok(c.parsed.y) + " tok";
  axisTickCallback(opts, labels);
  const solid = cssVar("--brand-strong", "#7AA4FF");
  const green = cssVar("--tok-cr", "#10B981");
  rebuildMain(labels, [
    { label: "全量等效输入", data: full, borderColor: theme.muted,
      borderDash: [5, 4], borderWidth: 1.6, pointRadius: labels.length <= 12 ? 2.4 : 0,
      pointBackgroundColor: theme.surface, tension: .3, fill: false },
    { label: "真实付费输入", data: paid, borderColor: solid,
      backgroundColor: hexA(green.startsWith("#") ? green : "#10B981", .16),
      fill: "-1", borderWidth: 2.2, pointRadius: labels.length <= 12 ? 2.4 : 0,
      pointBackgroundColor: theme.surface, tension: .3 },
  ], opts, "line");

  $("trendSummary").innerHTML =
    '<div class="trend-stat"><span>全量等效输入</span><b>' + esc(fmtTok(totFull)) + '</b><small>输入 + 缓存读取 + 写入</small></div>'
    + '<div class="trend-stat"><span>真实付费输入</span><b>' + esc(fmtTok(totPaid)) + '</b><small>含读取 10% · 写入 125%</small></div>'
    + '<div class="trend-stat"><span>缓存吸收</span><b>' + esc(fmtTok(saved)) + '</b><small>阴影区面积</small></div>'
    + '<div class="trend-stat"><span>节省率</span><b>' + (totFull > 0 ? (saved / totFull * 100).toFixed(1) + "%" : "—") + '</b><small>估算口径</small></div>';
  renderDailyDetail(rows, [], "tokens");
  const emp = $("mainEmpty");
  emp.hidden = totFull > 0;
  if (totFull === 0) emp.innerHTML = '<div class="t1">当前筛选下无缓存数据</div>'
    + '<div class="t2">该口径需要来源记录缓存读取/写入明细（Codex、Claude 等已支持）</div>';
}

/* ---------- Agent 用量榜（可折叠 + 会话明细已并入 SVG title） ---------- */

/* ---------- 迷你走势：纯 SVG 折线 + 渐变面积，不用 Chart.js ----------
   排行榜里每个数据源、展开后每个模型都有一条走势。
   之前用 Chart.js 实例，几十条同时驻留会吃掉大量内存并掉帧；
   SVG 由字符串直接生成：0 实例、0 监听器，主题切换靠 currentColor 自动换色。
   面积填充直接用 fill-opacity，不引入 <defs> 随机 id（避免碰撞与注入面）。 */
function sparklineSVG(pairs, cssColor){
  const vals = pairs.map(p => p[1]);
  const n = vals.length;
  if (!n) return '<span class="spark-empty">—</span>';
  const W = 120, H = 28, PAD = 2;
  const max = Math.max(...vals, 1);
  const peak = vals.indexOf(Math.max(...vals));
  const xs = i => PAD + (n === 1 ? (W - 2 * PAD) / 2 : (i / (n - 1)) * (W - 2 * PAD));
  const ys = v => H - PAD - (v / max) * (H - 2 * PAD);
  const pts = vals.map((v, i) => xs(i).toFixed(1) + "," + ys(v).toFixed(1)).join(" ");
  const area = "M " + xs(0).toFixed(1) + "," + ys(vals[0]).toFixed(1)
    + " L " + pts + " L " + xs(n - 1).toFixed(1) + "," + H + " L " + xs(0).toFixed(1) + "," + H + " Z";
  const nonzero = vals.filter(v => v > 0).length;
  return '<svg class="sparkline" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none"'
    + ' role="img" aria-label="每日 Token 走势，' + nonzero + ' 天有数据，峰值 ' + esc(md(pairs[peak][0])) + ' ' + esc(fmtTok(vals[peak])) + ' tok"'
    + (cssColor ? ' style="color:' + cssColor + '"' : "") + '>'
    + '<path d="' + area + '" fill="currentColor" fill-opacity="0.16" stroke="none"/>'
    + '<polyline fill="none" stroke="currentColor" stroke-width="1.8" vector-effect="non-scaling-stroke"'
    + ' stroke-linecap="round" stroke-linejoin="round" points="' + pts + '"/>'
    + '</svg>';
}
/* 迷你走势对应的"每日 Token"序列：与旧迷你图同源（fillDays 补零日期轴） */
function sparkPairs(rows, start){
  return fillDays(groupSeries(rows, "tokens", "day"), start);
}
/* 金额为 0 但有用量时，用三态徽标区分「按量计费 / 套餐覆盖 / 未计价」，
   避免把缺价或订阅制误读成真正免费 */
function costText(cost, tokens, model, forcePlan){
  if (cost > 0) return '<span class="cost-priced">' + fmtCNY(cost * DATA.cny_rate) + '</span>';
  if (!(tokens > 0)) return fmtCNY(0);
  const set = window.PLAN_SET || new Set();
  const isPlan = !!forcePlan || !!(model && set.has(String(model).toLowerCase()));
  if (isPlan){
    return '<span class="pill-pill pill-plan" title="套餐/订阅制模型（如商汤小浣熊、Agnes 等）：只记吞吐量，金额按 ¥0 统计">套餐覆盖</span>';
  }
  return '<span class="pill-pill pill-unpriced" title="单价不在价格库，未计入金额 —— 不是免费；可在 custom-pricing.json 补充单价">未计价</span>';
}
/* 长模型名智能分段：Provider 前缀弱化、尾部核心名保持醒目 */
function modelCellHTML(name){
  const s = String(name);
  const cut = s.lastIndexOf("/");
  const prov = cut > 0 ? s.slice(0, cut + 1) : "";
  const core = cut > 0 ? s.slice(cut + 1) : s;
  return '<span class="model-cell" title="' + esc(s) + '">'
    + (prov ? '<span class="model-provider">' + esc(prov) + '</span>' : "")
    + '<span class="model-name">' + esc(core) + '</span></span>';
}

/* ---------- 模型用量分布（环形图 + 双列 Top10，参考阿里云百炼看板） ---------- */
let DONUT = null;
function renderModelDist(){
  const rows = rowsFor(false);
  const agg = new Map();
  for (const r of rows){
    const o = agg.get(r.model) || { tokens:0, req:0, cost:0 };
    o.tokens += r.tokens; o.req += r.requests; o.cost += r.cost;
    agg.set(r.model, o);
  }
  const byTok = [...agg.entries()].sort((a,b)=>b[1].tokens-a[1].tokens);
  const byReq = [...agg.entries()].sort((a,b)=>b[1].req-a[1].req);

  /* 环形图按 Token 占比：前 8 个 + 其余合并，避免色块过碎 */
  const TOPN = 8;
  const head = byTok.slice(0, TOPN);
  const restTok = byTok.slice(TOPN).reduce((s, x)=>s + x[1].tokens, 0);
  const items = head.map(([n, o])=>({ name:n, val:o.tokens }));
  if (restTok > 0) items.push({ name:"其他 " + (byTok.length - TOPN) + " 个", val:restTok });
  const totalTok = items.reduce((s, i)=>s + i.val, 0) || 1;

  $("donutN").textContent = byTok.length;
  $("donutCap").textContent = "个模型 · " + fmtTok(totalTok);
  $("distSum").textContent = fmtInt(totalTok) + " tokens";

  if (DONUT){ DONUT.destroy(); DONUT = null; }
  if (items.length){
    DONUT = new Chart($("donutChart"), {
      type: "doughnut",
      data: {
        labels: items.map(i=>i.name),
        datasets: [{
          data: items.map(i=>i.val),
          backgroundColor: items.map((_, i)=>PAL[i % PAL.length]),
          borderColor: cssVar("--surface", "#161B22"), borderWidth: 3, hoverOffset: 7,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: "76%",
        plugins: {
          legend: { display: false },
          tooltip: Object.assign({}, TT, {
            callbacks: {
              title: it => it && it.length ? it[0].label : "",
              label: c => " " + fmtTok(c.parsed) + " · 占 " + (c.parsed / totalTok * 100).toFixed(1) + "%",
            },
          }),
        },
      },
    });
  }
  $("donutLegend").innerHTML = items.slice(0, 8).map((i, k)=>
    '<span><i style="background:' + PAL[k % PAL.length] + '"></i>' + esc(i.name) + '</span>').join("");

  /* 双列 Top10：按调用次数排序（与百炼一致） */
  const top = byReq.slice(0, 10);
  const maxReq = Math.max(...top.map(([, o]) => o.req), 1);
  const col = (arr, start) => arr.map(([n, o], k)=>
    '<div class="t10-row" data-model="' + esc(n) + '" title="查看 ' + esc(n) + ' 的明细">'
    + '<span class="idx">Top ' + (start + k + 1) + '</span>'
    + '<span class="dot" style="background:' + PAL[(start + k) % PAL.length] + '"></span>'
    + '<span class="nm">' + esc(n) + '</span>'
    + '<span class="t10-bar"><i style="width:' + Math.max(3, o.req / maxReq * 100).toFixed(1) + '%;background:' + PAL[(start + k) % PAL.length] + '"></i></span>'
    + '<span class="val">' + fmtInt(o.req) + '<em>次</em></span>'
    + '</div>').join("");
  const box = $("top10");
  box.innerHTML = '<div>' + col(top.slice(0, 5), 0) + '</div><div>' + col(top.slice(5, 10), 5) + '</div>';

  /* 点击某行 → 跳到「模型成本」视图看明细 */
  box.querySelectorAll(".t10-row").forEach(el=>{
    el.onclick = () => {
      switchView("models");
      window.scrollTo({ top: 0, behavior: "smooth" });
    };
  });
}

function renderAgentList(){
  const rows = rowsFor(false);
  const range = rangeDates();
  const start = range && range[0];
  const ag = new Map();
  const planSet = window.PLAN_SET || new Set();
  for (const r of rows){
    const o = ag.get(r.agent) || {tokens:0, cost:0, requests:0, planTokens:0};
    o.tokens += r.tokens; o.cost += r.cost; o.requests += r.requests;
    if (planSet.has(String(r.model).toLowerCase())) o.planTokens += r.tokens;
    ag.set(r.agent, o);
  }
  const list = [...ag.entries()].sort((a,b)=>b[1].tokens-a[1].tokens);   // 消耗多的在上
  const wrap = $("agentList");
  if (!list.length){
    wrap.innerHTML = '<div class="card"><div class="empty">当前筛选下无数据</div></div>'; return;
  }

  wrap.innerHTML =
    '<section class="agent-panel">' +
      '<div class="agent-panel-head">' +
        '<div><h3>Agent 用量排行</h3><p>按 Token 消耗排序，点行展开模型明细</p></div>' +
        '<span class="agent-panel-count">' + fmtInt(list.length) + ' 个数据源</span>' +
      '</div>' +
      '<div id="agCards"></div>' +
    '</section>';
  const box = $("agCards");
  /* 分批挂 DOM：几十条目一次性 innerHTML 会造成长任务；每批 12 条保持滚动流畅 */
  const CHUNK = 12;
  let rendered = 0;

  function renderChunk(){
    const slice = list.slice(rendered, rendered + CHUNK);
    slice.forEach(([name, o], offset)=>{
      const i = rendered + offset;
      /* 用 CSS 变量取色：主题切换时 sparkline 与图标随 currentColor 自动换色 */
      const cssColor = "var(--c" + (i % 9 + 1) + ")";
      const open = F.open.has(name);
      const sec = document.createElement("div");
      sec.className = "agent-entry";
      sec.innerHTML =
        '<div class="ar' + (open ? " open" : "") + '">' +
          '<div class="ar-head" role="button" tabindex="0" aria-expanded="' + (open ? "true" : "false") + '">' +
            '<span class="ar-fold" aria-hidden="true">▶</span>' +
            '<span class="ar-rank" aria-hidden="true">' + String(i + 1).padStart(2, "0") + '</span>' +
            '<span class="ar-icon" style="color:' + cssColor + '">' + agentIcon(name) + '</span>' +
            '<span class="nm">' + esc(agentLabel(name)) + '</span>' +
            '<span class="ar-metrics">' +
              '<span><small>Tokens</small><b>' + fmtInt(o.tokens) + '</b></span>' +
              '<span><small>请求</small><b>' + fmtInt(o.requests) + '</b></span>' +
              '<span><small>金额</small><b>' + costText(o.cost, o.tokens, null, o.planTokens > 0 && o.planTokens >= o.tokens * 0.995) + '</b></span>' +
            '</span>' +
          '</div>' +
          '<div class="ar-chart">' + sparklineSVG(sparkPairs(rows.filter(r=>r.agent===name), start), cssColor) + '</div>' +
          '<div class="ar-models" id="am-' + i + '"></div>' +
        '</div>';
      box.appendChild(sec);
      const arEl = sec.querySelector(".ar");
      const arHead = arEl.querySelector(".ar-head");
      const toggleAgent = () => {
        F.open.has(name) ? F.open.delete(name) : F.open.add(name);
        renderAgentList();
      };
      arHead.onclick = toggleAgent;
      arHead.onkeydown = e => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          toggleAgent();
        }
      };

      if (open){
        const arows = rows.filter(r=>r.agent===name);
        const mm = new Map();
        for (const r of arows){
          const o2 = mm.get(r.model) || {tokens:0, cost:0, requests:0};
          o2.tokens += r.tokens; o2.cost += r.cost; o2.requests += r.requests;
          mm.set(r.model, o2);
        }
        const mlist = [...mm.entries()].sort((a,b)=>b[1].tokens-a[1].tokens);
        const boxM = arEl.querySelector(".ar-models");
        if (!mlist.length) boxM.innerHTML = '<div class="empty">该数据源在当前筛选下没有模型明细</div>';
        mlist.forEach(([mname, o2])=>{
          const row = document.createElement("div");
          row.className = "mrow";
          row.innerHTML =
            '<span class="nm">' + modelCellHTML(mname) + '</span>' +
            '<span class="num">Tokens <b>' + fmtInt(o2.tokens) + '</b> · ' + fmtInt(o2.requests) + ' 次 · ' + costText(o2.cost, o2.tokens, mname) + '</span>' +
            '<div class="ch">' + sparklineSVG(sparkPairs(arows.filter(r=>r.model===mname), start), cssColor) + '</div>';
          boxM.appendChild(row);
        });
      }
    });
    rendered += slice.length;
    if (rendered < list.length){
      const more = document.createElement("button");
      more.type = "button";
      more.className = "btn btn-sm agent-more";
      more.textContent = "继续显示剩余 " + (list.length - rendered) + " 个数据源";
      more.onclick = function(){ more.remove(); renderChunk(); };
      box.appendChild(more);
    }
  }
  renderChunk();
}

/* ---------- 表格视图 ---------- */
function barCell(v, max, color){
  return `<td class="bar-cell"><div class="bar"><i style="width:${max?Math.max(v/max*100,1):0}%;background:${color}"></i></div></td>`;
}
/* 表格排序状态：默认按 Token 降序（口径：Token 是主口径） */
const SORT = { key: "tokens", dir: -1 };
function sortValue(item, key){
  const [, o] = item;
  if (key === "model") return String(item[0]).toLowerCase();
  if (key === "avg") return o.tokens ? o.cost * DATA.cny_rate / o.tokens * 1e6 : -1;
  return o[key] || 0;
}
function renderModelTable(){
  const rows = rowsFor(true);
  const agg = new Map();
  for (const r of rows){
    const o = agg.get(r.model) || {tokens:0, cost:0, requests:0};
    o.tokens += r.tokens; o.cost += r.cost; o.requests += r.requests;
    agg.set(r.model, o);
  }
  let list = [...agg.entries()];
  /* 顶部汇总始终反映"当前筛选的全部模型"，与分页/搜索/计费筛选无关 */
  const totalTokens = list.reduce((s,x)=>s+x[1].tokens,0);
  const totalCost = list.reduce((s,x)=>s+x[1].cost,0);
  $("msTokens").textContent = fmtInt(totalTokens);
  $("msModels").textContent = fmtInt(list.length);
  const costEl = $("msCost");
  costEl.textContent = totalCost > 0 ? fmtCNY(totalCost * DATA.cny_rate)
    : (totalTokens > 0 ? "套餐/未计价" : fmtCNY(0));
  costEl.title = totalCost > 0 ? "按当前价表估算，仅供参考"
    : "当前模型属于套餐/订阅制（只记用量不计金额），或单价不在价格库中";

  /* 本地搜索与计费筛选：只影响表格行，不改变 KPI 与图表口径 */
  const query = (PAGE.query || "").trim().toLowerCase();
  let filtered = query ? list.filter(([name]) => String(name).toLowerCase().includes(query)) : list;
  if (F.billing && F.billing !== "all") {
    const planSet = window.PLAN_SET || new Set();
    filtered = filtered.filter(([name, o]) => {
      const plan = planSet.has(String(name).toLowerCase());
      if (F.billing === "plan") return plan;
      if (F.billing === "unpriced") return !plan && o.tokens > 0 && o.cost <= 0;
      return !plan && o.cost > 0;                      /* metered：按量计费 */
    });
  }
  filtered.sort((a, b) => {
    const av = sortValue(a, SORT.key), bv = sortValue(b, SORT.key);
    if (typeof av === "string" || typeof bv === "string") return String(av).localeCompare(String(bv), "zh-CN") * SORT.dir;
    return (av - bv) * SORT.dir;
  });
  list = filtered;

  const size = PAGE.size > 0 ? PAGE.size : list.length || 1;
  const pages = Math.max(1, Math.ceil(list.length / size));
  if (PAGE.index > pages - 1) PAGE.index = pages - 1;
  if (PAGE.index < 0) PAGE.index = 0;
  const start = PAGE.size > 0 ? PAGE.index * size : 0;
  const view = PAGE.size > 0 ? list.slice(start, start + size) : list;
  const max = list.length ? Math.max(...list.map(x => x[1].tokens), 1) : 1;

  const body = $("tbModel");
  if (!list.length){
    body.innerHTML = '<tr><td colspan="6" class="empty">'
      + (query
          ? '没有名称包含「' + esc(query) + '」的模型'
          : F.billing && F.billing !== "all"
            ? '当前计费类型下没有模型（试试切回「全部」）'
            : '当前筛选下没有模型数据')
      + '</td></tr>';
  } else {
    /* data-label 供窄屏"卡片化"降级使用（CSS ::before 显示字段名） */
    body.innerHTML = view.map(([name,o],i)=>{
      const avg = o.tokens ? o.cost*DATA.cny_rate/o.tokens*1e6 : 0;
      const rank = start + i;
      return `<tr><td class="mono" data-label="模型"><span class="m-ico">${modelIcon(name)}</span>${modelCellHTML(name)}</td>
      <td class="num" data-label="Tokens">${fmtInt(o.tokens)}</td><td class="num" data-label="请求次数">${fmtInt(o.requests)}</td>
      ${barCell(o.tokens,max,rank<3?"var(--m-token)":"var(--line-strong)")}
      <td class="num" data-label="金额（估算）">${costText(o.cost, o.tokens, name)}</td>
      <td class="num" data-label="均价（¥/百万 tok）">${avg ? "¥"+avg.toFixed(2) : '<span class="muted">价格未知</span>'}</td>
      </tr>`;
    }).join("");
  }

  const countEl = $("modelTableCount");
  if (countEl){
    const scope = (F.billing && F.billing !== "all") ? " · 计费筛选后" : "";
    countEl.textContent = query
      ? "匹配 " + fmtInt(list.length) + " / " + fmtInt(agg.size) + " 个模型"
      : fmtInt(agg.size) + " 个模型" + scope + (PAGE.size > 0 && list.length > size ? " · 第 " + (PAGE.index + 1) + "/" + pages + " 页" : "");
  }
  renderPager(pages, list.length);
  renderTableHead();
}

/* 表头：可排序，点一下切换升降序 */
function renderTableHead(){
  const table = $("modelTable");
  if (!table) return;
  const labels = [["model","模型"],["tokens","Tokens"],["requests","请求次数"],["share","占比（Token）"],["cost","金额（估算）"],["avg","均价（¥/百万 tok）"]];
  const head = table.querySelector("thead tr");
  if (!head) return;
  head.innerHTML = labels.map(([key, label])=>{
    if (key === "share") return '<th scope="col" class="bar-col">' + label + "</th>";
    const on = SORT.key === key;
    const dir = on ? (SORT.dir === 1 ? "ascending" : "descending") : "none";
    return '<th scope="col" class="' + (key === "model" ? "" : "num") + '">'
      + '<button type="button" class="th-sort' + (on ? " on" : "") + '" data-sort="' + key + '" aria-sort="' + dir + '">'
      + esc(label)
      + '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" aria-hidden="true">'
      + '<path d="M6 2.5v7M3.5 7 6 9.5 8.5 7"/></svg>'
      + "</button></th>";
  }).join("");
  head.querySelectorAll("[data-sort]").forEach(button=>{
    button.onclick = () => {
      const key = button.dataset.sort;
      if (SORT.key === key) SORT.dir = -SORT.dir;
      else { SORT.key = key; SORT.dir = key === "model" ? 1 : -1; }
      PAGE.index = 0;
      renderModelTable();
    };
  });
}

/* 分页控件：首页/上一页/页码（省略号）/下一页/末页 */
function renderPager(pages, total){
  const box = $("modelPager");
  if (!box) return;
  if (PAGE.size <= 0 || pages <= 1){ box.innerHTML = ""; return; }
  const current = PAGE.index;
  const nums = [];
  for (let i = 0; i < pages; i++){
    if (i === 0 || i === pages - 1 || Math.abs(i - current) <= 1) nums.push(i);
    else if (nums[nums.length - 1] !== "…") nums.push("…");
  }
  const button = (label, page, opts) => {
    const attrs = [];
    if (opts && opts.current) attrs.push('aria-current="page"');
    if (opts && opts.disabled) attrs.push("disabled");
    if (opts && opts.aria) attrs.push('aria-label="' + opts.aria + '"');
    return '<button type="button" data-page="' + page + '" ' + attrs.join(" ") + ">" + label + "</button>";
  };
  box.innerHTML = '<span class="pager-info">共 ' + fmtInt(total) + ' 行</span>'
    + button("上一页", current - 1, { disabled: current === 0, aria: "上一页" })
    + nums.map(n => n === "…" ? '<button type="button" disabled aria-hidden="true">…</button>'
      : button(String(n + 1), n, { current: n === current, aria: "第 " + (n + 1) + " 页" })).join("")
    + button("下一页", current + 1, { disabled: current >= pages - 1, aria: "下一页" });
  box.querySelectorAll("button[data-page]").forEach(el=>{
    el.onclick = () => {
      const page = parseInt(el.dataset.page, 10);
      if (Number.isNaN(page) || page === PAGE.index) return;
      PAGE.index = Math.min(Math.max(page, 0), pages - 1);
      renderModelTable();
      const card = document.querySelector("#view-models .table-card");
      if (card) card.scrollIntoView({ block: "nearest", behavior: "smooth" });
    };
  });
}
