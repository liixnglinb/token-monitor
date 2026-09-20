# -*- coding: utf-8 -*-
r"""
Token Monitor — 全量数据源注册表
================================================
覆盖范围：
  · 国内 AI 编程/智能体工具（腾讯、阿里、字节、百度、智谱、月之暗面、MiniMax、
    DeepSeek、美团、华为、讯飞、商汤、小米、蚂蚁 …）
  · 国外主流（Anthropic、OpenAI、Google、GitHub、Cursor、Windsurf、AWS、
    JetBrains、Block、Charm、xAI、Meta …）
  · 以及本机实测发现的各类 agent 运行时

字段说明：
  id        唯一标识
  cn/en     中文名 / 英文名
  vendor    厂商
  region    CN 国内 / INTL 国外
  form      形态：cli / cli-desktop / ide / plugin / desktop / api
  paths     路径模板，支持 {home} {appdata} {localappdata} {xdg_data} {xdg_config}
  fmt       解析格式（对应 detect_engine 的解析器）
  status    状态：
              verified  已实测确认存在且有 token 字段
              candidate 路径存在但未确认含 token
              encrypted 数据被加密，需特殊处理
              api_only  本地无数据，须走官方 API
              absent    本机未安装
  note      备注 / 关键字段

本表为"数据"，逻辑在 detect_engine.py。新增源只需在此追加一条。
"""

# ---------------------------------------------------------------- 格式常量
FMT_CLAUDE_LIKE = "jsonl_claude_like"      # message.usage 四类 token
FMT_CODEX_ROLL = "jsonl_codex_rollout"     # token_count 累计值
FMT_SQL_TABLES = "sqlite_token_tables"     # 扫全库找 token 列
FMT_SQL_NAMED = "sqlite_named"             # 指定表与列
FMT_JSON_CHAT = "json_chat"                # 通用 JSON 会话（含 usage 对象）
FMT_JSONL_GEN = "jsonl_generic"            # 通用 JSONL，递归找 usage
FMT_LOG = "log_generic"
FMT_ENC = "sqlcipher_encrypted"
FMT_API = "api_sync"
FMT_NONE = "none"

SOURCES = [
    # ============================================================ 国内 · 巨头
    dict(id="workbuddy", cn="腾讯 WorkBuddy", en="Tencent WorkBuddy",
         vendor="腾讯", region="CN", form="desktop",
         paths=["{home}/.workbuddy/projects", "{home}/.workbuddy-ai/projects",
                "{home}/.workbuddy/workbuddy.db"],
         fmt=FMT_CLAUDE_LIKE, status="verified",
         note="与 Claude Code 同构；5.5+ 迁至 .workbuddy-ai；另有 sqlite 回退"),

    dict(id="codebuddy", cn="腾讯 CodeBuddy", en="Tencent CodeBuddy",
         vendor="腾讯", region="CN", form="cli",
         paths=["{home}/.codebuddy/projects", "{home}/.codebuddy/models.json"],
         fmt=FMT_CLAUDE_LIKE, status="candidate",
         note="CodeBuddy Code CLI；与 Claude Code 同构"),

    dict(id="yumbo", cn="腾讯元宝", en="Tencent Yuanbao",
         vendor="腾讯", region="CN", form="desktop",
         paths=["{appdata}/Tencent/Yuanbao", "{appdata}/yuanbao"],
         fmt=FMT_JSONL_GEN, status="candidate"),

    dict(id="ima", cn="腾讯 IMA", en="Tencent IMA",
         vendor="腾讯", region="CN", form="desktop",
         paths=["{appdata}/Tencent/IMA", "{appdata}/ima.copilot"],
         fmt=FMT_JSONL_GEN, status="absent"),

    dict(id="tongyi-lingma", cn="阿里 通义灵码", en="Alibaba Tongyi Lingma",
         vendor="阿里巴巴", region="CN", form="plugin",
         paths=["{appdata}/Code/User/globalStorage/alibaba-cloud.tongyi-lingma",
                "{home}/.lingma", "{home}/.tongyi-lingma",
                "{appdata}/JetBrains/lingma"],
         fmt=FMT_JSONL_GEN, status="candidate",
         note="VS Code / JetBrains 插件；国内用户量最大"),

    dict(id="qoder", cn="阿里 Qoder", en="Alibaba Qoder",
         vendor="阿里巴巴", region="CN", form="ide",
         paths=["{home}/.qoder-cli/ai-stats", "{home}/.qoder", "{home}/.qoderwork",
                "{home}/.qodersec", "{appdata}/QoderCN", "{appdata}/QoderWork CN"],
         fmt=FMT_JSONL_GEN, status="verified",
         note="ai-stats 仅代码行归属；token 需查 index/IndexedDB"),

    dict(id="qwen-cli", cn="阿里 通义千问 CLI", en="Alibaba Qwen CLI",
         vendor="阿里巴巴", region="CN", form="cli",
         paths=["{home}/.qwen/projects", "{home}/.qwen-agent", "{appdata}/Qianwen"],
         fmt=FMT_CLAUDE_LIKE, status="candidate"),

    dict(id="trae", cn="字节 TRAE", en="ByteDance TRAE",
         vendor="字节跳动", region="CN", form="ide",
         paths=["{home}/.trae-cn", "{appdata}/TRAE SOLO CN", "D:/Trae"],
         fmt=FMT_ENC, status="encrypted",
         note="数据存于 SQLCipher 加密 SQLite；需密钥提取或官方 API 同步"),

    dict(id="doubao", cn="字节 豆包", en="ByteDance Doubao",
         vendor="字节跳动", region="CN", form="desktop",
         paths=["{appdata}/Doubao", "{home}/Doubao"],
         fmt=FMT_JSONL_GEN, status="candidate"),

    dict(id="ark", cn="字节 火山方舟", en="ByteDance Volcengine Ark",
         vendor="字节跳动", region="CN", form="api",
         paths=[], fmt=FMT_API, status="api_only",
         note="API 服务，须查控制台或账单接口"),

    dict(id="comate", cn="百度 文心快码", en="Baidu Comate",
         vendor="百度", region="CN", form="plugin",
         paths=["{appdata}/Code/User/globalStorage/baidu-comate",
                "{home}/.comate", "{appdata}/JetBrains/comate"],
         fmt=FMT_JSONL_GEN, status="candidate"),

    dict(id="zhipu-codegeex", cn="智谱 CodeGeeX", en="Zhipu CodeGeeX",
         vendor="智谱 AI", region="CN", form="plugin",
         paths=["{appdata}/Code/User/globalStorage/zhipu-ai.codegeex",
                "{home}/.codegeex", "{home}/.codeium"],
         fmt=FMT_JSONL_GEN, status="candidate"),

    dict(id="kimi", cn="月之暗面 Kimi", en="Moonshot Kimi",
         vendor="月之暗面", region="CN", form="cli",
         paths=["{home}/.kimi/sessions", "{home}/.kimi-code/sessions",
                "{home}/.kimi-work", "{appdata}/kimi-desktop"],
         fmt=FMT_JSONL_GEN, status="verified",
         note="kimi-cli / kimi-code / kimi-work 三形态；日志目录无 token"),

    dict(id="minimax", cn="MiniMax Code", en="MiniMax Code",
         vendor="MiniMax", region="CN", form="cli",
         paths=["{home}/.minimax", "{home}/.minimax-agent-cn",
                "{home}/.config/tokscale/headless/mcode"],
         fmt=FMT_SQL_TABLES, status="candidate"),

    dict(id="dsh", cn="DeepSeek Harness", en="DeepSeek Harness",
         vendor="深度求索", region="CN", form="cli",
         paths=["{home}/.dsh/sessions", "{appdata}/DSH Desktop"],
         fmt=FMT_JSONL_GEN, status="verified",
         note="session.jsonl.zstd，需 zstd 解压"),

    dict(id="catpaw", cn="美团 CatPaw", en="Meituan CatPaw",
         vendor="美团", region="CN", form="desktop",
         paths=["{home}/.catpaw", "{home}/.catdesk", "{appdata}/catpaw-moon",
                "{appdata}/meituan-catpaw", "D:/CatPaw"],
         fmt=FMT_SQL_TABLES, status="candidate",
         note="主推 LongCat 模型"),

    dict(id="zcode", cn="ZCode", en="ZCode",
         vendor="ZCode", region="CN", form="cli",
         paths=["{home}/.zcode/cli/db/db.sqlite", "{home}/.zcode/projects"],
         fmt=FMT_SQL_NAMED, status="verified",
         note="model_usage 表 3,555 行，字段最全（含耗时/TTFT）"),

    dict(id="mimo", cn="小米 MiMo Code", en="Xiaomi MiMo Code",
         vendor="小米", region="CN", form="cli",
         paths=["{home}/.local/share/mimocode/mimocode.db"],
         fmt=FMT_SQL_TABLES, status="absent"),

    dict(id="codefuse", cn="蚂蚁 CodeFuse", en="Ant CodeFuse",
         vendor="蚂蚁集团", region="CN", form="cli",
         paths=["{home}/.codefuse", "{appdata}/codefuse"],
         fmt=FMT_JSONL_GEN, status="absent"),

    dict(id="codearts", cn="华为 CodeArts Snap", en="Huawei CodeArts Snap",
         vendor="华为", region="CN", form="plugin",
         paths=["{home}/.codearts", "{appdata}/Code/User/globalStorage/huawei.codearts"],
         fmt=FMT_JSONL_GEN, status="absent"),

    dict(id="iflycode", cn="讯飞 iFlyCode", en="iFlytek iFlyCode",
         vendor="科大讯飞", region="CN", form="plugin",
         paths=["{home}/.iflycode", "{appdata}/Code/User/globalStorage/iflytek.iflycode"],
         fmt=FMT_JSONL_GEN, status="absent"),

    dict(id="sensenova", cn="商汤 SenseNova", en="SenseTime SenseNova",
         vendor="商汤", region="CN", form="api",
         paths=[], fmt=FMT_API, status="api_only",
         note="本机日志中出现 sensenova-6.8-flash-lite 模型调用"),

    dict(id="cherrystudio", cn="Cherry Studio", en="Cherry Studio",
         vendor="Cherry Studio", region="CN", form="desktop",
         paths=["{home}/.cherrystudio", "{appdata}/CherryStudio",
                "{appdata}/CherryStudio/Data/Agents/.claude/projects"],
         fmt=FMT_CLAUDE_LIKE, status="verified",
         note="Agent 模式转录与 Claude Code 同构"),

    # ============================================================ 国内 · 新兴
    dict(id="reasonix", cn="Reasonix", en="Reasonix",
         vendor="Reasonix", region="CN", form="cli-desktop",
         paths=["{home}/.reasonix/stats", "{appdata}/reasonix/archive"],
         fmt=FMT_JSONL_GEN, status="candidate"),

    dict(id="agnes", cn="Agnes", en="Agnes",
         vendor="Agnes", region="CN", form="cli",
         paths=["{home}/.agnes", "{home}/agnes"], fmt=FMT_SQL_TABLES,
         status="candidate"),

    dict(id="mavis", cn="Mavis", en="Mavis",
         vendor="Mavis", region="CN", form="cli",
         paths=["{home}/.mavis"], fmt=FMT_SQL_TABLES, status="candidate"),

    dict(id="mimosa", cn="Mimosa", en="Mimosa",
         vendor="Mimosa", region="CN", form="cli",
         paths=["{home}/.mimosa"], fmt=FMT_SQL_TABLES, status="candidate"),

    dict(id="openviking", cn="OpenViking", en="OpenViking",
         vendor="OpenViking", region="CN", form="cli",
         paths=["{home}/.openviking"], fmt=FMT_JSONL_GEN, status="candidate"),

    dict(id="box-agent", cn="Box Agent", en="Box Agent",
         vendor="Box Agent", region="CN", form="cli",
         paths=["{home}/.box-agent", "D:/AI-Tools-Data/.box-agent"],
         fmt=FMT_JSONL_GEN, status="candidate"),

    dict(id="hermes", cn="Hermes Agent", en="Hermes Agent",
         vendor="Hermes", region="CN", form="cli",
         paths=["{home}/.hermes/state.db", "{home}/.hermes/profiles",
                "{appdata}/Hermes"],
         fmt=FMT_SQL_TABLES, status="verified",
         note="sessions 表含四类 token；messages 表含 token_count"),

    dict(id="raccoonwork", cn="RaccoonWork", en="RaccoonWork",
         vendor="RaccoonWork", region="CN", form="desktop",
         paths=["{home}/RaccoonWork", "{appdata}/office-raccoon"],
         fmt=FMT_JSONL_GEN, status="candidate"),

    dict(id="goofish-cli", cn="闲鱼 CLI", en="Goofish CLI",
         vendor="阿里巴巴", region="CN", form="cli",
         paths=["{home}/.goofish-cli"], fmt=FMT_JSONL_GEN, status="candidate"),

    dict(id="lark-cli", cn="飞书 CLI", en="Lark CLI",
         vendor="字节跳动", region="CN", form="cli",
         paths=["{home}/.lark-cli"], fmt=FMT_JSONL_GEN, status="candidate"),

    dict(id="cc-switch", cn="CC Switch", en="CC Switch",
         vendor="第三方", region="CN", form="desktop",
         paths=["{home}/.cc-switch", "{appdata}/com.ccswitch.desktop"],
         fmt=FMT_JSONL_GEN, status="candidate",
         note="Claude Code 配置切换器，本身不产 token"),

    # ============================================================ 国外 · 主流
    dict(id="claude-code", cn="Anthropic Claude Code", en="Claude Code",
         vendor="Anthropic", region="INTL", form="cli",
         paths=["{home}/.claude/projects", "{home}/.claude/transcripts"],
         fmt=FMT_CLAUDE_LIKE, status="verified",
         note="message.usage；须按 message.id 去重（65% 重复）"),

    dict(id="codex", cn="OpenAI Codex CLI", en="OpenAI Codex CLI",
         vendor="OpenAI", region="INTL", form="cli",
         paths=["{home}/.codex/sessions", "{home}/.codex/archived_sessions",
                "{appdata}/Codex++"],
         fmt=FMT_CODEX_ROLL, status="verified",
         note="token_count 累计值取末条；input 已含 cached"),

    dict(id="gemini-cli", cn="Google Gemini CLI", en="Google Gemini CLI",
         vendor="Google", region="INTL", form="cli",
         paths=["{home}/.gemini/tmp", "{home}/.gemini/antigravity-cli/conversations"],
         fmt=FMT_JSON_CHAT, status="candidate"),

    dict(id="copilot-cli", cn="GitHub Copilot CLI", en="GitHub Copilot CLI",
         vendor="GitHub", region="INTL", form="cli",
         paths=["{home}/.copilot/otel", "{home}/.copilot"],
         fmt=FMT_JSONL_GEN, status="candidate"),

    dict(id="copilot-chat", cn="GitHub Copilot Chat", en="GitHub Copilot Chat",
         vendor="GitHub", region="INTL", form="plugin",
         paths=["{appdata}/Code/User/globalStorage/github.copilot-chat"],
         fmt=FMT_SQL_TABLES, status="candidate",
         note="session-store.db 有 sessions/turns 表"),

    dict(id="opencode", cn="OpenCode", en="OpenCode",
         vendor="OpenCode", region="INTL", form="cli",
         paths=["{xdg_data}/opencode/opencode.db",
                "{xdg_data}/opencode/opencode-stable.db",
                "{xdg_data}/opencode/storage/message",
                "{appdata}/ai.opencode.desktop"],
         fmt=FMT_SQL_TABLES, status="verified",
         note="session 表自带 cost 与四类 token"),

    dict(id="cursor", cn="Cursor", en="Cursor",
         vendor="Anysphere", region="INTL", form="ide",
         paths=["{home}/.cursor", "{appdata}/Cursor",
                "{home}/.config/tokscale/cursor-cache"],
         fmt=FMT_API, status="api_only",
         note="本地仅代码追踪；用量须官方 API 同步"),

    dict(id="windsurf", cn="Windsurf", en="Windsurf (Codeium)",
         vendor="Codeium", region="INTL", form="ide",
         paths=["{home}/.windsurf", "{home}/.codeium", "{appdata}/Windsurf"],
         fmt=FMT_JSONL_GEN, status="absent"),

    dict(id="aider", cn="Aider", en="Aider",
         vendor="Aider", region="INTL", form="cli",
         paths=["{home}/.aider", "{home}/.aider.tags.cache.v4"],
         fmt=FMT_JSONL_GEN, status="absent"),

    dict(id="cline", cn="Cline", en="Cline",
         vendor="Cline", region="INTL", form="plugin",
         paths=["{home}/.cline/data/sessions",
                "{appdata}/Code/User/globalStorage/saoudrizwan.claude-dev/tasks"],
         fmt=FMT_JSONL_GEN, status="absent"),

    dict(id="roo-code", cn="Roo Code", en="Roo Code",
         vendor="Roo", region="INTL", form="plugin",
         paths=["{appdata}/Code/User/globalStorage/rooveterinaryinc.roo-cline/tasks"],
         fmt=FMT_JSONL_GEN, status="absent"),

    dict(id="kilo-code", cn="Kilo Code", en="Kilo Code",
         vendor="Kilo", region="INTL", form="plugin",
         paths=["{appdata}/Code/User/globalStorage/kilocode.kilo-code/tasks",
                "{xdg_data}/kilo/kilo.db"],
         fmt=FMT_JSONL_GEN, status="absent"),

    dict(id="continue", cn="Continue", en="Continue",
         vendor="Continue", region="INTL", form="plugin",
         paths=["{home}/.continue/sessions",
                "{appdata}/Code/User/globalStorage/continue.continue"],
         fmt=FMT_JSONL_GEN, status="absent"),

    dict(id="amp", cn="Amp", en="Amp (AmpCode)",
         vendor="Sourcegraph", region="INTL", form="cli",
         paths=["{xdg_data}/amp/threads"], fmt=FMT_JSONL_GEN, status="absent"),

    dict(id="droid", cn="Factory Droid", en="Factory Droid",
         vendor="Factory", region="INTL", form="cli",
         paths=["{home}/.factory/sessions"], fmt=FMT_JSONL_GEN, status="absent"),

    dict(id="goose", cn="Block Goose", en="Block Goose",
         vendor="Block", region="INTL", form="cli",
         paths=["{xdg_data}/goose/sessions/sessions.db",
                "{appdata}/Block/goose"],
         fmt=FMT_SQL_TABLES, status="absent"),

    dict(id="crush", cn="Charm Crush", en="Charm Crush",
         vendor="Charm", region="INTL", form="cli",
         paths=["{xdg_data}/crush/projects.json"], fmt=FMT_JSON_CHAT, status="absent"),

    dict(id="opencode-review", cn="OpenCodeReview", en="OpenCodeReview",
         vendor="OpenCodeReview", region="INTL", form="cli",
         paths=["{home}/.opencodereview/sessions"], fmt=FMT_JSONL_GEN, status="absent"),

    dict(id="openclaw", cn="OpenClaw", en="OpenClaw",
         vendor="OpenClaw", region="INTL", form="cli",
         paths=["{home}/.openclaw/agents", "{home}/.clawdbot/agents",
                "{home}/.moltbot/agents"],
         fmt=FMT_SQL_TABLES, status="candidate"),

    dict(id="devin", cn="Devin CLI", en="Devin CLI",
         vendor="Cognition", region="INTL", form="cli",
         paths=["{xdg_data}/devin/cli/sessions.db",
                "{appdata}/Devin/User/acp-events"],
         fmt=FMT_SQL_TABLES, status="absent"),

    dict(id="junie", cn="JetBrains Junie", en="JetBrains Junie",
         vendor="JetBrains", region="INTL", form="plugin",
         paths=["{home}/.junie/sessions"], fmt=FMT_JSONL_GEN, status="absent"),

    dict(id="zed", cn="Zed Agent", en="Zed Agent",
         vendor="Zed", region="INTL", form="ide",
         paths=["{xdg_data}/zed/threads/threads.db",
                "{appdata}/Zed/threads/threads.db"],
         fmt=FMT_SQL_TABLES, status="absent"),

    dict(id="kiro", cn="AWS Kiro", en="AWS Kiro",
         vendor="AWS", region="INTL", form="ide",
         paths=["{home}/.kiro/sessions/cli", "{xdg_data}/kiro-cli/data.sqlite3"],
         fmt=FMT_JSON_CHAT, status="absent"),

    dict(id="amazon-q", cn="Amazon Q Developer", en="Amazon Q Developer",
         vendor="AWS", region="INTL", form="plugin",
         paths=["{home}/.aws/amazonq"], fmt=FMT_JSONL_GEN, status="absent"),

    dict(id="augment", cn="Augment Code", en="Augment Code",
         vendor="Augment", region="INTL", form="cli",
         paths=["{home}/.augment/sessions"], fmt=FMT_JSON_CHAT, status="absent"),

    dict(id="warp", cn="Warp", en="Warp",
         vendor="Warp", region="INTL", form="cli",
         paths=["{home}/.warp", "{appdata}/Warp"], fmt=FMT_API, status="api_only"),

    dict(id="grok-build", cn="xAI Grok Build", en="xAI Grok Build",
         vendor="xAI", region="INTL", form="cli",
         paths=["{home}/.grok/sessions"], fmt=FMT_JSONL_GEN, status="absent"),

    dict(id="lmstudio", cn="LM Studio", en="LM Studio",
         vendor="LM Studio", region="INTL", form="desktop",
         paths=["{home}/.lmstudio/server-logs"], fmt=FMT_LOG, status="absent",
         note="本地推理，成本 $0"),

    dict(id="unsloth", cn="Unsloth Studio", en="Unsloth Studio",
         vendor="Unsloth", region="INTL", form="desktop",
         paths=["{home}/.unsloth/studio/studio.db"], fmt=FMT_SQL_TABLES, status="absent"),

    dict(id="mux", cn="Mux", en="Mux",
         vendor="Mux", region="INTL", form="cli",
         paths=["{home}/.mux/sessions"], fmt=FMT_JSONL_GEN, status="absent"),

    dict(id="pi", cn="Pi / Oh My Pi", en="Pi / Oh My Pi",
         vendor="Pi", region="INTL", form="cli",
         paths=["{home}/.pi/agent/sessions", "{home}/.omp/agent/sessions"],
         fmt=FMT_JSONL_GEN, status="absent"),

    dict(id="prime", cn="Prime Agent", en="Prime Agent",
         vendor="Prime", region="INTL", form="cli",
         paths=["{home}/.prime/agent/sessions"], fmt=FMT_JSONL_GEN, status="absent"),

    dict(id="codebuff", cn="Codebuff", en="Codebuff",
         vendor="Codebuff", region="INTL", form="cli",
         paths=["{home}/.config/manicode", "{home}/.config/manicode-dev"],
         fmt=FMT_JSONL_GEN, status="absent"),

    dict(id="command-code", cn="Command Code", en="Command Code",
         vendor="Command Code", region="INTL", form="cli",
         paths=["{home}/.commandcode/projects"], fmt=FMT_JSONL_GEN, status="absent"),

    dict(id="jcode", cn="Jcode", en="Jcode",
         vendor="Jcode", region="INTL", form="cli",
         paths=["{home}/.jcode/sessions"], fmt=FMT_JSONL_GEN, status="absent"),

    dict(id="opencode-atlantis", cn="Antigravity CLI", en="Antigravity CLI",
         vendor="Google", region="INTL", form="cli",
         paths=["{home}/.gemini/antigravity-cli/conversations"],
         fmt=FMT_SQL_TABLES, status="absent"),

    # ============================================================ 通用/辅助
    dict(id="cc-switch-data", cn="CC Switch 代理日志", en="CC Switch Proxy Logs",
         vendor="第三方", region="CN", form="desktop",
         paths=["{home}/.cc-switch", "{home}/.cc-switch_tmp"],
         fmt=FMT_SQL_TABLES, status="verified",
         note="★代理层完整请求日志：proxy_request_logs 10,289 行含四类 token；"
              "model_pricing 199 个模型价格 —— 相当于本地中转站，价值极高"),

    dict(id="agnes-ledger", cn="Agnes 用量台账", en="Agnes Usage Ledger",
         vendor="Agnes", region="CN", form="cli",
         paths=["{home}/.agnes"], fmt=FMT_SQL_TABLES, status="verified",
         note="sessions / messages / usage_ledger(113 行) 三张表均含 token"),

    dict(id="mha-agent", cn="MHAgent", en="MHAgent",
         vendor="第三方", region="CN", form="desktop",
         paths=["{appdata}/MHAgent", "{home}/.mha-agent"],
         fmt=FMT_JSONL_GEN, status="verified",
         note="字段 cache_read_input_tokens / input_tokens / output_tokens"),

    dict(id="modex", cn="ModexData", en="ModexData",
         vendor="ModexData", region="CN", form="desktop",
         paths=["{appdata}/ModexData"], fmt=FMT_SQL_TABLES, status="verified",
         note="chat_sessions.cost_usd；chat_messages.tokens_in / tokens_out"),

    dict(id="openclaw-autoclaw", cn="OpenClaw AutoClaw", en="OpenClaw AutoClaw",
         vendor="OpenClaw", region="CN", form="cli",
         paths=["{home}/.openclaw-autoclaw"], fmt=FMT_SQL_TABLES,
         status="verified", note="cron_run_logs.total_tokens"),

    dict(id="workbuddy-legacy", cn="WorkBuddy 旧版数据", en="WorkBuddy Legacy",
         vendor="腾讯", region="CN", form="desktop",
         paths=["{home}/.workbuddy_legacy"], fmt=FMT_JSONL_GEN,
         status="verified", note="WorkBuddy 迁移前的旧数据，含 inputTokens/outputTokens"),

    dict(id="codex-session-delete", cn="Codex 会话归档工具", en="Codex Session Delete",
         vendor="第三方", region="CN", form="cli",
         paths=["{home}/.codex-session-delete"], fmt=FMT_JSONL_GEN,
         status="candidate", note="84 文件 / 448MB，含 tokens_used"),

    dict(id="meituan-catpaw-models", cn="美团 CatPaw 价格库", en="Meituan CatPaw Models",
         vendor="美团", region="CN", form="desktop",
         paths=["{home}/.meituan-catpaw", "{home}/.catpaw/.catpaw"],
         fmt=FMT_SQL_TABLES, status="candidate",
         note="models 表含 input_price / output_price / cache_price（价格源）"),

    dict(id="trae-solo", cn="字节 TRAE SOLO（可读）", en="ByteDance TRAE SOLO",
         vendor="字节跳动", region="CN", form="ide",
         paths=["{appdata}/TRAE SOLO CN"], fmt=FMT_JSONL_GEN,
         status="encrypted",
         note="★706 文件 / 606MB，含 usage 字段；与加密的 .trae-cn 不同，此路可读"),

    dict(id="tokscale", cn="Tokscale", en="Tokscale",
         vendor="junhoyeo", region="INTL", form="cli",
         paths=["{appdata}/tokscale", "{home}/.config/tokscale"],
         fmt=FMT_NONE, status="verified",
         note="不产 token，但含 LiteLLM/OpenRouter 价格缓存，可直接复用"),

    dict(id="ai-tools-data", cn="AI 工具数据根目录", en="AI Tools Data Root",
         vendor="用户自建", region="CN", form="dir",
         paths=["D:/AI-Tools-Data"], fmt=FMT_NONE, status="verified",
         note="本机 C 盘点目录的软链接目标，聚合了大量 agent 数据"),
]

# ------------------------------------------------ 通用兜底扫描的候选根目录
# 这些目录下的所有子目录都会被"内容实证"检查，用于发现注册表未收录的新工具
SWEEP_ROOTS = [
    "{home}",                      # 用户主目录（含隐藏目录）
    "{appdata}",                   # Electron 类桌面应用主战场
    "{localappdata}",              # 另一批桌面应用
    "{xdg_data}", "{xdg_config}",
]

# 全盘扫描时在各盘根/一层子目录寻找的候选名
DRIVE_CANDIDATES = {
    ".claude", ".codex", ".codex-plus", ".zcode", ".workbuddy", ".workbuddy-ai",
    ".codebuddy", ".qwen", ".qwen-agent", ".cursor", ".gemini", ".dsh", ".hermes",
    ".opencode", "opencode", "cherrystudio", ".cherrystudio", "reasonix",
    ".reasonix", ".kimi", ".kimi-code", ".kimi-work", ".trae-cn", "trae",
    ".qoder", ".qoder-cli", ".qoderwork", ".qodersec", ".factory", ".pi",
    ".mux", ".prime", ".grok", ".kiro", ".augment", ".junie", ".cline",
    ".goose", ".crush", ".kilo", ".aider", ".windsurf", ".codeium",
    "ai-tools-data", "agnes", "catpaw", ".catpaw", ".catdesk", ".mavis",
    ".mimosa", ".openviking", ".box-agent", ".minimax", ".minimax-agent-cn",
    ".sensenova", ".mimo", "tokscale", ".tokscale", ".reasonix",
}

# 系统目录，扫描时跳过
SKIP_DIRS = {
    "windows", "$recycle.bin", "system volume information", "program files",
    "program files (x86)", "programdata", "appdata", "node_modules",
    "recovery", "$windows.~ws", "msocache", "perflogs", "intel", "amd",
    "nvidia", "drivers", "temp", "tmp",
}

# 用于判定"含 token 账本"的字段名（小写匹配）
TOKEN_KEYS = (
    "input_tokens", "output_tokens", "inputtokens", "outputtokens",
    "prompt_tokens", "completion_tokens", "prompttokens", "completiontokens",
    "total_tokens", "totaltokens", "tokens_input", "tokens_output",
    "cache_read_input_tokens", "cached_input_tokens", "cachecreationinputtokens",
    "cache_read_tokens", "cache_write_tokens", "tokens_cache_read",
    "tokens_cache_write", "reasoning_tokens", "reasoningtokens",
    "token_count", "tokencount", "tokens_used", "total_tokencount",
    "promptTokens".lower(), "usage", "cost_usd", "totalcost",
)

# 扫描时考虑的文件后缀
DATA_SUFFIX = (".jsonl", ".json", ".db", ".sqlite", ".sqlite3", ".csv",
               ".log", ".zstd", ".ndjson")

# SQLite 中视为"token 列"的列名子串
SQL_TOKEN_HINTS = ("token", "cost", "usage", "price", "credit")


def expand(tpl, home, appdata, localappdata, xdg_data, xdg_config):
    return tpl.format(home=home, appdata=appdata, localappdata=localappdata,
                      xdg_data=xdg_data, xdg_config=xdg_config)


def stats():
    from collections import Counter
    c = Counter(s["status"] for s in SOURCES)
    r = Counter(s["region"] for s in SOURCES)
    return dict(total=len(SOURCES), by_status=dict(c), by_region=dict(r))


if __name__ == "__main__":
    import json
    print(json.dumps(stats(), ensure_ascii=False, indent=2))
