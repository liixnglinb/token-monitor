"use strict";
let DATA = null, MAIN = null;
const MINIS = [];
const F = { rangeKey: "last7", agent: "all", metric: "tokens", grain: "day", dim: "total", open: new Set() };
const PAL = ["#4F6BED","#4FB6A6","#E7A93D","#E26D72","#8577E8","#4FA4C8","#8C9AA8","#D28056","#A9B1BC"];
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
  gradient.addColorStop(1, hexA(color, .48));
  return gradient;
}
function lineGradient(context, color){
  const { chart } = context;
  const area = chart.chartArea;
  if (!area) return hexA(color, .18);
  const gradient = chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
  gradient.addColorStop(0, hexA(color, .30));
  gradient.addColorStop(.62, hexA(color, .09));
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
};
const AGENT_NAME = {
  "claude-code":"Claude Code", "codex":"Codex", "zcode":"ZCode",
  "opencode":"OpenCode", "hermes":"Hermes", "mhagent":"MHAgent",
  "openclaw-autoclaw":"OpenClaw", "agnes":"Agnes", "dsh":"DSH",
  "cline":"Cline", "box-agent":"Box Agent", "mavis":"Mavis",
  "unknown":"未知来源",
};
const AGENT_LOGOS = {
  "codex":"openai.svg", "claude-code":"claude.svg",
  "opencode":"opencode.svg", "cline":"cline.svg",
};
function agentIcon(name){
  const logo = AGENT_LOGOS[name];
  if (logo){
    return '<img class="agent-brand-img" src="/static/logos/' + logo
      + '" alt="" loading="lazy" decoding="async">';
  }
  return AGENT_ICONS[name] ||
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="4.2" y="4.2" width="15.6" height="15.6" rx="4"/><circle cx="12" cy="12" r="2.4"/></svg>';
}
const agentLabel = name => AGENT_NAME[name] || name;
const $ = id => document.getElementById(id);
