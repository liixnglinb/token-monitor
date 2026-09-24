/* ---------- 主流程 ---------- */
function renderAll(){
  /* 首扫期间 /api/summary 返回 building 占位（无 range/matrix），此时不渲染也不报错，
     等后台扫描完成后 pollMeta 会拉到真数据再走一遍这里 */
  if (!DATA || DATA.building || !(DATA.range && DATA.range.max)) return;
  /* 套餐模型集合先行设置：renderAgentList / renderModelDist 都要用它区分「套餐」与「缺价」 */
  window.PLAN_SET = new Set(((DATA.kpi_all && DATA.kpi_all.plan_models) || [])
    .map(x => String(x).toLowerCase()));
  renderSideAgents();
  renderRangeMenu();
  renderKPI(); renderMain(); renderAgentList();
  renderModelDist(); renderModelTable(); renderNote(); renderScanInfo();
}

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
  const wrap = $("sideAgents");
  if (!wrap || !DATA || !Array.isArray(DATA.agents)) return;
  const allBtn = document.querySelector('[data-agent-filter="all"]');
  if (allBtn) allBtn.classList.toggle("active", F.agent === "all");
  $("sideAgentTotal").textContent = String(DATA.agents.length);
  wrap.innerHTML = DATA.agents.slice(0, 6).map(a => {
    const name = String(a.name);
    const active = F.agent === name;
    return '<button class="side-project' + (active ? ' active' : '') + '" type="button" data-agent-filter="' + esc(name) + '" title="' + esc(agentLabel(name)) + '">'
      + '<span class="side-project-icon">' + agentIcon(name) + '</span>'
      + '<span class="side-project-name">' + esc(agentLabel(name)) + '</span>'
      + '<em>' + esc(fmtTok(a.tokens)) + '</em></button>';
  }).join("");
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


function renderKPI(){
  const rows = rowsFor(true);                       // KPI 含日期未知行
  const tokens = rows.reduce((s,r)=>s+r.tokens,0);
  const req = rows.reduce((s,r)=>s+r.requests,0);
  const cost = rows.reduce((s,r)=>s+r.cost,0);
  const cr = rows.reduce((s,r)=>s+r.cr,0);
  const base = rows.reduce((s,r)=>s+r.inp+r.cw+r.cr,0);
  const planTokens = rows.reduce((s,r)=>s+((window.PLAN_SET||new Set()).has(String(r.model).toLowerCase()) ? r.tokens : 0),0);

  $("kCost").textContent = fmtCNY(cost * DATA.cny_rate);
  if (cost === 0 && tokens > 0){
    const costSub = $("kCostSub");
    costSub.textContent = planTokens >= tokens * 0.995
      ? "套餐用量"
      : (planTokens > 0 ? "套餐 + 未知价格" : "价格未知");
    costSub.title = planTokens >= tokens * 0.995
      ? "套餐/订阅制模型只统计用量，不计金额"
      : (planTokens > 0 ? "套餐模型不计费，部分模型价格未知" : "模型单价不在价格库，未计入金额");
  } else {
    $("kCostSub").textContent = fmtUSD(cost) + " · 汇率 " + DATA.cny_rate;
  }
  $("kReq").textContent = fmtInt(req);
  const range = rangeDates();
  const days = range ? Math.round((new Date(range[1]) - new Date(range[0]))/864e5) + 1
    : (DATA.range.max && DATA.range.min
      ? Math.round((new Date(DATA.range.max) - new Date(DATA.range.min))/864e5)+1 : 0);
  $("kReqSub").textContent = days
    ? (req/days < 1 ? "日均 <1" : "日均 " + fmtInt(req/days))
    : "全部时间";
  $("kTok").textContent = fmtInt(tokens);           // 对齐 DeepSeek：完整千分位
  $("kTokSub").textContent = fmtTok(tokens);
  $("kCache").textContent = "缓存命中 " + (cr/Math.max(base,1)*100).toFixed(1) + "%";
  /* 平均单次请求（参考百炼的「平均单次请求Token」） */
  $("kAvg").textContent = req ? fmtInt(Math.round(tokens / req)) : "—";
  $("kAvgSub").textContent = req ? fmtInt(req) + " 次请求" : "无记录";
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
    box.innerHTML = '<div class="daily-empty">当前筛选下没有可展示的日期数据</div>';
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
      + '<div class="daily-meta"><span>' + fmtTok(extra.tokens) + ' tok</span><span>'
      + fmtCNY(extra.cost * DATA.cny_rate) + '</span><span>' + fmtInt(extra.requests) + ' 次</span></div>'
      + '</div>';
  }).join("");
}
function renderMain(){
  const rows = rowsFor(false);
  const range = rangeDates();
  const fmt = fmtTick[F.metric];
  const suffix = F.grain === "month" ? "（按月）" : "";
  const title = F.grain === "month"
    ? (F.metric === "tokens" ? "Tokens 趋势" : METRIC_NAME[F.metric]) + suffix
    : (F.metric === "tokens" ? "每日 Token" : F.metric === "cost" ? "每日消耗金额" : "每日请求次数");
  $("mainTitle").textContent = title;

  const raw = groupSeries(rows, F.metric, F.grain);
  const data = F.grain === "day" ? fillDays(raw, range && range[0]) : raw;
  const labels = data.map(d=>d[0]);
  const list = data.map(([label, value]) => ({ label, value }));
  const total = list.reduce((sum, item) => sum + item.value, 0);
  $("mainSum").textContent = DIM_NAME[F.dim] + " · " + metricText(total, F.metric);
  renderTrendSummary(list, F.metric);
  renderDailyDetail(rows, list, F.metric);

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
        pointHoverRadius: 5, pointBackgroundColor: "#FFFFFF",
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

/* ---------- Agent 用量榜（可折叠 + 会话明细） ---------- */
function sessionLines(date, agent, model, metric){
  /* 指定日期与维度下的对话分布（TOP 5 + 其余合计） */
  const byS = new Map();
  for (const r of DATA.matrix){
    if (r.date !== date || r.agent !== agent) continue;
    if (model && r.model !== model) continue;
    const o = byS.get(r.session) || {t:0, c:0, q:0};
    o.t += r.tokens; o.c += r.cost; o.q += r.requests;
    byS.set(r.session, o);
  }
  const list = [...byS.entries()].sort((a,b)=>b[1].t-a[1].t);
  if (!list.length) return [];
  const val = o => metric==="cost" ? fmtCNY(o.c*DATA.cny_rate)
    : metric==="tokens" ? fmtTok(o.t) : fmtInt(o.q)+" 次";
  const out = list.slice(0,5).map(([s,o]) =>
    "· " + (s==="unknown" ? "未知对话" : s) + "   " + val(o));
  if (list.length > 5) out.push("… 另有 " + (list.length-5) + " 个对话");
  return out;
}

function miniChart(canvas, pairs, color, tip){
  /* 迷你柱：每日 Token 走势；hover 显示对话分布 */
  /* 渲染前先销毁同画布上的旧实例（与 MAIN/DONUT 一致），防重复 new 造成泄漏 */
  const ex = Chart.getChart(canvas);
  if (ex) ex.destroy();
  return new Chart(canvas, { type: "bar",
    data: { labels: pairs.map(d=>d[0]),
      datasets: [{ data: pairs.map(d=>d[1]), backgroundColor: color,
        borderRadius: 2, maxBarThickness: barW(pairs.length) }] },
    options: { responsive:true, maintainAspectRatio:false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend:{display:false},
        tooltip: { ...TT, displayColors:false,
          filter: it => it.parsed.y > 0,          // 空日期不弹泡
          callbacks: { title: it => it && it.length ? md(it[0].label) : "",
            label: c => {
              /* 会话明细并入 body 多行 */
              const base = " " + fmtTok(c.parsed.y) + " tok";
              const lines = c.label ? tip(c.label) : [];
              return lines.length ? [base, ...lines] : base;
            } } },
      scales: {
        /* ⚠️ 不用顶层 display:false —— Chart.js 深合并会把它覆盖回 true，
           分别隐藏 ticks/grid/border 才可靠 */
        x: { ticks:{display:false}, grid:{display:false}, border:{display:false} },
        y: { ticks:{display:false}, grid:{display:false}, border:{display:false} }
      }
    }
  } });
}

function addMini(id, pairs, color, tip){
  const c = miniChart($(id), pairs, color, tip);
  /* Chart.js 深合并对 display:false 的覆盖有怪癖，构造后强制关闭最可靠 */
  c.options.scales.x.display = false;
  c.options.scales.y.display = false;
  c.update();
  return c;
}
/* 单点/双点时柱太细，看起来像坏图 —— 自适应放宽 */
const barW = n => n <= 2 ? 36 : n <= 5 ? 16 : 8;
/* 金额为 0 但有用量时，标注"价格未知"，避免误以为算错 */
/* 成本列文案：区分「有计价 / 套餐不计费 / 价表缺价」三态
   model       —— 模型名，用于查套餐集合（Agent 行传 null）
   forcePlan   —— Agent 行用：该 Agent 全部为套餐模型时直接标套餐 */
function costText(cost, tokens, model, forcePlan){
  if (cost > 0) return fmtCNY(cost * DATA.cny_rate);
  if (!(tokens > 0)) return fmtCNY(0);
  const set = window.PLAN_SET || new Set();
  const isPlan = !!forcePlan || !!(model && set.has(String(model).toLowerCase()));
  const tip = isPlan ? "套餐/订阅制，按口径只记用量、不计金额" : "单价不在价表中";
  const label = isPlan ? "套餐不计费" : "价格未知";
  return fmtCNY(0) + ' <span class="muted" title="' + tip + '">' + label + '</span>';
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
          borderColor: "#11171E", borderWidth: 3, hoverOffset: 7,
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
    MINIS.forEach(c=>c.destroy()); MINIS.length = 0;   // 空数据时也要清理，避免旧实例悬挂
    wrap.innerHTML = '<div class="card"><div class="empty">当前筛选下无数据</div></div>'; return;
  }

  MINIS.forEach(c=>c.destroy()); MINIS.length = 0;
  wrap.innerHTML =
    '<section class="agent-panel">' +
      '<div class="agent-panel-head">' +
        '<div><h3>Agent 用量排行</h3><p>按 Token 消耗排序</p></div>' +
        '<span class="agent-panel-count">' + fmtInt(list.length) + ' 个数据源</span>' +
      '</div>' +
      '<div id="agCards"></div>' +
    '</section>';
  const box = $("agCards");

  list.forEach(([name, o], i)=>{
    const color = PAL[i % PAL.length];
    const open = F.open.has(name);
    const sec = document.createElement("div");
    sec.className = "agent-entry";
    sec.innerHTML =
      '<div class="ar' + (open ? " open" : "") + '">' +
        '<div class="ar-head" role="button" tabindex="0" aria-expanded="' + (open ? "true" : "false") + '">' +
          '<span class="ar-fold">▶</span>' +
          '<span class="ar-rank">' + String(i + 1).padStart(2, "0") + '</span>' +
          '<span class="ar-icon" style="color:' + color + '">' + agentIcon(name) + '</span>' +
          '<span class="nm">' + esc(agentLabel(name)) + '</span>' +
          '<span class="ar-metrics">' +
            '<span><small>Tokens</small><b>' + fmtInt(o.tokens) + '</b></span>' +
            '<span><small>请求</small><b>' + fmtInt(o.requests) + '</b></span>' +
            '<span><small>成本</small><b>' + costText(o.cost, o.tokens, null, o.planTokens > 0 && o.planTokens >= o.tokens * 0.995) + '</b></span>' +
          '</span>' +
        '</div>' +
        '<div class="ar-chart"><canvas id="ac-' + i + '" role="img" aria-label="' + esc(name) + ' 每日 Token 走势"></canvas></div>' +
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

    const arows = rows.filter(r=>r.agent===name);
    const sA = fillDays(groupSeries(arows, "tokens", "day"), start);
    MINIS.push(addMini("ac-"+i, sA, color,
      d => sessionLines(d, name, null, "tokens")));

    if (open){
      const mm = new Map();
      for (const r of arows){
        const o2 = mm.get(r.model) || {tokens:0, cost:0, requests:0};
        o2.tokens += r.tokens; o2.cost += r.cost; o2.requests += r.requests;
        mm.set(r.model, o2);
      }
      const mlist = [...mm.entries()].sort((a,b)=>b[1].tokens-a[1].tokens);
      const boxM = arEl.querySelector(".ar-models");
      mlist.forEach(([mname, o2], j)=>{
        const row = document.createElement("div");
        row.className = "mrow";
        row.innerHTML =
          '<span class="nm" title="' + esc(mname) + '">' + esc(mname) + '</span>' +
          '<span class="num">Tokens <b>' + fmtInt(o2.tokens) + '</b> · ' + fmtInt(o2.requests) + ' 次 · ' + costText(o2.cost, o2.tokens, mname) + '</span>' +
          '<div class="ch"><canvas id="mc-' + i + '-' + j + '" role="img" aria-label="' + esc(mname) + ' 每日 Token 走势"></canvas></div>';
        boxM.appendChild(row);
        const mrows = arows.filter(r=>r.model===mname);
        const sM = fillDays(groupSeries(mrows, "tokens", "day"), start);
        MINIS.push(addMini("mc-"+i+"-"+j, sM, color,
          d => sessionLines(d, name, mname, "tokens")));
      });
    }
  });
}

/* ---------- 表格视图 ---------- */
function barCell(v, max, color){
  return `<td><div class="bar"><i style="width:${max?Math.max(v/max*100,1):0}%;background:${color}"></i></div></td>`;
}
function renderModelTable(){
  const rows = rowsFor(true);
  const agg = new Map();
  for (const r of rows){
    const o = agg.get(r.model) || {tokens:0, cost:0, requests:0};
    o.tokens += r.tokens; o.cost += r.cost; o.requests += r.requests;
    agg.set(r.model, o);
  }
  const list = [...agg.entries()].sort((a,b)=>b[1].cost-a[1].cost);
  const max = list.length ? Math.max(list[0][1].cost, 1e-9) : 1;
  const totalTokens = list.reduce((s,x)=>s+x[1].tokens,0);
  const totalCost = list.reduce((s,x)=>s+x[1].cost,0);
  $("msModels").textContent = fmtInt(list.length);
  $("msTokens").textContent = fmtInt(totalTokens);
  const costEl = $("msCost");
  costEl.textContent = totalCost > 0 ? fmtCNY(totalCost * DATA.cny_rate)
    : (totalTokens > 0 ? "未计价" : fmtCNY(0));
  costEl.title = totalCost > 0 ? "按当前价表估算"
    : "当前模型属于套餐/订阅制，或单价不在价格库中";
  $("tbModel").innerHTML = list.map(([name,o],i)=>{
    const avg = o.tokens ? o.cost*DATA.cny_rate/o.tokens*1e6 : 0;
    return `<tr><td class="mono">${esc(name)}</td>
    <td class="num">${fmtInt(o.tokens)}</td><td class="num">${fmtInt(o.requests)}</td>
    <td class="num">${fmtCNY(o.cost*DATA.cny_rate)}</td>
    <td class="num">${avg ? "¥"+avg.toFixed(2) : '<span class="muted">价格未知</span>'}</td>
    ${barCell(o.cost,max,i<3?"#4D6BFE":"#56565F")}</tr>`;
  }).join("") || `<tr><td colspan="6" class="empty">当前筛选下无数据</td></tr>`;
}
