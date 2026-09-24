/* ---------- 图表公共样式 ---------- */
const TT = { backgroundColor:"#FFFFFF", borderColor:"#DDE3EA", borderWidth:1,
  titleColor:"#151A20", bodyColor:"#5F6B78", padding:13, cornerRadius:8,
  displayColors:true, usePointStyle:true, boxWidth:8, boxHeight:8, boxPadding:4,
  bodySpacing:6, titleSpacing:6, titleMarginBottom:8 };
/* hover 竖直参考线（对齐 DeepSeek） */
const crosshair = { id: "crosshair",
  afterDatasetsDraw(c){
    const a = c.tooltip && c.tooltip._active;
    if (!a || !a.length) return;
    const x = a[0].element.x, ctx = c.ctx, top = c.chartArea.top, bot = c.chartArea.bottom;
    ctx.save();
    ctx.strokeStyle = "rgba(21,26,32,.18)";
    ctx.lineWidth = 1; ctx.setLineDash([4,4]);
    ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bot); ctx.stroke();
    ctx.restore();
  } };
function baseOpts(fmt, legend){
  return { responsive:true, maintainAspectRatio:false,
    animation:{ duration:360, easing:"easeOutQuart" },
    interaction:{ mode:"index", intersect:false },
    plugins:{ legend:{display:false},
      tooltip:{ ...TT, filter: i => i.parsed.y !== 0,
        callbacks:{ label:c => " " + fmt(c.parsed.y) } } },
    scales:{
      x:{ stacked:true, ticks:{ color:"#76818E", font:{family:"Inter, Segoe UI, system-ui", size:10.5, weight:"500"}, maxRotation:0, autoSkip:true, maxTicksLimit:10 },
          grid:{ display:false }, border:{ color:"#E3E8ED" } },
      y:{ stacked:true, beginAtZero:true, ticks:{ color:"#76818E", font:{family:"Inter, Segoe UI, system-ui", size:10.5, weight:"500"}, maxTicksLimit:6, callback:fmt },
          grid:{ color:"rgba(21,26,32,.055)" }, border:{ display:false } } } };
}
const fmtTick = {
  cost: v => "¥" + (v>=1e4 ? (v/1e4).toFixed(1)+"k" : v.toFixed(0)),
  tokens: v => v>=1e9 ? (v/1e9).toFixed(1)+"B" : v>=1e6 ? (v/1e6).toFixed(0)+"M" : v>=1e3 ? (v/1e3).toFixed(0)+"k" : v,
  requests: v => v>=1e3 ? (v/1e3).toFixed(1)+"k" : v
};
