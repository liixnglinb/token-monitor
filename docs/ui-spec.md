# Token Monitor · UI 设计规范

本文件是界面层的唯一规范来源。**所有数值都必须来自 `webapp/static/styles/tokens.css`**，
组件样式不得再写死颜色、字号、间距与圆角。

- 样式入口：`webapp/static/styles/styles.css`（index.html 只引用这一个样式表）
- 层叠层顺序：`legacy < base < components < layout`
- 校验脚本：`tools/ui_audit.py`（硬编码/字号/规范覆盖）、`tools/contrast_check.py`（对比度）、
  `tools/ui_verify.py`（DOM/焦点/对比度体检）、`tools/ui_smoke.py`（交互回归）、
  `tools/final_check.py`（收尾综合验收）、`tools/style_snapshot.py`（计算样式快照对比）、
  `tools/capture_spec_shots.py`（本文档实拍图）

> 2026-10-03 · v2.0 前端大重构：由「控制台仪表盘」转为**杂志化排版 + 统一网格卡片（Bento Box）**。
> 骨架从「248px 侧栏 + 普通顶栏」改为「64px Slim Rail + 全局上下文顶栏」，总览视图由单张
> Hero 复合卡拆为 4 联等高 KPI 网格 + 主舞台 + 侧边排行 + 底部双栏。

---

## 一、信息架构与导航

| 项目 | 约定 |
| --- | --- |
| 页面职责 | `用量总览`＝看趋势与构成；`模型用量`＝查明细表；`设置`＝改配置。一个视图只做一件事 |
| 首屏网格 | **4 联 Bento KPI（等高 `--kpi-h` 168px）**：① Token 总量（大数缩写↔完整，点击锁定；底部「按量计费 / 套餐不计费」微型双色条）② 缓存杠杆（左：等效节省金额 + 节省率；右：四色迷你环形图；下：紧凑图例）③ API 与并发（请求总数 + 日均 + 背景极弱 sparkline）④ 资金消耗（¥/$ 双显，**悬停 3D 翻转**看单次均价） |
| 主舞台 | 主图表**取消卡片边框**直接融入背景；右上角浮动 `.glass-seg` 毛玻璃分段控件切换三视角 |
| 主图视角 | `segLens`：实体堆叠（按源/模型/总量）/ 物理构成（五态堆叠，自动停用指标与维度切换）/ 缓存杠杆（上轨=全量等效输入、下轨=真实付费输入＝输入+10%读取+125%写入，阴影=缓存吸收） |
| Agent 排行 | 主舞台**右侧侧边面板** `.agent-rail`（原在图表下方）；行高压缩，sparkline **仅悬停/展开时渐隐浮现**；展开用 `grid-template-rows: 0fr→1fr` 平滑拉伸 |
| 底部双栏 | 左：模型用量环形图（镂空放大，中心突出模型数）+ **单列调用次数 Top 10**（原双列条已融合为环形图右侧附带列表）；右：每日明细表 |
| 主导航 | 极简左侧导航栏 `.slim-rail`（64px，仅图标 + 悬停浮层提示，含选中指示条）；窄屏改为底部标签栏（≤760px），二者共用同一套 `switchView` |
| 全局筛选 | 上下文顶栏 `.global-filters` 承载**时间范围**与**数据源**两个下拉（原左侧栏数据源列表整体上移，按数据源过滤在顶栏一处完成） |
| 二级导航 | 设置页分类改为**视图内横向选项卡** `#setNav`（通用偏好 / 扫描与缓存 / 关于），不再占用侧栏 |
| 深链接 | hash 路由 + **筛选参数序列化**：`#/overview?range=last7&agent=codex&metric=tokens&grain=day&dim=total&billing=plan`；刷新/前进/后退/分享都不丢过滤视图 |
| 窄屏筛选 | ≤760px 顶栏「筛选」按钮打开**数据源抽屉**（与顶栏下拉共用同一份渲染，`role=dialog` + 焦点陷阱 + Esc 关闭） |
| 返回 | 设置页「← 返回总览」；`Esc` 关闭弹层与抽屉；浏览器后退等价于返回上一视图 |
| 内容形态 | 时间序数据→图表；跨维度对比→表格；单个实体摘要→卡片；来源清单→列表 |

> 面包屑已移除：位置感改由**上下文顶栏的大标题**承担（标题即当前位置），减少一条冗余信息线。

## 二、布局与栅格

| 项目 | 约定 |
| --- | --- |
| 页面骨架 | `body` 用 `grid-template-areas: "rail main"`：Slim Rail 64px（`--rail-w`）+ 主区自适应 |
| Bento 网格 | KPI 行 `repeat(4, minmax(0,1fr))`；主舞台行 `minmax(0,2.1fr) minmax(300px,1fr)`；底部行 2 等分 |
| 间距阶梯 | `--sp-1..--sp-9` = 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 56 px；网格间距 `--grid-gap` 16 / `--grid-gap-lg` 24 / `--grid-gap-sm` 12 |
| 内容列 | `--content-max` 1440px 居中；内边距 `--content-pad-x/y`（宽屏 36px，窄屏 20/14px） |
| 固定元素 | Slim Rail sticky 满高；上下文顶栏 sticky 毛玻璃；表格动作栏 sticky；表头在**表格自身滚动容器**内 sticky；窄屏底部标签栏 fixed |
| 留白节奏 | KPI 卡内 16/20px；网格间距 16px；区块间距 24px；标题到内容 12px |

断点：`≥1441`（内边距加大）、`≤1280`（主舞台比例收窄）、`≤1180`（顶栏隐藏副标题与筛选摘要）、
`≤1100`（KPI 两列，主舞台与 Agent 侧栏改为上下堆叠）、`≤900`（顶栏换行，筛选独占一行）、
`≤760`（Slim Rail 转底部标签栏，全部单列/两列，模型表卡片化）、`≤480`（KPI 单列）、`≤360`（极限窄屏兜底）。

## 三、设计规范（设计系统）

全部 token 定义在 `tokens.css`，共 7 组：基础阶梯、深色主题、浅色主题、系统偏好、兼容别名、
无障碍偏好、吸顶偏移。

- **色彩**：面 6 级（`--canvas/--surface/--surface-2/--surface-3/--side/--inset`）、
  线 3 级（`--line/--line-soft/--line-strong`）+ `--hairline`（排版驱动的极细分隔线）、
  文字 5 级（`--ink/--text/--text-2/--muted/--m-dim`）、
  语义 4 组（`--pos/--warn/--neg/--info`，各带 `-soft`）、指标 5 色（`--m-token/--m-cost/--m-req/--m-avg/--m-cache`）、
  **Token 五态**（`--tok-inp/--tok-out/--tok-cr/--tok-cw/--tok-think`：输入/输出/缓存读/缓存写/深度思考，
  深色 500·400 系、浅色 700·800 系，全部过 AA）、图表 9 色（`--c1..--c9`）。同一语义全站只用同一个 token。
- **字体**：字号阶梯 9 档（11/12/13/14/16/20/24/30/32）+ 排版阶梯（`--fs-hero 40`、
  `--fs-display 38 / --fs-display-sm 30 / --fs-display-xs 24` 用于 Bento 大数字）；
  字重仅 3 档（400/550/650）；行高 4 档；字体族 `--font-ui`（中文优先）/`--font-mono`。
- **形状**：控件 8px、面板 12px、卡片 14px、弹窗 16px、胶囊 999px、小标 4/6px。
- **材质与深度**：`--shadow-sm/md/lg` + `--shadow-focus` + `--shadow-float`（浮层）；
  卡片材质 `--card-bg` / 悬停 `--card-hover-bg` / **边缘光泽 `--edge-glow`**（1px 亮边 + 内高光 + 底层弥散阴影，
  替代单纯的背景色变化）；**毛玻璃** `--glass-bg` / `--glass-line` / `--glass-blur` / `--glass-sat`
  （浮动控件共用）；**纹理** `--noise` / `--noise-opacity` / `--grid-tex` / `--grid-tex-size`（极弱网格背景，仅作质感）。
- **图标**：统一线性风格、`currentColor` 描边、16/20/24 网格、`stroke-width` 1.4–1.8。
- **token 化**：`components.css` / `layout.css` 中的硬编码颜色为 **0**（`base.css` 仅打印分支保留
  `#fff/#000/#ccc`，打印不走主题无法 token 化）；字号一律走 `--fs-*` 阶梯，样式中不出现 px 字面量。

## 四、基础组件规范

| 组件 | 类型/尺寸 | 必须覆盖的状态 |
| --- | --- | --- |
| 按钮 `.btn` | `btn-primary`（主）、`btn`（次）、`btn-ghost`（文字）、`btn-danger`（危险）；`btn-sm` 28 / 默认 34 / `btn-lg` 40 / `icon-btn` 方形 | 默认·悬停·按下·聚焦·禁用·加载（`aria-busy`） |
| 输入类 | `input[type=text/search]`、`select.set-sel`、`textarea`、`.field-search`（带图标搜索）、`.switch`（开关）、`.seg`（分段） | 默认·悬停·聚焦·错误（`aria-invalid`）·禁用 |
| Bento 卡 | `.kpi-card`（等高、`--i` 用于错开入场）+ `.kc-head/.kc-hero/.kc-sub/.kc-foot`；网格 1 的 `.num-toggle` + `.dual-bar`；网格 2 的 `.mini-donut` + `.legend-mini`；网格 3 的 `.kc-spark`；网格 4 的 `.flip-card`（3D 翻转，`tabindex=0` 键盘可达） | 默认·悬停（上浮 2px + 边缘光泽）·聚焦 |
| 主舞台 | `.main-stage`（无边框） + `.stage-head/.stage-title` + `.glass-seg`（毛玻璃视角切换） + `.chart-toolbar` + `.trend-summary` | 默认·悬停·禁用（结构视角下 `seg-disabled`） |
| 排行侧栏 | `.agent-rail` + `.ar-entry/.ar-row`（grid 行）+ `.ar-spark`（悬停浮现）+ `.ar-detail`（0fr→1fr 展开）+ `.mrow`（模型明细） | 默认·悬停·展开（`aria-expanded`）·加载更多 |
| 展示类 | `.table-card`（**行卡片化**：`border-collapse: separate` + `border-spacing`，首末 `td` 圆角）、`.bar`（轨道 = 模型色 20%，标识头 = 100%）、`.daily-row` + `.daily-track`、`.t10-row`（单列）、`.donut-wrap`、`.chip`、`.agent-mono` | 加载（骨架）·空·错误 |
| 导航类 | `.slim-rail`（图标 + `.rail-tip` 悬停提示 + 选中指示条）、`#setNav`（横向选项卡）、`#tabbar`、`.pager`（页码 + 上一页/下一页） | 默认·悬停·当前（`aria-current`） |
| 反馈类 | `.upd-modal`（弹窗）、`.confirm-card`（危险操作确认）、`.toast`（轻提示）、`.collection-state`（数据状态条）、`.upd-notes`（**深色嵌板**：进度条 + Markdown 更新日志） | 出现·关闭·焦点陷阱·Esc 取消 |

数据区三态：**加载**用 `.skeleton`（骨架屏，不用转圈）；**空**用 `.empty`（图标 + 说明 + 行动按钮）；
**错误**用 `.collection-state[data-kind=error]` + toast 提供重试入口。

## 五、状态设计

- 加载：首屏 KPI 骨架 → 数据到达后替换；按钮 `aria-busy="true"` 显示内联转圈；图表空态覆盖 `#mainEmpty`。
- 空：图表/每日明细/表格/来源列表各有专属空态文案，并给出「查看全部时间」等下一步动作。
- 错误：`collection-state` 明确写出原因与影响（"已有结果保留"），并提供「重新读取结果」；
  设置视图内不重复展示扫描告警（`body[data-mode="settings"]` 下隐藏告警条）。
- 成功：导出、重新扫描、设置保存、主题切换都有 toast 反馈（`kind=success`）。
- **扫描真状态绑定**：重新扫描期间按钮禁用并显示真实耗时（"扫描中 Ns"），1s 轮询 `/api/settings`
  的 `busy` 直到完成后才恢复；已有扫描进行时不重复排队，直接等待其完成 —— 杜绝
  "按钮 1 秒恢复但数据没变"的假反馈。
- 断网/弱网：轮询失败时提示"暂时无法连接本地服务"，恢复后自动继续，手动重试入口常驻。

## 六、交互与动效（6 层动画系统）

- 时长：`--dur-instant 90ms` / `--dur-fast 140ms` / `--dur-base 200ms` / `--dur-slow 280ms`。
- 缓动：`--ease-standard`（控件）、`--ease-out`（进场）、`--ease-in-out`（位移）。

| 层 | 机制 | 实现 |
| --- | --- | --- |
| 1 视图切换 | Cross-fade & Scale：`opacity 0 + scale(.985)` → `1 + none` | `@keyframes view-in`（`layout.css`，`--dur-base var(--ease-out)`） |
| 2 网格错开入场 | 4 联 KPI、主舞台、底部双栏按 `--i` 依次滑入（55ms 步进） | `.bento-kpis.enter > *` / `.stage-grid.enter > *` / `.bottom-grid.enter > *`；`renderAll()` 重挂 `.enter` 触发重放 |
| 3 微交互反馈 | 按下位移 1px + **内部发光扩散**（Ripple 的极简 CSS 替代） | `.is-pressing` + `::after` 径向渐变（`.btn`/`.seg button`/`.glass-seg button`/`.t10-row`/`.ar-row`/`.set-item`） |
| 4 高度自适应 | Agent 明细展开用 `grid-template-rows: 0fr → 1fr` 平滑拉伸，替代瞬间插入 DOM | `.ar-detail`（展开时明细只渲染一次，之后靠类名切换） |
| 5 图表渲染流 | 主题切换触发 `tm:theme` 时，容器先降透明度再重绘，避免画布闪变 | `.chart-wrap.is-swapping` + `requestAnimationFrame` 内重建 MAIN/DONUT |
| 6 无障碍偏好 | `prefers-reduced-motion: reduce` 时全部过渡/动画归零，翻转改为瞬时状态切换 | `tokens.css` 时长归零 + `components.css` 末尾显式 `transition/animation: none` |

- 过渡：视图切换淡入缩放、菜单下拉、弹窗缩放淡入、骨架屏微光。
- 快捷键：`1`/`2` 切视图、`G` 设置、`/` 聚焦模型搜索、`R` 重新扫描、`Esc` 关弹层。
- 尊重系统：`prefers-reduced-motion: reduce` 时全部时长归零并关闭图表动画。

## 七、可访问性

- 键盘：所有交互元素可达（体检脚本逐个聚焦验证焦点环）；`skip-link` 直达主内容；分段控件（含毛玻璃视角切换）方向键切换；下拉 `↑/↓/Home/End/Esc`；资金卡 `tabindex=0` 可聚焦翻转。
- 焦点：`base.css` 统一定义 `:focus-visible` 焦点环（2px + 2px offset），焦点陷阱用于弹窗，关闭后焦点归还。
- 对比度：`tools/contrast_check.py` 校验全部「文字 token × 表面 token」组合，深浅两套主题均 **0 处不达标**（AA 正文标准）。
- 语义：`main`/`nav`/`header` landmark、`aria-current`、`aria-pressed`、`aria-expanded`、`aria-sort`、`aria-live` 播报、`role="img"` + `aria-label` 描述图表（迷你环形图每段带 `<title>`）。
- 不只靠颜色：错误/警告同时用图标、文字与边框；状态点带文字标签；占比条同时给出数值与百分比。
- 可缩放：字号使用 px 阶梯但布局全为弹性/网格，系统缩放 125%/150% 与浏览器缩放下不破版。

## 八、多端与多主题

- 主题三态：`跟随系统`（默认，不写 `data-theme`）、`浅色`、`深色`；顶栏按钮循环切换，设置页也可选；选择记入 `localStorage("tm-theme")`。
- 首帧不闪：`index.html` 内联脚本在样式表之前落地主题。
- 图表随主题：`charts.js` 用 `getComputedStyle` 读取 `--c1..--c9`；主题变化（`tm:theme` 事件）触发 MAIN/DONUT
  按新 token 重建，SVG sparkline 与表格占比条靠 `currentColor` / `var()` 自动适配；
  专项断言脚本 `tools/check_theme_chart.py` 实测两套主题的刻度/网格/tooltip 色全部跟随。
- 原生标题栏联动：主题变化时经 pywebview js_api（`Api.set_titlebar`）调用 DWM 同步 Windows 标题栏明暗；
  Win10 不支持上色时静默跳过。
- 平台差异：Windows 下滚动条自绘 10px；`.rail-top` 保留 52px 原生标题栏拖拽区。
- 高 DPI：图标用 SVG；位图徽标以 `object-fit: contain` 定尺寸，避免 125%/150% 模糊。

## 九、内容与文案

- 按钮文案：动词 + 对象（"重新扫描""导出 CSV""检查更新""更新并重启"）。
- 错误文案：说清"发生了什么 + 影响 + 怎么办"，例如
  「统计结果读取失败：读取失败（HTTP 500）；上次有效结果仍可查看。」
- 数字格式化统一走 `TMUI.fmt`：整数千分位、Token 用 B/M/k、金额 `¥` 两位小数、
  百分比一位小数、日期 `zh-CN` 区域、时间 `HH:mm`。
- 长文本：模型名/来源名 `text-overflow: ellipsis` + `title` 完整显示；
  错误描述 `overflow-wrap: anywhere` 防溢出。
- 本地化：界面为中文，`lang="zh-CN"`；数字/日期均通过 `Intl`，便于后续扩展语言。

## 十、性能体验

- 首屏：KPI 先出骨架；`/api/summary` 单请求拿全量聚合；KPI 四张卡由**一次遍历**取齐宏观口径
  （`heroTotals()`），四个渲染子函数共用，不做重复 reduce。
- **迷你走势零实例化**：排行榜与模型明细的走势图是**纯 SVG sparkline**（字符串直出、`currentColor` 取色），
  全站 Chart.js 实例恒定为 2 个（主趋势图 + 环形图）；此前几十个迷你 Chart 实例同时驻留导致的
  内存攀升与滚动掉帧已消除。
- 渲染分层：`renderHero()` 已拆为 `renderTotalTokenCard / renderCacheCard / renderApiCard / renderCostCard`，
  单卡改动不影响其余三张。
- 大数据量：模型表分页（25/50/100/全部，默认 50）+ 本地搜索（180ms 防抖）+ 表头排序 +
  **计费类型筛选**（全部 / 按量计费 / 套餐 / 未计价）；Agent 排行分批渲染（每批 12 条）；
  表格在自身滚动容器内滚动（`max-height: min(62vh, 720px)`），表头与动作栏吸顶。
- 资源：品牌图 `loading="lazy" decoding="async"`；单个 vendor 依赖（Chart.js）本地内置。
- 响应：切视图后 `requestAnimationFrame` 内重算画布尺寸；主题切换（`tm:theme` 事件）时
  MAIN/DONUT 按新 token 重建，SVG 走势靠 `currentColor` 自动换色。

## 十一、边界与异常

- 超长模型名：省略号 + `title`；超多数据：分页 + 分批渲染。
- 极端窗口：360px 起可用；超宽屏内容居中不拉伸。
- 重复提交：导出按钮在导出期间禁用；扫描按钮 `disabled` + `aria-busy`；轮询请求去重（`metaRequest`/`summaryRequest`）。
- 超时/失败：`fetch` 失败一律给出可见提示 + 重试入口；不静默吞错。

## 十二、安全与隐私（UI 层）

- 全部统计在本机完成，界面「关于」页明确写出：不上传任何用量数据，服务仅监听 127.0.0.1。
- 危险/不可逆操作二次确认：`TMUI.confirm()` 提供 `role="alertdialog"` + 焦点陷阱 + Esc 取消。
- 权限/不可用状态：无数据时按钮禁用并说明原因（如"尚不能导出"），不给出可点却无效的入口。
- 注入防护：所有插入 DOM 的文本经 `esc()` 转义（release notes 先转义再套结构）。

## 十三、可维护性

- 组件复用：按钮/输入/卡片/状态条/toast/弹窗/抽屉只有一处实现（`components.css` + `TMUI`）。
- token 集中：改一处全局生效；`tokens.css` 是唯一数值来源；JS 侧图表色一律经 `cssVar()` 解析，
  render.js/charts.js 中不允许出现界面配色字面量（品牌色字典除外）。
- 层叠可控：四层结构 + `@layer` 顺序明确；`!important` 集中在两处 —— `base.css` 的
  `[hidden]` 兜底与 `.sr-only`，以及 `components.css` 里 `prefers-reduced-motion` 的归零分支，
  均为可访问性必需且带注释说明。
- 历史样式：11 个旧样式表与合并产物 legacy.css 已从仓库移除（git 历史可回溯）；
  `styles.css` 保留 `@layer legacy` 占位与注释掉的 import，便于临时对比时恢复。
- 规范文档：本文件；组件属性见上文表格与 `components.css` 注释；实拍图由
  `tools/capture_spec_shots.py` 一键重生成。

---

## 附：多端与主题实拍

| 视图 | 截图 |
| --- | --- |
| 总览 · 深色（1440×900，整页） | ![总览·深色](shots/overview-dark.png) |
| 设置 · 浅色 | ![设置·浅色](shots/settings-light.png) |
| 模型用量 · 深色（卡片化表格 + 分页 + 排序） | ![模型用量](shots/models-dark.png) |
| 窄屏 390px（底部标签栏接管导航） | ![窄屏](shots/overview-mobile.png) |
| 改版前（对比用，保留历史） | ![改版前](shots/before-redesign.png) |

## 附：视觉标识（Bento 杂志化语言）

- 近黑画布（`#0B0D10`）+ 顶部两团极光（蓝主、橙辅）+ 极弱网格纹理；浅色主题为极淡同色氛围。
- 卡片用"浅一层的面"+ 极细描边 + 内高光，悬停给**边缘光泽 + 弥散阴影 + 上浮 2px**，而不是重描边堆叠。
- 排版驱动：先靠字号阶梯与字重拉层级，再考虑加线；分隔线退化为 `--hairline`。
- 语义色固定：Token=蓝、金额=暖橙、请求=薄荷绿、均值=紫、缓存=青。
- 数字一律 `font-variant-numeric: tabular-nums`，Bento 大数字用 `--fs-display` 阶梯 + 紧字距。
