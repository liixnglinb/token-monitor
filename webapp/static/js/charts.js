/* ---------- 图表公共样式 ---------- */
/* 取色一律走 tokens.css 的变量：主题切换（深浅）后图表自动跟着变。
   Chart.js 不认 var()，所以在渲染那一刻用 getComputedStyle 解析成真实色值。 */
function cssVar(name, fallback){
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback || "#888888";
}
const PAL_FALLBACK = ["#6C9BFF","#4FC3A1","#E8B45B","#F0737A","#9B92F0","#5CC8DE","#E08B5C","#8FA0C4","#B9C0CA"];
const palette = () => [1,2,3,4,5,6,7,8,9].map((i) => cssVar("--c" + i, PAL_FALLBACK[i - 1]));

/* 图表用色上下文：每次重绘取一份，避免主题切换后仍残留旧配色 */
function chartTheme(){
  const theme = {
    surface: cssVar("--surface-2", "#161B22"),
    line: cssVar("--line", "rgba(255,255,255,.14)"),
    lineStrong: cssVar("--line-strong", "rgba(255,255,255,.22)"),
    ink: cssVar("--ink", "#EEEEE7"),
    text: cssVar("--text", "#CBCCC2"),
    muted: cssVar("--muted", "#A7A99E"),
    grid: cssVar("--line-soft", "rgba(255,255,255,.06)"),
    palette: palette(),
  };
  theme.tooltip = {
    backgroundColor: theme.surface,
    borderColor: theme.lineStrong,
    borderWidth: 1,
    titleColor: theme.ink,
    bodyColor: theme.text,
    padding: 13,
    cornerRadius: 8,
    displayColors: true,
    usePointStyle: true,
    boxWidth: 8,
    boxHeight: 8,
    boxPadding: 4,
    bodySpacing: 6,
    titleSpacing: 6,
    titleMarginBottom: 8,
  };
  return theme;
}
/* TT 是历史调用点用的全局；每次进入渲染前由 refreshChartTokens() 刷新 */
let TT = chartTheme().tooltip;
function refreshChartTokens(){
  const theme = chartTheme();
  TT = theme.tooltip;
  return theme;
}
/* hover 竖直参考线（对齐 DeepSeek）+ 被钉住那一天的实线标记 */
const crosshair = { id: "crosshair",
  afterDatasetsDraw(c){
    const ctx = c.ctx, top = c.chartArea.top, bot = c.chartArea.bottom;
    /* 钉住标记先画，hover 虚线压在它上面：鼠标动的时候不该把"你钉了哪天"盖掉 */
    const day = (typeof F !== "undefined" && F.day) ? String(F.day) : null;
    if (day){
      const i = (c.data.labels || []).findIndex(l => String(l) === day);
      if (i >= 0){
        const x = c.scales.x.getPixelForValue(i);
        ctx.save();
        ctx.strokeStyle = cssVar("--brand-strong", "#6C9BFF");
        ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bot); ctx.stroke();
        ctx.fillStyle = cssVar("--brand-strong", "#6C9BFF");
        ctx.fillRect(x - 2.5, top - 1, 5, 5);
        ctx.restore();
      }
    }
    const a = c.tooltip && c.tooltip._active;
    if (!a || !a.length) return;
    const x = a[0].element.x;
    ctx.save();
    ctx.strokeStyle = cssVar("--line-strong", "rgba(255,255,255,.22)");
    ctx.lineWidth = 1; ctx.setLineDash([4,4]);
    ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bot); ctx.stroke();
    ctx.restore();
  } };
function baseOpts(fmt, legend){
  const theme = refreshChartTokens();
  return { responsive:true, maintainAspectRatio:false,
    animation:matchMedia('(prefers-reduced-motion: reduce)').matches ? false : { duration:200, easing:"easeOutQuart" },
    interaction:{ mode:"index", intersect:false },
    plugins:{ legend:{display:false},
      tooltip:{ ...theme.tooltip, filter: i => i.parsed.y !== 0,
        callbacks:{ label:c => " " + fmt(c.parsed.y) } } },
    scales:{
      x:{ stacked:true, ticks:{ color:theme.muted, font:{family:"Segoe UI, Microsoft YaHei UI, system-ui", size:12, weight:"500"}, maxRotation:0, autoSkip:true, maxTicksLimit:10 },
          grid:{ display:false }, border:{ color:theme.line } },
      y:{ stacked:true, beginAtZero:true, ticks:{ color:theme.muted, font:{family:"Segoe UI, Microsoft YaHei UI, system-ui", size:12, weight:"500"}, maxTicksLimit:6, callback:fmt },
          grid:{ color:theme.grid }, border:{ display:false } } } };
}
const fmtTick = {
  cost: v => "¥" + (v>=1e4 ? (v/1e4).toFixed(1)+"k" : v.toFixed(0)),
  tokens: v => v>=1e9 ? (v/1e9).toFixed(1)+"B" : v>=1e6 ? (v/1e6).toFixed(0)+"M" : v>=1e3 ? (v/1e3).toFixed(0)+"k" : v,
  requests: v => v>=1e3 ? (v/1e3).toFixed(1)+"k" : v
};
