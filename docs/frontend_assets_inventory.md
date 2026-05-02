# 前端资产清单 (2026-04-08)

> 详细列出所有前端文件，标记活跃/废弃状态，用于 Phase 32 改造参考。

---

## 目录结构

```
workspace/static/
├── index.html                    # 唯一 HTML 入口
├── css/
│   ├── variables.css            # CSS 变量定义
│   ├── layout.css               # 布局、Tab、状态栏
│   ├── components.css           # 组件样式
│   └── responsive.css           # 响应式适配
└── js/
    ├── state.js                 # 全局状态
    ├── api.js                   # 数据获取
    ├── indicators.js            # 技术指标
    ├── chart-render.js          # 图表渲染
    ├── chart-interaction.js     # 图表交互
    ├── screener.js              # 选股面板
    ├── alerts.js                # 告警管理
    ├── watchlist.js             # 监控列表
    ├── analysis.js              # 板块分析
    ├── news_v2.js               # 新闻系统 (活跃入口)
    ├── main_fd_20260408.js      # 主入口 (活跃入口)
    ├── main.js                  # 旧主入口 (废弃)
    ├── news.js                  # 旧新闻入口 (废弃)
    ├── news_fd_20260408.js      # 旧新闻副本 (废弃)
    └── test-only-initNewsToggle.js  # 测试文件 (废弃)
```

---

## 资产详情

### HTML (1 个)

| # | 文件名 | 大小 | 最后修改 | 状态 | 引用位置 |
|---|--------|------|----------|------|----------|
| 1 | index.html | ~15KB | 2026-04-08 | ✅ 活跃 | 浏览器入口 |

**index.html 引用的 CSS (按加载顺序):**
1. `variables.css?v=20260326001`
2. `layout.css?v=20260326001`
3. `components.css?v=20260326001`
4. `responsive.css?v=20260326001`

**index.html 引用的 JS (按加载顺序):**
1. `state.js?v=202604081000`
2. `api.js?v=202604081000`
3. `indicators.js?v=202604081000`
4. `chart-render.js?v=202604081000`
5. `chart-interaction.js?v=202604081000`
6. `screener.js?v=202604081000`
7. `alerts.js?v=202604081000`
8. `watchlist.js?v=202604081000`
9. `analysis.js?v=202604081000`
10. `news_v2.js?v=202604081000` ← 新闻统一入口
11. `main_fd_20260408.js?v=202604081000` ← 主入口

---

### CSS (4 个)

| # | 文件名 | 行数 | 状态 | 主要用途 |
|---|--------|------|------|----------|
| 1 | variables.css | ~45 | ✅ 活跃 | CSS 变量（颜色、主题） |
| 2 | layout.css | ~200 | ✅ 活跃 | Tab 导航、状态栏、布局框架 |
| 3 | components.css | ~350 | ✅ 活跃 | 面板、图表、按钮、表单、告警 |
| 4 | responsive.css | ~280 | ✅ 活跃 | 移动端/平板适配 |

**CSS 变量清单:**
```css
--up, --down              /* 涨跌颜色 */
--bg, --panel, --panel-2  /* 背景色 */
--text, --muted           /* 文字颜色 */
--border, --grid          /* 边框/网格 */
--dif, --dea              /* MACD 线色 */
--hist-up, --hist-down    /* MACD 柱色 */
--ma5, --ma10, --ma20, --ma60  /* MA 线色 */
```

---

### JS - 活跃文件 (11 个)

| # | 文件名 | 行数 | 状态 | 主要职责 | 依赖 |
|---|--------|------|------|----------|------|
| 1 | state.js | ~90 | ✅ 活跃 | 全局状态、常量定义 | 无 |
| 2 | api.js | ~200 | ✅ 活跃 | 数据获取 API | state.js |
| 3 | indicators.js | ~50 | ✅ 活跃 | 技术指标计算 | state.js |
| 4 | chart-render.js | ~300 | ✅ 活跃 | K线/MACD渲染 | state.js, indicators.js |
| 5 | chart-interaction.js | ~250 | ✅ 活跃 | 图表交互 | state.js, chart-render.js |
| 6 | screener.js | ~180 | ✅ 活跃 | 选股面板 | api.js |
| 7 | alerts.js | ~280 | ✅ 活跃 | 告警管理 | state.js, api.js |
| 8 | watchlist.js | ~80 | ✅ 活跃 | 监控列表 | state.js, api.js |
| 9 | analysis.js | ~150 | ✅ 活跃 | 板块分析 | api.js |
| 10 | news_v2.js | ~350 | ✅ 活跃 | 新闻系统 | api.js |
| 11 | main_fd_20260408.js | ~350 | ✅ 活跃 | 主入口、Tab切换 | 所有以上 |

**JS 依赖关系图:**
```
state.js (基础层)
  └── api.js (数据层)
        ├── indicators.js
        ├── chart-render.js
        │     └── chart-interaction.js
        ├── screener.js
        ├── alerts.js
        ├── watchlist.js
        ├── analysis.js
        └── news_v2.js
              └── main_fd_20260408.js (入口层)
```

---

### JS - 废弃/历史文件 (4 个)

| # | 文件名 | 行数 | 状态 | 废弃原因 | 处理建议 |
|---|--------|------|------|----------|----------|
| 1 | main.js | ~350 | ⚠️ 废弃 | 功能已合并到 main_fd_20260408.js | T32.8 移入 legacy/ |
| 2 | news.js | ~300 | ⚠️ 废弃 | 功能已合并到 news_v2.js | T32.8 移入 legacy/ |
| 3 | news_fd_20260408.js | ~300 | ⚠️ 废弃 | news.js 的副本，内容相同 | T32.8 移入 legacy/ |
| 4 | test-only-initNewsToggle.js | ~20 | ⚠️ 废弃 | 测试用临时文件 | T32.8 删除 |

**废弃文件对比:**

```bash
# main.js vs main_fd_20260408.js
# 差异: main_fd_20260408.js 增加了:
# - updateFloatingButtons() 函数
# - 新闻 Tab 切换时调用 onNewsTabActivate()
# - 移除了 loadRecentNews() 调用（由 news_v2.js 接管）

# news.js vs news_v2.js
# 差异: news_v2.js 重构为:
# - 统一的 NewsState 状态管理
# - 清晰的 fetchNewsData / renderSidebarNews / renderNewsTab 分离
# - 明确的 onNewsTabActivate 回调
# - 移除了冗余的 initNewsTab 自动执行
```

---

## 文件大小统计

| 类别 | 文件数 | 估算总大小 |
|------|--------|-----------|
| HTML | 1 | ~15 KB |
| CSS | 4 | ~25 KB |
| JS (活跃) | 11 | ~220 KB |
| JS (废弃) | 4 | ~100 KB |
| **总计** | **20** | **~360 KB** |

---

## 版本号管理

当前使用的版本号标记：

| 类型 | 当前版本 | 最后更新 | 更新场景 |
|------|----------|----------|----------|
| CSS | `?v=20260326001` | 2026-03-26 | CSS 文件变更 |
| JS | `?v=202604081000` | 2026-04-08 | JS 文件变更 |

---

## 后续改造建议

### T32.2 (页面骨架刷新)
- 修改 `index.html` 标题
- 更新 `variables.css` 配色
- 刷新 `layout.css` 状态栏样式

### T32.3 (监控 Tab 优化)
- 修改 `components.css` 图表卡片样式
- 优化 `chart-render.js` 渲染逻辑
- 保持 `alerts.js` 数据结构不变

### T32.4 (新闻 Tab 优化)
- 优化 `news_v2.js` 样式渲染
- **T32.8 清理旧文件**: `main.js`, `news.js`, `news_fd_20260408.js`

### T32.5 (选股 Tab 优化)
- 修改 `screener.js` 结果表格样式
- 更新回测 Tab 占位内容

### T32.6 (响应式优化)
- 修改 `responsive.css` 移动端适配
- 优化 `main_fd_20260408.js` 触摸交互

---

## 变更记录

| 日期 | 变更 | 作者 |
|------|------|------|
| 2026-04-08 | 创建资产清单 | 股子 |

---

*文档版本: v1.0 | 盘点日期: 2026-04-08*
