"use strict";
let DATA = null, MAIN = null;
const MINIS = [];
const F = { rangeKey: "last7", agent: "all", metric: "tokens", grain: "day", dim: "total", open: new Set() };
const PAL = ["#6C9BFF","#4FC3A1","#E8B45B","#F0737A","#9B92F0","#5CC8DE","#8A93A8","#E08B5C","#B9C0CA"];
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
  "openclaw-autoclaw":"OpenClaw", "agnes":"Agnes", "dsh":"DSH",
  "cline":"Cline", "box-agent":"Box Agent", "mavis":"Mavis",
  "workbuddy":"WorkBuddy", "workbuddy-ai":"WorkBuddy AI",
  "unknown":"未知来源",
};
const AGENT_LOGOS = {
  "codex":"openai.svg", "claude-code":"claude.svg",
  "opencode":"opencode.svg", "cline":"cline.svg",
  /* 2026-09-27：以下均为从本机各应用安装目录提取的真实品牌图（256px 归一） */
  "zcode":"zcode.png", "hermes":"hermes.png", "workbuddy":"workbuddy.png",
  "workbuddy-ai":"workbuddy.png", "dsh":"dsh.png", "catpaw":"catpaw.png",
  "kimi":"kimi.png",
  /* 2026-09-29：MHAgent 官方应用图标（从 %APPDATA%/MHAgent 的 ico 提取 256px） */
  "mhagent":"mhagent.png",
};
/* 本机确实拿不到品牌图的应用 → 字母徽标（比通用图形更像"它们自己"） */
const AGENT_MONO = {
  "box-agent": ["B", "#7C8CF8"], "mhagent": ["MH", "#4AC08A"],
  "mavis": ["M", "#E8B45B"], "agnes": ["A", "#A78BFA"],
  "qoder": ["Q", "#5CC8DE"], "trae-solo": ["T", "#F0737A"], "trae": ["T", "#F0737A"],
  "cursor": ["C", "#9AA1AC"], "doubao": ["D", "#5C8AF5"], "qwen-cli": ["Q", "#7C8CF8"],
  "cherrystudio": ["CH", "#E8834B"], "yumbo": ["YB", "#4FC3A1"],
  "copilot-chat": ["GH", "#9AA1AC"], "copilot-cli": ["GH", "#9AA1AC"],
  "goofish-cli": ["闲", "#E8B45B"], "mimosa": ["M", "#E0607A"],
  "openviking": ["OV", "#5CC8DE"], "raccoonwork": ["R", "#4AC08A"],
};
function agentIcon(name){
  const logo = AGENT_LOGOS[name];
  if (logo){
    return '<img class="agent-brand-img" src="/static/logos/' + logo
      + '" alt="" loading="lazy" decoding="async">';
  }
  const mono = AGENT_MONO[name];
  if (mono){
    return '<span class="agent-mono" style="--mc:' + mono[1] + '">' + mono[0] + '</span>';
  }
  return AGENT_ICONS[name] ||
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="4.2" y="4.2" width="15.6" height="15.6" rx="4"/><circle cx="12" cy="12" r="2.4"/></svg>';
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
      if (typeof v[1] === "string"){
        return '<img class="agent-brand-img" src="/static/logos/' + v[1]
          + '" alt="" loading="lazy" decoding="async">';
      }
      return '<span class="agent-mono" style="--mc:' + v[1][1] + '">' + v[1][0] + '</span>';
    }
  }
  const tag = n.replace(/[^a-z0-9]/g, "").slice(0, 2).toUpperCase() || "?";
  return '<span class="agent-mono" style="--mc:#666C75">' + tag + '</span>';
}
const $ = id => document.getElementById(id);
