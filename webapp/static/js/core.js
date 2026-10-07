"use strict";
let DATA = null, MAIN = null;
/* 后端是否正在扫描：唯一写入点是 interactions.js 的 syncSettings，
   渲染侧只读它，避免"部分结果已到位但扫描指示条还挂着"这类时序错乱。 */
let SCANNING = false;

/* ---------- 全局兜底（必须最早挂上） ----------
   界面跑在 WebView 里：未捕获异常和 Promise 拒绝默认只在开发者控制台闪过，
   用户看到的是"某块内容没出来"，事后什么线索都没有。这里把摘要送进本地服务的
   app.log（和后端同一份日志），并给一次可读提示。
   只送消息、文件名、行号 —— 不送数据内容、不送用户日志里的任何原文。 */
(function globalErrorNet(){
  const seen = new Map();            // 同一条消息 60s 内只报一次
  let shown = 0;
  function report(msg, src, line){
    const key = String(msg || "未知错误").slice(0, 300);
    const now = Date.now();
    if (now - (seen.get(key) || 0) < 60000) return;
    seen.set(key, now);
    if (seen.size > 80) seen.clear();
    try { console.error("[UI] " + key + " @ " + src + ":" + line); } catch (_) {}
    try {
      fetch("/api/client-error", {
        method: "POST", headers: { "Content-Type": "application/json" }, keepalive: true,
        body: JSON.stringify({ msg: key, src: String(src || "").slice(0, 200),
                               line: Number(line) || 0 })
      }).catch(() => {});             // 上报本身失败不能再触发一次拒绝
    } catch (_) {}
    if (shown < 2 && window.TMUI && TMUI.toast){
      shown++;
      TMUI.toast("界面有一处出了错，已记入本地日志；点顶部「刷新」可恢复", { kind: "error" });
    }
  }
  window.addEventListener("error", e => {
    const t = e && e.target;
    if (t && t !== window && t.tagName)          // 图片 / 脚本加载失败也要留痕
      report(t.tagName + " 资源加载失败: " + String(t.src || t.href || "").slice(0, 200), "asset", 0);
    else
      report(e && e.message, e && e.filename, e && e.lineno);
  }, true);
  window.addEventListener("unhandledrejection", e => {
    const r = e && e.reason;
    report((r && r.message) ? r.message : String(r).slice(0, 300), "promise", 0);
  });
  window.__TM_ERROR = report;                     // 供验收工具与人工排查调用
})();

const F = { rangeKey: "last7", agent: "all", metric: "tokens", grain: "day", dim: "total",
            billing: "all", lens: "entity", open: new Set(),
            /* 钉住的某一天/某一月（"2026-10-02" / "2026-09"）：只影响右侧排行，
               不改动趋势图与顶部 KPI 的区间口径 —— 否则整页数字会跟着变成一天，
               用户会以为统计错了。null = 未钉。 */
            day: null };
/* 视图与筛选记在 localStorage 而不是 sessionStorage：
   session 存储只在"同一次标签会话"内有效，程序整个退出重开（或崩溃后被拉起来）
   就清空 —— 界面于是回到默认视图，等于没记住用户在哪。主题一直用的是 localStorage，
   两者本来就该同一个持久度。 */
const UI_FILTER_KEY = "voyra-token-filters", UI_VIEW_KEY = "voyra-token-view";
function persistFilters(){
  try {
    localStorage.setItem(UI_FILTER_KEY, JSON.stringify({
      rangeKey: F.rangeKey, agent: F.agent, metric: F.metric, grain: F.grain,
      dim: F.dim, billing: F.billing, lens: F.lens, day: F.day,
      open: [...F.open].slice(0, 40)          /* 展开态也记住；上限防极端情况撑大 */
    }));
  } catch (_) { /* 纯 UI 状态，存不下就算了 */ }
}
try {
  const saved = JSON.parse(localStorage.getItem(UI_FILTER_KEY) || "null");
  if (saved) {
    if (["today","yesterday","last7","last30","last90","thismonth","lastmonth","all"].includes(saved.rangeKey)) F.rangeKey=saved.rangeKey;
    if (typeof saved.agent==="string" && saved.agent.length<128) F.agent=saved.agent;
    if (["cost","tokens","requests"].includes(saved.metric)) F.metric=saved.metric;
    if (["day","month"].includes(saved.grain)) F.grain=saved.grain;
    if (["total","agent","model"].includes(saved.dim)) F.dim=saved.dim;
    if (["all","metered","plan","unpriced"].includes(saved.billing)) F.billing=saved.billing;
    if (["entity","composition","cache"].includes(saved.lens)) F.lens=saved.lens;
    /* 钉住的那天：只认 YYYY-MM-DD 或 YYYY-MM，别的值一律当没存过 */
    if (typeof saved.day === "string" && /^\d{4}-\d{2}(-\d{2})?$/.test(saved.day)) F.day=saved.day;
    if (Array.isArray(saved.open)) saved.open.forEach(k => { if (typeof k === "string") F.open.add(k); });
  }
} catch { /* corrupt storage never blocks the dashboard */ }
/* 图表调色板：PAL_FALLBACK / palette() 定义在 charts.js（先加载），
   这里只负责在渲染前把 tokens.css 的 --c1..--c9 取出来。 */
let PAL = (typeof palette === "function") ? palette() : [];
function refreshPalette(){
  try {
    PAL = (typeof palette === "function") ? palette() : PAL;
  } catch (e) { /* 取色失败就沿用上一份，不影响渲染 */ }
  return PAL;
}
refreshPalette();
const METRIC_NAME = { cost: "消耗金额（CNY）", tokens: "Tokens", requests: "API 请求次数" };
const DIM_NAME = { total: "总量", agent: "数据源", model: "模型" };
const hexA = (hex, alpha) => {
  const value = parseInt(hex.slice(1), 16);
  return `rgba(${(value >> 16) & 255},${(value >> 8) & 255},${value & 255},${alpha})`;
};
function barGradient(context, index){
  const { chart } = context;
  const area = chart.chartArea;
  const color = PAL[index % PAL.length];
  if (!area) return color;
  const gradient = chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
  gradient.addColorStop(0, color);
  gradient.addColorStop(1, hexA(color, .68));
  return gradient;
}
/* 堆叠柱专用：渐变按「这一段自己的像素区间」算，而不是整根坐标轴。
   按整轴算会让靠下的段整体发灰，段与段之间看着就像隔了一层空隙。 */
function segGradient(context, color){
  const { chart, datasetIndex, dataIndex } = context;
  const c = color || PAL[datasetIndex % PAL.length];
  const el = chart.chartArea && chart.getDatasetMeta(datasetIndex).data[dataIndex];
  /* 未布局或零高度时 base === y，createLinearGradient 两点重合会画出退化渐变
     —— 那是不透明的空，整根柱子直接消失。这种情况一律退回实色。 */
  if (!el || !Number.isFinite(el.y) || !Number.isFinite(el.base) || el.base <= el.y) return c;
  const gradient = chart.ctx.createLinearGradient(0, el.y, 0, el.base);
  gradient.addColorStop(0, c);
  gradient.addColorStop(1, hexA(c, .8));
  return gradient;
}
/* 只有"该列最上面的非零段"该有圆角：每段都圆角会在段间接出缝。 */
function topSegmentMask(series){
  if (!series.length) return [];
  return series[0].data.map((_, i) => {
    for (let d = series.length - 1; d >= 0; d--) if (series[d].data[i] > 0) return d;
    return -1;
  });
}
function topRadius(mask){
  return context => context.datasetIndex === mask[context.dataIndex]
    ? { topLeft: 6, topRight: 6, bottomLeft: 0, bottomRight: 0 } : 0;
}

function lineGradient(context, color){
  const { chart } = context;
  const area = chart.chartArea;
  if (!area) return hexA(color, .2);
  const gradient = chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
  gradient.addColorStop(0, hexA(color, .42));
  gradient.addColorStop(.62, hexA(color, .13));
  gradient.addColorStop(1, hexA(color, 0));
  return gradient;
}
/* 时间粒度菜单（对齐 DeepSeek 选项） */
const RANGES = [
  ["today",     "今天"],
  ["yesterday", "昨天"],
  ["last7",     "近 7 天"],
  ["last30",    "近 30 天"],
  ["last90",    "近 90 天"],
  ["thismonth", "本月"],
  ["lastmonth", "上月"],
  ["all",       "全部"],
];
const RANGE_LABEL = Object.fromEntries(RANGES);
/* Agent 软件图标（内联 SVG，24×24，继承 currentColor） */
const AGENT_ICONS = {
  "claude-code": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M12 2.8v5.4M12 15.8v5.4M2.8 12h5.4M15.8 12h5.4M5.5 5.5l3.8 3.8M14.7 14.7l3.8 3.8M18.5 5.5l-3.8 3.8M9.3 14.7L5.5 18.5"/></svg>',
  "codex": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"><path d="M12 2.6l7.6 4.4v8.8L12 20.2l-7.6-4.4V7z"/><path d="M12 8.1l3.8 2.2v4.4L12 16.9l-3.8-2.2v-4.4z"/></svg>',
  "zcode": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M6 5h12L9 12h9l-9 7"/></svg>',
  "opencode": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6.5l-5.5 5.5L9 17.5M15 6.5l5.5 5.5L15 17.5"/></svg>',
  "hermes": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M2.6 8.2c3.6-3.2 7.2-3.2 9.4 0 2.2-3.2 5.8-3.2 9.4 0-1.9 6.2-5 10.2-9.4 13.2-4.4-3-7.5-7-9.4-13.2z"/><path d="M12 8.4v9.6"/></svg>',
  "mhagent": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="3.8" y="3.8" width="16.4" height="16.4" rx="3.4"/><path d="M8.6 16.4V8.4l3.4 4.4 3.4-4.4v8"/></svg>',
  "openclaw-autoclaw": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21.2c-3.1 0-5.2-1.4-5.2-3.4 0-1.5 1.3-2.4 2.7-2.7M12 21.2c3.1 0 5.2-1.4 5.2-3.4 0-1.5-1.3-2.4-2.7-2.7"/><path d="M7.4 6.4c0-2.1 2-3.6 4.6-3.6s4.6 1.5 4.6 3.6"/><path d="M7.9 11.6V9M12 11.2V8.4M16.1 11.6V9"/></svg>',
  "agnes": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><circle cx="12" cy="12" r="8.6"/><path d="M8.3 16.3l3.7-9.2 3.7 9.2M9.7 13.4h4.6"/></svg>',
  "dsh": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3.6 6.2h7.2M3.6 12h11.4M3.6 17.8h5.6"/><path d="M17.4 5.2l3.4 13.6"/></svg>',
  "workbuddy-ai": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3.4" y="6.6" width="17.2" height="12.4" rx="3.4"/><path d="M12 3.2v3.4M8.6 12.2h6.8M8.6 15.6h4.2"/></svg>',
};
const AGENT_NAME = {
  "claude-code":"Claude Code", "codex":"Codex", "zcode":"ZCode",
  "opencode":"OpenCode", "hermes":"Hermes", "mhagent":"MHAgent",
  "openclaw":"OpenClaw", "openclaw-autoclaw":"OpenClaw AutoClaw",
  "agnes":"Agnes", "agnes-ledger":"Agnes Ledger", "dsh":"DSH",
  "cline":"Cline", "box-agent":"Box Agent", "mavis":"Mavis",
  "workbuddy":"WorkBuddy", "workbuddy-ai":"WorkBuddy AI",
  "workbuddy-legacy":"WorkBuddy 旧版",
  "codebuddy":"腾讯 CodeBuddy", "yumbo":"腾讯元宝", "ima":"腾讯 IMA",
  "tongyi-lingma":"通义灵码", "qoder":"Qoder", "qwen-cli":"通义千问 CLI",
  "trae":"TRAE", "trae-solo":"TRAE Solo", "doubao":"豆包",
  "ark":"火山方舟", "comate":"Baidu Comate", "iflycode":"讯飞 iFlyCode",
  "codearts":"华为 CodeArts", "codefuse":"CodeFuse", "zhipu-codegeex":"CodeGeeX",
  "cherrystudio":"Cherry Studio", "kimi":"Kimi", "minimax":"MiniMax",
  "sensenova":"商汤 Sensenova", "meituan-catpaw-models":"美团 CatPaw",
  "gemini-cli":"Gemini CLI", "windsurf":"Windsurf", "cursor":"Cursor",
  "copilot-chat":"GitHub Copilot", "copilot-cli":"GitHub Copilot CLI",
  "amazon-q":"Amazon Q", "junie":"Junie", "kiro":"Kiro", "zed":"Zed",
  "warp":"Warp", "goose":"Goose", "crush":"Crush", "opencode-atlantis":"OpenCode Atlantis",
  "opencode-review":"OpenCode Review", "roo-code":"Roo Code", "kilo-code":"Kilo Code",
  "aider":"Aider", "amp":"Amp", "augment":"Augment", "continue":"Continue",
  "crush-codebuff":"CodeBuff", "codebuff":"CodeBuff", "devin":"Devin",
  "droid":"Factory Droid", "command-code":"Command Code", "grok-build":"Grok Build",
  "lmstudio":"LM Studio", "lark-cli":"飞书 Lark", "cc-switch":"CC Switch",
  "cc-switch-data":"CC Switch 数据", "tokscale":"TokScale", "mha-agent":"MHA Agent",
  "mimo":"Xiaomi MiMo", "modex":"Modex", "mux":"Mux", "pi":"Pi", "prime":"Prime",
  "reasonix":"Reasonix", "unsloth":"Unsloth", "jcode":"JCode",
  "goofish-cli":"闲鱼 CLI", "mimosa":"Mimosa", "openviking":"OpenViking",
  "raccoonwork":"RaccoonWork", "codex-session-delete":"Codex 会话清理",
  "unknown":"未知来源",
};
const AGENT_LOGOS = {
  "codex":"codex.png", "claude-code":"claude.svg",
  "opencode":"opencode.svg", "cline":"cline.svg",
  /* 2026-09-27：以下均为从本机各应用安装目录提取的真实品牌图（256px 归一） */
  "zcode":"zcode.png", "hermes":"hermes.png", "workbuddy":"workbuddy.png",
  "workbuddy-ai":"workbuddy.png", "dsh":"dsh.png", "catpaw":"catpaw.png",
  "kimi":"kimi.png",
  /* 2026-09-29：MHAgent 官方应用图标（从 %APPDATA%/MHAgent 的 ico 提取 256px） */
  "mhagent":"mhagent.png",
  /* 2026-10-05：从本机各应用安装体（icon.ico / 安装包 PE 资源 / MSIX app.asar）
     提取的官方图。此前 Codex 错误地复用 OpenAI 的 knot 标志，现已换成 Codex 自己的。 */
  "doubao":"doubao.png", "qwen-cli":"qianwen.png", "yumbo":"yuanbao.png",
  /* 2026-10-07：Qoder CN 第一次能被扫到，顺手补上官方应用图标
     （取自本机 %APPDATA%/com.qodercn.app.stable/application-icons 的当前 ico，256px 归一） */
  "qoder":"qoder.png",
};
/* 需要浅色底衬的 logo：这几张官方素材是纯深色单色实心路径（#111827 / #0F172A），
   直接落在深色面板上等于隐形。按同一标准登记，别顺手给彩色 logo 也加瓷砖。 */
const LOGO_ON_PLATE = new Set(["openai.svg", "opencode.svg", "qoder.png"]);
function brandImg(file){
  return '<img class="agent-brand-img' + (LOGO_ON_PLATE.has(file) ? " plate" : "")
    + '" src="/static/logos/' + file + '" alt="" loading="lazy" decoding="async">';
}
/* 本机确实拿不到品牌图的应用 → 字母徽标（比通用图形更像"它们自己"） */
const AGENT_MONO = {
  "box-agent": ["B", "#7C8CF8"], "mhagent": ["MH", "#4AC08A"],
  "mavis": ["M", "#E8B45B"], "agnes": ["A", "#A78BFA"],
  "agnes-ledger": ["AL", "#A78BFA"],
  "qoder": ["Q", "#5CC8DE"], "trae-solo": ["TS", "#F0737A"], "trae": ["T", "#F0737A"],
  "cursor": ["C", "#9AA1AC"],
  "cherrystudio": ["CH", "#E8834B"],
  "copilot-chat": ["GH", "#9AA1AC"], "copilot-cli": ["GH", "#9AA1AC"],
  "goofish-cli": ["闲", "#E8B45B"], "mimosa": ["M", "#E0607A"],
  "openviking": ["OV", "#5CC8DE"], "raccoonwork": ["R", "#4AC08A"],
  "codebuddy": ["CB", "#3E7BFA"], "ima": ["IM", "#3E7BFA"],
  "tongyi-lingma": ["通", "#6C5CE7"], "ark": ["方", "#3C74F6"],
  "comate": ["Co", "#E0607A"], "iflycode": ["iF", "#3B82F6"],
  "codearts": ["CA", "#5C8AF5"], "codefuse": ["CF", "#4AC08A"],
  "zhipu-codegeex": ["CG", "#3859FF"], "minimax": ["MM", "#F23F5D"],
  "sensenova": ["SN", "#E8531F"], "meituan-catpaw-models": ["猫", "#FFC300"],
  "gemini-cli": ["GE", "#4285F4"], "windsurf": ["W", "#26B787"],
  "amazon-q": ["Q", "#FF9900"], "junie": ["J", "#E08B5C"],
  "kiro": ["K", "#FF9900"], "zed": ["Z", "#E0607A"], "warp": ["W", "#B49BF8"],
  "goose": ["G", "#4FC3A1"], "crush": ["C", "#F0737A"], "codebuff": ["CB", "#F0737A"],
  "roo-code": ["R", "#E8724C"], "kilo-code": ["KL", "#5CC8DE"],
  "aider": ["A", "#E8B45B"], "amp": ["A", "#A78BFA"], "augment": ["Au", "#4AC08A"],
  "continue": ["C", "#26B787"], "devin": ["D", "#5C8AF5"],
  "droid": ["Dr", "#9B92F0"], "command-code": ["CC", "#E8B45B"],
  "grok-build": ["GK", "#8A8F98"], "lmstudio": ["LM", "#7C8CF8"],
  "lark-cli": ["飞", "#26B787"], "cc-switch": ["CS", "#8A93A8"],
  "cc-switch-data": ["CS", "#8A93A8"], "tokscale": ["TS", "#5CC8DE"],
  "mha-agent": ["MHA", "#4AC08A"], "mimo": ["Mi", "#E08B5C"],
  "modex": ["MX", "#9AA1AC"], "mux": ["MX", "#A78BFA"], "pi": ["Pi", "#5CC8DE"],
  "prime": ["P", "#E8B45B"], "reasonix": ["Rx", "#9B92F0"],
  "unsloth": ["U", "#E0C05A"], "jcode": ["JC", "#5CC8DE"],
  "openclaw": ["OC", "#F0737A"], "openclaw-autoclaw": ["OC", "#F0737A"],
  "workbuddy-legacy": ["WB", "#3E7BFA"],
  "codex-session-delete": ["CD", "#9AA1AC"],
  "opencode-atlantis": ["OA", "#5CC8DE"], "opencode-review": ["OR", "#5CC8DE"],
};
/* 未登记软件的兜底：从名称派生字母徽标 + 稳定配色（同一软件永远同色）。
   中文名取首字，拉丁名取前两个字母；颜色由名称哈希落在扩展调色板上。 */
const _MONO_PAL = ["#6C9BFF","#4FC3A1","#E8B45B","#F0737A","#9B92F0",
  "#5CC8DE","#E08B5C","#A78BFA","#26B787","#E0607A","#B49BF8","#8A93A8"];
function monoFor(name){
  const label = agentLabel(name) || String(name || "?");
  const latin = label.replace(/[^A-Za-z0-9]/g, "");
  let h = 0;
  for (let i = 0; i < label.length; i++) h = (h * 31 + label.charCodeAt(i)) >>> 0;
  const color = _MONO_PAL[h % _MONO_PAL.length];
  const tag = /^[一-鿿]/.test(label) ? label[0]
    : (latin.slice(0, 2).toUpperCase() || label.slice(0, 2) || "?");
  return [tag, color];
}
function agentIcon(name){
  const logo = AGENT_LOGOS[name];
  if (logo) return brandImg(logo);
  const mono = AGENT_MONO[name] || monoFor(name);
  return '<span class="agent-mono" style="--mc:' + mono[1] + '">' + esc(mono[0]) + '</span>';
}
const agentLabel = name => AGENT_NAME[name] || name;
const agentHasIcon = name => !!(AGENT_LOGOS[name] || AGENT_MONO[name] || AGENT_ICONS[name]);

/* 模型厂商识别：模型名 → 官方品牌图 / 品牌色徽标。
   有本机已验证的官方素材就走 img，其余用厂商品牌色字母徽标，
   与侧栏数据源的 mono 徽标同一套视觉语言。 */
const MODEL_VENDOR = [
  [/^(gpt|o[134](-| |$)|codex|davinci|chatgpt|omni)/, ["openai", "openai.svg"]],
  [/^claude/, ["claude", "claude.svg"]],
  [/^(kimi|moonshot)/, ["kimi", "kimi.png"]],
  [/^deepseek/, ["deepseek", ["DS", "#4D6BFE"]]],
  [/^(glm|zhipu|chatglm)/, ["zhipu", ["GL", "#3859FF"]]],
  [/^(qwen|qwq|qvq)/, ["qwen", ["QW", "#6236FF"]]],
  [/^(doubao|ark-)/, ["doubao", ["DB", "#3C74F6"]]],
  [/^ernie/, ["baidu", ["EB", "#2932E1"]]],
  [/^hunyuan/, ["tencent", ["HY", "#0052D9"]]],
  [/^(minimax|abab)/, ["minimax", ["MM", "#F23F5D"]]],
  [/^(sn-|sensenova)/, ["sensenova", ["SN", "#E8531F"]]],
  [/^gemini/, ["gemini", ["GE", "#4285F4"]]],
  [/^grok/, ["xai", ["GK", "#8A8F98"]]],
  [/^(llama|meta-)/, ["meta", ["LL", "#0668E1"]]],
  [/^(mistral|mixtral)/, ["mistral", ["MI", "#FA520F"]]],
  [/^raccoon/, ["raccoon", ["R", "#4AC08A"]]],
];
function modelIcon(name){
  const n = String(name || "").toLowerCase();
  for (const [re, v] of MODEL_VENDOR){
    if (re.test(n)){
      if (typeof v[1] === "string") return brandImg(v[1]);
      return '<span class="agent-mono" style="--mc:' + v[1][1] + '">' + v[1][0] + '</span>';
    }
  }
  const tag = n.replace(/[^a-z0-9]/g, "").slice(0, 2).toUpperCase() || "?";
  return '<span class="agent-mono" style="--mc:#666C75">' + tag + '</span>';
}
const $ = id => document.getElementById(id);
