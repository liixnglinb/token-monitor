/* ---------- 格式化 ---------- */
const fmtInt = n => Math.round(n).toLocaleString("en-US");
const fmtTok = n => n >= 1e9 ? (n/1e9).toFixed(2)+" B" : n >= 1e6 ? (n/1e6).toFixed(1)+" M"
  : n >= 1e3 ? (n/1e3).toFixed(1)+" k" : String(Math.round(n));
const fmtCNY = n => "¥" + n.toLocaleString("en-US",{minimumFractionDigits:2, maximumFractionDigits:2});
const fmtUSD = n => "$" + n.toLocaleString("en-US",{minimumFractionDigits:2, maximumFractionDigits:2});
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

/* ---------- 工具 ---------- */
const ymd = d => d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")+"-"+String(d.getDate()).padStart(2,"0");
const md  = s => { const [,m,d] = s.split("-"); return String(+m)+"/"+String(+d); };   // 2026-09-16 → 9/16
/* 月份 key（2026-09）→ 图表显示用：同年显示 "9月"，跨年显示 "2025年12月"（保留完整 key 用于排序/tooltip 取数，不动原始数据） */
const fmtMonth = s => {
  const m = /^(\d{4})-(\d{2})$/.exec(s);
  if (!m) return s;                       // 非月份 key（如 2026-09-16）原样返回
  const y = +m[1], mm = String(+m[2]);
  return y === new Date().getFullYear() ? mm + "月" : y + "年" + mm + "月";
};
const addDays = (s, n) => { const d = new Date(s+"T00:00:00"); d.setDate(d.getDate()+n); return ymd(d); };
/* 各时间粒度 → [start, end]；全部返回 null */
function rangeDates(){
  const max = DATA.range.max || ymd(new Date());
  const now = new Date(), today = ymd(now);
  switch (F.rangeKey){
    case "today":     return [today, today];
    case "yesterday": return [addDays(today,-1), addDays(today,-1)];
    case "last7":     return [addDays(max,-6), max];
    case "last30":    return [addDays(max,-29), max];
    case "last90":    return [addDays(max,-89), max];
    case "thismonth": return [ymd(new Date(now.getFullYear(), now.getMonth(), 1)), today];
    case "lastmonth": return [ymd(new Date(now.getFullYear(), now.getMonth()-1, 1)),
                              ymd(new Date(now.getFullYear(), now.getMonth(), 0))];
    default:          return null;
  }
}
/* 填充连续日期轴：无数据的日期补 0，与 DeepSeek 一致 */
function fillDays(pairs, start){
  if (!DATA.range.min || !DATA.range.max) return pairs;
  const map = new Map(pairs);
  const out = [];
  const s = start || DATA.range.min;
  const e = DATA.range.max;
  if (s > e) return pairs;
  for (let d = new Date(s+"T00:00:00"); d <= new Date(e+"T00:00:00"); d.setDate(d.getDate()+1))
    out.push([ymd(d), map.get(ymd(d)) || 0]);
  return out;
}
function rowsFor(keepUnknown){
  const range = rangeDates();
  return DATA.matrix.filter(r => {
    if (F.agent !== "all" && r.agent !== F.agent) return false;
    if (range){
      if (r.date === "unknown") return !!keepUnknown;
      if (r.date < range[0] || r.date > range[1]) return false;
    }
    return true;
  });
}
const cellVal = (r, m) => m === "cost" ? r.cost : m === "tokens" ? r.tokens : r.requests;

function groupSeries(rows, metric, grain){
  const map = new Map();
  for (const r of rows){
    if (r.date === "unknown") continue;
    const k = grain === "month" ? r.date.slice(0,7) : r.date;
    map.set(k, (map.get(k)||0) + cellVal(r, metric));
  }
  return [...map.entries()].sort((a,b)=>a[0]<b[0]?-1:1);
}
