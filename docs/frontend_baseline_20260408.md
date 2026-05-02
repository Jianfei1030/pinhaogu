# 前端基线文档 (2026-04-08)

> 文档用途：记录 Phase 32 前端改造前的完整基线状态，作为后续回退依据。

---

## 1. 文件清单总览

### 1.1 HTML 入口

| 文件 | 路径 | 状态 | 说明 |
|------|------|------|------|
| index.html | `workspace/static/index.html` | ✅ 活跃入口 | 唯一 HTML 入口，加载所有 JS/CSS |

### 1.2 CSS 文件

| 文件 | 路径 | 状态 | 说明 |
|------|------|------|------|
| variables.css | `workspace/static/css/variables.css` | ✅ 活跃 | CSS 变量定义（颜色、主题） |
| layout.css | `workspace/static/css/layout.css` | ✅ 活跃 | 布局、Tab 导航、状态栏、响应式基础 |
| components.css | `workspace/static/css/components.css` | ✅ 活跃 | 组件样式（面板、图表、按钮、表单） |
| responsive.css | `workspace/static/css/responsive.css` | ✅ 活跃 | 移动端/平板响应式适配 |

### 1.3 JS 文件

| 文件 | 路径 | 状态 | 说明 |
|------|------|------|------|
| state.js | `workspace/static/js/state.js` | ✅ 活跃 | 全局状态定义（COLORS、MA_COLORS、state 对象） |
| api.js | `workspace/static/js/api.js` | ✅ 活跃 | 数据获取函数（loadQuote、loadData、loadAlerts 等） |
| indicators.js | `workspace/static/js/indicators.js` | ✅ 活跃 | 技术指标计算 |
| chart-render.js | `workspace/static/js/chart-render.js` | ✅ 活跃 | K 线/MACD 图表渲染 |
| chart-interaction.js | `workspace/static/js/chart-interaction.js` | ✅ 活跃 | 图表交互（触摸、缩放、tooltip） |
| screener.js | `workspace/static/js/screener.js` | ✅ 活跃 | 选股面板逻辑 |
| alerts.js | `workspace/static/js/alerts.js` | ✅ 活跃 | 告警规则管理 |
| watchlist.js | `workspace/static/js/watchlist.js` | ✅ 活跃 | 监控股票列表侧边栏 |
| analysis.js | `workspace/static/js/analysis.js` | ✅ 活跃 | 每日板块分析面板 |
| news_v2.js | `workspace/static/js/news_v2.js` | ✅ 活跃 | 新闻系统统一入口（当前主入口） |
| main_fd_20260408.js | `workspace/static/js/main_fd_20260408.js` | ✅ 活跃 | 主入口 JS（当前主入口） |

### 1.4 历史/废弃 JS 文件（待清理）

| 文件 | 路径 | 状态 | 说明 |
|------|------|------|------|
| main.js | `workspace/static/js/main.js` | ⚠️ 旧版 | 旧主入口，功能与 main_fd_20260408.js 基本一致 |
| news.js | `workspace/static/js/news.js` | ⚠️ 旧版 | 旧新闻入口，已被 news_v2.js 替代 |
| news_fd_20260408.js | `workspace/static/js/news_fd_20260408.js` | ⚠️ 旧版 | news.js 的副本，内容相同 |
| test-only-initNewsToggle.js | `workspace/static/js/test-only-initNewsToggle.js` | ⚠️ 测试 | 测试用文件，非生产代码 |

---

## 2. 页面结构与 Tab 布局

### 2.1 Tab 结构

```
┌─────────────────────────────────────────────────────────────┐
│  📊 监控  │  📰 新闻  │  🔍 选股  │  📈 回测                    │  ← TabBar
├─────────────────────────────────────────────────────────────┤
│  🔴 已停止 · 已收盘  │  股票报价...  │  采集中  0条              │  ← StatusBar
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  [Tab 内容区]                                                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 各 Tab 功能

| Tab | ID | 主要功能 |
|-----|-----|----------|
| 监控 | `tabContentMonitor` | K 线图、MACD、告警规则、详情面板、侧边栏 |
| 新闻 | `tabContentNews` | 新闻列表、盘前分析、复盘分析 |
| 选股 | `tabContentScreener` | 板块筛选、条件筛选、选股结果表格 |
| 回测 | `tabContentBacktest` | 占位页面（"回测功能即将推出"） |

---

## 3. 关键 API 依赖清单

### 3.1 监控相关 API

| API | 方法 | 用途 |
|-----|------|------|
| `/api/config` | GET | 获取配置（监控股票列表、周期等） |
| `/api/quote/{symbol}` | GET | 获取实时报价 |
| `/api/kline` | GET | 获取 K 线数据 |
| `/api/monitor/status` | GET | 获取监控进程状态 |
| `/api/calibration/status` | GET | 获取数据源校准状态 |
| `/api/alerts` | GET/POST/PUT/DELETE | 告警规则 CRUD |
| `/api/alerts/test` | POST | 测试告警规则 |
| `/api/indicators` | GET | 获取技术指标配置 |

### 3.2 新闻相关 API

| API | 方法 | 用途 |
|-----|------|------|
| `/api/news/status` | GET | 获取新闻采集器状态 |
| `/api/news/recent` | GET | 获取最近新闻列表 |

### 3.3 分析相关 API

| API | 方法 | 用途 |
|-----|------|------|
| `/api/premarket/latest` | GET | 获取最新盘前分析报告 |
| `/api/premarket/report?date={date}` | GET | 获取指定日期盘前报告 |
| `/api/review/report?date={date}` | GET | 获取指定日期复盘报告 |
| `/api/analysis/status` | GET | 获取分析任务状态 |
| `/api/analysis/report` | GET | 获取分析报告 |
| `/api/analysis/daily` | POST | 触发每日分析 |

### 3.4 选股相关 API

| API | 方法 | 用途 |
|-----|------|------|
| `/api/screener/sectors` | GET | 获取板块列表 |
| `/api/screener/conditions` | GET | 获取选股条件配置 |
| `/api/screener/run` | POST | 执行选股 |

### 3.5 板块数据 API

| API | 方法 | 用途 |
|-----|------|------|
| `/api/board/snapshots` | GET | 获取板块快照 |
| `/api/board/stocks` | GET | 获取板块成分股 |
| `/api/board/history` | GET | 获取板块历史数据 |

---

## 4. 浮动按钮与面板

### 4.1 浮动按钮

| 按钮 | ID | 显示条件 | 位置 |
|------|-----|----------|------|
| 📋 切换股票 | `symbolToggleBtn` | 监控 Tab | 左下角 |
| 📊 每日分析 | `analysisToggleBtn` | 新闻 Tab | 右下角 |

### 4.2 浮动面板

| 面板 | ID | 触发方式 |
|------|-----|----------|
| 股票列表面板 | `symbolPanel` | 点击"切换股票"按钮 |
| 每日分析面板 | `analysisPanel` | 点击"每日分析"按钮 |

---

## 5. 技术债与现状问题记录

### 5.1 代码层面

| 问题 | 位置 | 严重程度 | 说明 |
|------|------|----------|------|
| 旧 JS 文件并存 | `js/main.js`, `js/news.js`, `js/news_fd_20260408.js` | 低 | 历史遗留，未被 index.html 引用但存在 |
| 页面标题偏旧 | `index.html` title | 低 | "港股监控验证页" → 应改为更通用名称 |
| CSS 版本号硬编码 | `index.html` 中 `?v=20260326001` | 低 | 需随更新手动修改 |
| JS 版本号硬编码 | `index.html` 中 `?v=202604081000` | 低 | 需随更新手动修改 |

### 5.2 功能层面

| 问题 | 位置 | 严重程度 | 说明 |
|------|------|----------|------|
| 回测 Tab 空白 | `tabContentBacktest` | 中 | 仅显示占位文字，无实际功能 |
| 新闻侧边栏 ID 不一致 | `index.html` | 低 | `monitorNewsList` vs `newsList` |
| 移动端侧边栏抽屉 | `responsive.css` | 低 | 存在 `.sidebar.open` 样式但无触发按钮 |

### 5.3 样式层面

| 问题 | 位置 | 严重程度 | 说明 |
|------|------|----------|------|
| 暗色主题对比度 | 全局 | 低 | 部分区域层次感可优化 |
| 状态栏信息密度 | `#statusBar` | 低 | 股票报价过长时可能溢出 |

---

## 6. JS 文件依赖关系

```
index.html
├── state.js (全局状态)
├── api.js (数据获取)
├── indicators.js (指标计算)
├── chart-render.js (图表渲染)
├── chart-interaction.js (图表交互)
├── screener.js (选股)
├── alerts.js (告警)
├── watchlist.js (监控列表)
├── analysis.js (板块分析)
├── news_v2.js (新闻 - 统一入口)
└── main_fd_20260408.js (主入口)
    ├── 依赖: state.js, api.js
    ├── 调用: news_v2.js 的 onNewsTabActivate
    └── 调用: news_v2.js 的 loadNews
```

---

## 7. 关键配置与常量

### 7.1 CSS 变量 (variables.css)

```css
--up: #e74c3c;           /* 上涨色 */
--down: #2ecc71;         /* 下跌色 */
--bg: #1a1a2e;           /* 背景色 */
--panel: #16213e;        /* 面板背景 */
--muted: #9aa5ce;        /* 次要文字 */
--border: #26304d;       /* 边框色 */
--ma5: #ffffff;          /* MA5 线色 */
--ma10: #f1c40f;         /* MA10 线色 */
--ma20: #9b59b6;         /* MA20 线色 */
--ma60: #1abc9c;         /* MA60 线色 */
```

### 7.2 JS 全局状态 (state.js)

```javascript
state = {
  config: null,              // 配置数据
  current: null,             // 当前 K 线数据
  calibration: null,         // 校准状态
  hoverIndex: -1,            // 鼠标悬停索引
  selectedIndex: -1,         // 选中索引
  watchQuotes: {},           // 监控股票报价
  currentQuote: null,        // 当前股票报价
  alerts: [],                // 告警规则列表
  visibleCount: 60,          // 可见 K 线数量
  dataOffset: 0,             // 数据偏移
  touch: {...},              // 触摸状态
}
```

---

## 8. 基线截图存档

> 注：基线截图应在浏览器中截取并保存至 `docs/screenshots/baseline_20260408/` 目录

建议截图清单：
- [ ] 监控 Tab - 桌面端 (1920px)
- [ ] 监控 Tab - 平板端 (768px)
- [ ] 监控 Tab - 移动端 (375px)
- [ ] 新闻 Tab - 桌面端
- [ ] 新闻 Tab - 移动端
- [ ] 选股 Tab - 桌面端
- [ ] 选股 Tab - 移动端
- [ ] 回测 Tab - 桌面端

---

## 9. 回退策略

如需回退到本基线状态：

1. **代码回退**：
   ```bash
   git checkout <commit-hash-before-phase32>
   ```

2. **文件恢复**：
   - 从本基线文档确认文件清单
   - 确保 `index.html` 引用的 JS/CSS 版本正确

3. **验证清单**：
   - [ ] 4 个 Tab 可正常切换
   - [ ] K 线图正常渲染
   - [ ] 告警规则可增删改查
   - [ ] 新闻列表正常加载
   - [ ] 选股功能正常
   - [ ] 浮动按钮正常显示/隐藏

---

## 10. 变更记录

| 日期 | 变更 | 作者 |
|------|------|------|
| 2026-04-08 | 创建基线文档 | 股子 |

---

*文档版本: v1.0 | 基线冻结日期: 2026-04-08*
