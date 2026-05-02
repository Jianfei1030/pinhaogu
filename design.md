# 股票实时监控系统 — 设计文档

---

## 架构重构说明（2026-04）

> 描述 stock-monitor 项目的架构优化方向和分阶段重构计划。

### 当前架构的主要问题

1. **顶层脚本过多，职责混杂**
   - `workspace/` 目录下存在大量顶层脚本（`monitor.py`, `server.py`, `premarket_analysis.py`, `postmarket_review.py` 等）
   - 入口脚本、库模块、一次性工具混在同一层级
   - 新成员难以快速识别"哪个是主入口"、"哪个是库"

2. **配置层尚未完全成为单一真相源**
   - `config.yaml` 与 `config.py` 并存，部分配置硬编码在脚本中
   - Telegram/QQ 推送配置分散在多个脚本

3. **任务脚本入口风格不统一**
   - 有些脚本是 `if __name__ == "__main__"` 入口
   - 有些脚本被 `server.py` 直接 import 并调用
   - 缺少统一的 Job Runner 形态

4. **`server.py` 责任偏重**
   - 50KB+ 代码量，承担路由、业务逻辑、状态管理、外部通知等多重职责
   - API 路由与业务逻辑耦合，难以单独测试

### 目标形态

**继续走模块化单体，不上微服务**：
- 保持单一进程部署，降低运维复杂度
- 通过清晰的分层和模块边界实现可维护性

**顶层脚本逐步变成 thin wrapper**：
- 只负责：加载配置、调用对应的 service / job、处理退出码和异常
- 真实业务逻辑下沉到分层模块中

**真实逻辑下沉到清晰分层**：
```
workspace/
├── jobs/           # 任务入口（Job Runner 形态）
├── api/            # API 路由层（轻量）
│   ├── routes/
│   └── server.py   # FastAPI 应用入口
├── services/       # 业务逻辑层（核心）
│   ├── market_data_service.py
│   ├── alert_service.py
│   ├── analysis_service.py
│   ├── push_service.py
│   └── calendar_service.py
├── adapters/       # 外部系统适配层
│   ├── data_sources/
│   ├── push_channels/
│   └── llm/
├── persistence/    # 数据持久化层
├── indicators/     # 指标计算（保持现有）
├── config/         # 配置层（单一真相源）
└── ... (顶层脚本逐步迁移)
```

### 重构优先级（分阶段）

**Phase 1: 任务脚本统一为 Job Runner 形态**
- 创建 `jobs/` 目录
- 将 `monitor.py`, `premarket_analysis.py`, `postmarket_review.py` 等改造为 Job Runner 形态
- 验证点：三件套启动正常、cron 任务正常触发、推送功能正常

**Phase 2: 配置层升级为单一真相源**
- 统一 `config.yaml` + `config_manager.py` 为唯一配置入口
- 移除硬编码配置
- 验证点：修改 `config.yaml` 后所有脚本生效、无硬编码配置残留

**Phase 3: `server.py` 拆 router + service**
- 将 `server.py` 中的业务逻辑提取到 `services/` 层
- API 路由层只负责请求参数验证、调用 service、返回响应
- 验证点：所有 API 端点正常、前端页面正常加载

**Phase 4: 横切能力继续沉淀为 service**
- 推送能力统一为 `push_service.py`（支持 Telegram / QQ 双通道）
- LLM 调用统一为 `llm_service.py`
- 交易日历/节假日保护统一为 `calendar_service.py`
- 验证点：推送功能正常、节假日保护逻辑正常

**Phase 5: 顶层脚本逐步收口（软迁移）**
- 将顶层脚本逐步迁移到 `jobs/` 目录
- 旧脚本保留但标记为 `@deprecated`
- 逐步更新 cron 任务指向新 Job

### 明确先不做什么

- **不上微服务** — 不拆分独立进程，不引入服务间 HTTP/RPC 调用
- **不急着换 SQLite** — 保持当前 DB 文件结构
- **不一口气全目录搬迁** — 采用渐进式迁移，每步迁移后验证功能正常

### 每步都要验证

**最小验证集**（每阶段至少覆盖）：
- 三件套启动正常
- 关键 API 正常（健康检查、股票列表、板块列表）
- dry-run 模式正常
- 节假日保护逻辑正常
- 核心分析流程正常

---

## 数据源策略

### 概念板块数据

| 数据源 | 用途 | 数量 | 状态 |
|--------|------|------|------|
| **同花顺** `stock_board_concept_name_ths()` | 板块列表 | 375 个 | ✅ 主源 |
| **东财** `stock_board_concept_cons_em()` | 成分股 | ~250 只/板块 | ✅ 优先 |
| **同花顺** `fetch_board_stocks_by_code()` | 成分股 | ~50 只/板块 | ✅ Fallback |

### 个股实时行情

| 数据 | 第一源 | Fallback |
|------|--------|----------|
| 港股分钟线 | 东财 `stock_hk_hist_min_em` | yfinance `XXXX.HK` |
| 港股日线 | 东财 `stock_hk_hist` | — |
| A 股分钟线 (5/15/30/60) | 东财 | 新浪 `stock_zh_a_minute` |
| A 股 120min | 东财 | 无替代 |
| A 股日线 | 东财 | 腾讯 `stock_zh_a_hist_tx` |
| 港股指数日线 | 新浪 `stock_hk_index_daily_sina` | — |
| 实时行情 | 新浪 `hq.sinajs.cn` | 东财直连 HTTP |

### 数据源实测结论

2026-03-25 实测了 8 种免费数据源，结论：

- **东方财富直连 HTTP**：行情新鲜度 ~2 秒，稳定性 3/3，推荐做主源
- **同花顺 realhead**：响应 22~33ms，数据 ~20 秒级延迟，适合做备源
- **TradingView**：延迟 900 秒（15 分钟），不适合实时
- **akshare**：本机环境下不稳定，不建议做主链路
- **yfinance**：适合历史数据回填（60 天/2 年/全历史）

> 详见：[数据源实测报告](#附录 a-数据源实测报告)

---

## 数据流

```
腾讯 1 分钟线 → 聚为 5/15/30/60min K 线 → SQLite 持久化
                                        ↓
东财分钟线 → MACD 指标计算 → 告警检测 → Telegram + QQ 推送
                                        ↓
盘前分析 (08:47) / 盘后复盘 (21:30) / 数据补全 (17:30 & 21:30)
```

## K 线聚合规则（东财对齐）

标签 = bar 结束时间，Close = 标签分钟的 1 分钟线价格。

**15 分钟:**
- :01~:15 → :15, :16~:30 → :30, :31~:45 → :45, :46~:59/:00 → 下一小时:00

**30 分钟:**
- :01~:30 → :30, :31~:59/:00 → 下一小时:00

**120 分钟:**
- 从 60min 两两聚合：open=第一根的 open, high=两根 max, low=两根 min, close=第二根的 close, volume=两根相加

## 数据库设计

### 文件路径结构

```
data/
├── HK/                          # 港股
│   ├── HK01810/                 # 小米集团
│   │   ├── YYYYMMDD.db          # 按交易日一个数据库
│   │   └── ...
│   └── ...
├── A/                           # A 股
│   ├── A603986/
│   └── ...
└── hk_index_{symbol}/           # 港股指数（如 HSTECH）
```

### 表结构

每个 db 内部：

| 表名 | 说明 | bar_time 格式 |
|------|------|--------------|
| kline_1min | 1 分钟原始数据 | `09:30` |
| kline_5min | 5 分钟聚合 | `09:35` |
| kline_15min | 15 分钟聚合 | `09:45` |
| kline_30min | 30 分钟聚合 | `10:00` |
| kline_60min | 60 分钟聚合 | `10:00` |
| kline_120min | 120 分钟（从 60min 聚合） | — |
| kline_1d | 日线 | `YYYY-MM-DD` |

技术指标按级别存储在 indicators 表中。

---

## 系统架构

## 模块清单

| 模块 | 文件 | 功能 |
|------|------|------|
| 实时监控 | monitor.py | 每 tick 拉 K 线 → MACD → DB → 告警 |
| Web 服务 | server.py | FastAPI 端口 18805（可配置）|
| 新闻采集 | daily_news_collector.py | 5 源 + Qwen3-Embedding 4B 去重 |
| 盘前分析 | premarket_analysis.py | 375 板块 → LLM 推荐 → 成分股筛选 → 筹码计算 |
| 盘后复盘 | postmarket_review.py | 对比预测 vs 实际 → LLM 复盘 |
| 状态检测 | status_report.py | 进程健康检查（10:00-20:00 每小时） |
| 筹码分布 | calc_chip_dist.py | yfinance 90 天日线模拟筹码 |

---

## 架构重构说明

> 详见 `ARCHITECTURE_NEXT.md`

### 当前架构的主要问题

**1. 顶层脚本过多，职责混杂**
- `workspace/` 目录下存在大量顶层脚本（`monitor.py`, `server.py`, `premarket_analysis.py` 等）
- 入口脚本、库模块、一次性工具混在同一层级，难以区分
- 新成员难以快速识别"哪个是主入口"、"哪个是库"

**2. 配置层尚未完全成为单一真相源**
- `config.yaml` 与 `config.py` 并存，部分配置硬编码在脚本中
- Telegram/QQ 推送配置分散在多个脚本
- 数据路径、API 端点等配置未完全统一

**3. 任务脚本入口风格不统一**
- 有些脚本是 `if __name__ == "__main__"` 入口
- 有些脚本被 `server.py` 直接 import 并调用
- 有些脚本通过 cron 直接执行 shell 脚本
- 缺少统一的 Job Runner 形态

**4. `server.py` 责任偏重**
- 50KB+ 代码量，承担路由、业务逻辑、状态管理、外部通知等多重职责
- API 路由与业务逻辑耦合，难以单独测试
- 前端静态文件服务与后端 API 混在一起

**5. 横切能力还在继续收口中**
- 推送能力（Telegram / QQ）分散在多个脚本
- LLM 调用（Ollama）嵌入在业务逻辑中
- 交易日历/节假日保护逻辑分散
- 运行时状态管理不统一

### 推荐目标形态

**继续走模块化单体，不上微服务**
- 保持单一进程部署，降低运维复杂度
- 通过清晰的分层和模块边界实现可维护性
- 不引入 HTTP/RPC 服务间调用

**顶层脚本逐步变成 thin wrapper**
- 顶层脚本只负责：加载配置、调用对应的 service / job、处理退出码和异常
- 真实业务逻辑下沉到分层模块中

**目标目录结构**：
```
workspace/
├── jobs/           # 任务入口（Job Runner 形态）
├── api/            # API 路由层（轻量）
├── services/       # 业务逻辑层（核心）
├── adapters/       # 外部系统适配层
├── persistence/    # 数据持久化层
├── indicators/     # 指标计算（保持现有）
├── config/         # 配置层（单一真相源）
└── ... (顶层脚本逐步迁移)
```

### 重构优先级

按以下顺序分阶段执行，**每阶段完成后必须验证功能正常**：

**Phase R1: 任务脚本统一为 Job Runner 形态**
- 创建 `jobs/` 目录
- 将 `monitor.py`, `premarket_analysis.py`, `postmarket_review.py` 等改造为 Job Runner 形态
- 每个 Job 只负责：加载配置、调用对应的 service、处理异常和退出码
- **验证点**：后台四件套启动正常（含 Ollama）、cron 任务正常触发、推送功能正常

**Phase R2: 配置层升级为单一真相源**
- 统一 `config.yaml` + `config_manager.py` 为唯一配置入口
- 移除硬编码配置（Telegram token、QQ target、数据路径等）
- 所有脚本通过 `config_manager` 加载配置
- **验证点**：修改 `config.yaml` 后所有脚本生效、无硬编码配置残留

**Phase R3: `server.py` 拆 router + service**
- 将 `server.py` 中的业务逻辑提取到 `services/` 层
- API 路由层只负责：请求参数验证、调用 service、返回响应
- **验证点**：所有 API 端点正常、前端页面正常加载

**Phase R4: 横切能力继续沉淀为 service**
- 推送能力统一为 `push_service.py`（支持 Telegram / QQ 双通道）
- LLM 调用统一为 `llm_service.py`
- 交易日历/节假日保护统一为 `calendar_service.py`
- 运行时状态统一为 `state_service.py`
- **验证点**：推送功能正常、节假日保护逻辑正常、LLM 调用正常

**Phase R5: 顶层脚本逐步收口（软迁移）**
- 将顶层脚本逐步迁移到 `jobs/` 目录
- 旧脚本保留但标记为 `@deprecated`
- 逐步更新 cron 任务指向新 Job
- **验证点**：新旧脚本并行运行正常、cron 切换后功能正常

### 明确先不做什么

- **不上微服务** — 不拆分独立进程，不引入服务间 HTTP/RPC 调用
- **不急着换 SQLite** — 保持当前 DB 文件结构，不迁移数据库引擎
- **不一口气全目录搬迁** — 采用渐进式迁移，保持新旧代码并行运行

### 每步验证原则

**验证原则**：
- 每完成一个阶段，必须做功能验证
- 验证通过后再进入下一阶段
- 验证失败则回滚并修复

**最小验证集**（每阶段至少覆盖）：
| 验证项 | 说明 |
|--------|------|
| 四件套启动 | `monitor.py` / `premarket_analysis.py` / `postmarket_review.py` 正常启动，Ollama 依赖可用 |
| 关键 API | 健康检查、股票列表、板块列表 API 正常 |
| dry-run | 所有支持 dry-run 的脚本正常 |
| 节假日保护 | 非交易日不触发告警、不推送 |
| 核心分析流程 | 盘前分析 → 成分股筛选 → 筹码计算 → 推送 全流程正常 |

**风险控制**：
- 每阶段改动控制在可回滚范围内
- 保持新旧代码并行运行
- 不删除旧代码，只标记 `@deprecated`
- 验证失败则立即回滚到上一阶段

---

## 推送系统

| 渠道 | 账号 | 方式 |
|------|------|------|
| Telegram | stock bot (`8624013562`) | Bot API `requests.post` |
| QQ | guzi (股子) | `openclaw message send --channel qqbot --account guzi` |

已集成 QQ 推送：monitor / premarket / postmarket / status_report / daily_sector_pipeline

## 筹码分布

- **数据源**: yfinance 90 天日线
- **算法**: 模拟筹码衰减（每日换手率 ≈ 2%）
- **指标**: profit_ratio（获利比例 0-1）/ avg_cost（平均成本）/ concentration_90（90% 集中度）
- **盘前应用**: 成分股三重筛选 — 换手>3% → 成交额>3 亿 → 获利>50%

## Embedding 模型

| 模型 | 参数 | 维度 | 用途 |
|------|------|------|------|
| **Qwen3-Embedding 4B** | 4B | 2560 | ✅ 新闻去重主力 |
| bge-m3 | 567M | 1024 | ✅ 保留备用 |

## 指标引擎架构（可扩展）

```python
class IndicatorBase:
    name: str
    def calc(self, df: pd.DataFrame) -> pd.Series: ...

class MACD(IndicatorBase):
    def __init__(self, fast=12, slow=26, signal=9): ...

engine = IndicatorEngine()
engine.register(MACD(fast=12, slow=26, signal=9))
results = engine.calc_all(df)  # 返回所有指标
```

| 指标 | 参数 | Phase |
|------|------|-------|
| MACD | 12,26,9 | Phase 1 |
| MA | 5/10/20/60 | Phase 3 |
| RSI | 14 | Phase 3 |
| KDJ | 9,3,3 | Phase 3 |
| BOLL | 20,2 | Phase 4 |
| ATR | 14 | Phase 4 |

## Cron 任务

| 时间 | 任务 |
|------|------|
| 周一至五 08:47 | 盘前分析 |
| 周一至五 21:30 | 盘后复盘 |
| 10:00-20:00 每小时 | 进程健康检查 |

## API 端点

| 端点 | 说明 |
|------|------|
| `GET /` | Web 前端 |
| `GET /api/kline` | K 线 + MACD |
| `GET /api/quote/{symbol}` | 实时行情 |
| `GET /api/monitor/status` | 监控状态 |
| `GET /api/premarket/report` | 盘前报告 |
| `GET /api/review/report` | 盘后复盘报告 |
| `GET /api/board/snapshots` | 板块快照 |
| `GET /api/screener/run` | 执行选股 |

---

## 前端设计评审

### 页面问题与优化（2026-03-25）

| 优先级 | 问题 | 方案 |
|--------|------|------|
| P0 | 股票信息区空间浪费 | 一行化：`01810  32.520  ↑0.31%  已矫正` |
| P1 | 告警规则区域臃肿 | 每条 80px→40px，条件文字缩略 |
| P1 | MACD 标题误导 | 改为「详情」 |
| P1 | 数据不足警告太刺眼 | 改为 K 线图右上角小标签 |
| P2 | 详情面板+MACD 信息重复 | 合并为 `DIF 0.003↗  DEA -0.062↘  Hist 0.130↗` |

---

## 移动端适配

### 断点体系

| 断点 | 范围 | 说明 |
|------|------|------|
| ≥ 1100px | 桌面端 | 保持不变 |
| 768–1099px | 平板端 | 侧栏收起为主，图表缩放 |
| < 768px | 手机端 | 全面重构布局，抽屉式侧栏 |

### 核心方案

- **侧栏**：CSS 抽屉式（固定定位 + transform）
- **K 线图**：高度缩减（260px），减少可见蜡烛数（60→30）
- **触摸交互**：单指拖拽平移、双指缩放、hover 映射为 touchstart
- **Canvas**：devicePixelRatio 适配防止 Retina 模糊
- **面板**：分析面板全屏、弹窗全屏、选股底部抽屉

> 完整 CSS 代码见 [mobile-adaptation-report](#附录 b-移动端适配完整报告)

---

## 附录 A：数据源实测报告

### 8 种数据源实测对比（2026-03-25）

| 数据源 | 响应 | 行情新鲜度 | 稳定性 | 结论 |
|---|---|---|---|---|
| 东方财富直连 | ~170-250ms | **~2 秒** | 3/3 | ✅ **推荐主源** |
| 同花顺 realhead | 22-33ms | ~20 秒 | 3/3 | ✅ 适合备源 |
| TradingView | ~450ms | 900 秒延迟 | 3/3 | ❌ 不适合实时 |
| akshare | — | — | 0/1 | ❌ 跑不通 |
| Futu | — | — | 0/1 | ❌ 网络不可用 |
| pytdx | ~5008ms 超时 | — | 0/1 | ❌ 接失败 |

### 东财直连接口示例
```
https://push2.eastmoney.com/api/qt/stock/get?secid=116.01810&fields=f43,f57,f58,f60,f86,f169,f170
```
字段：f43=最新价 (/1000)、f60=昨收 (/1000)、f86=秒级时间戳

### 东财分钟接口
```
https://push2his.eastmoney.com/api/qt/stock/trends2/get?secid=116.01810&ndays=5&fields2=f51,f52,f53,f54,f55,f56,f57,f58
```
返回真正的 OHLC + 成交量 + 成交额，适合替代 fetch_1min。

## 附录 B：动端适配完整报告

### Canvas 适配要点

**高清屏处理**：
```javascript
function setupCanvas(canvas, cssWidth, cssHeight) {
  const dpr = window.devicePixelRatio || 1;
  canvas.width = cssWidth * dpr;
  canvas.height = cssHeight * dpr;
  canvas.style.width = cssWidth + 'px';
  canvas.style.height = cssHeight + 'px';
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  return ctx;
}
```

**触摸事件映射**：
| 桌面端 | 移动端 | 功能 |
|--------|--------|------|
| mouseover | touchstart | 显示 tooltip |
| mousemove | touchmove | 跟随更新 |
| mouseout | touchend | 隐藏 tooltip |
| wheel | touchstart(双指) | 缩放 K 线范围 |
| - | touchstart(单指拖拽) | 平移历史数据 |

### CSS 断点策略

**平板端**: `@media (768px – 1099px)` — 侧栏横向、图表略缩
**手机端**: `@media (< 768px)` — 抽屉侧栏、全屏面板、Canvas 缩减

### 风险控制

| 风险 | 规避 |
|------|------|
| 桌面端被破坏 | 所有手机端样式在 `@media` 内 |
| Canvas 性能 | requestAnimationFrame 节流 |
| z-index 冲突 | 侧栏 500 / 分析面板 600 |
| 页面滚动 | `touch-action: none` + `passive: false` |

> 此报告源自 `mobile-adaptation-report.md`（2026-03-25），完整 CSS 代码已实施到前端。

---

*最后更新：2026-04-07（合并 ARCHITECTURE_NEXT.md 架构重构说明）*

---

## thesis-ingest 设计

### 题材写入技能 — 设计文档

> 版本：2.1
> 创建日期：2026-04-09
> 最后更新：2026-04-17

---

#### 1. 系统架构

```
input_images/*.jpg
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  process_thesis_image.py  (一键编排，6 步管道)               │
│  输出归档到 output/{题材名}/，每次运行清空重建               │
│                                                             │
│  Step 1: plan_semantic_cuts.py                              │
│    - OpenCV 红色水平线检测 → 定位切割边界                    │
│    - 多模态模型识别根题材 + 一级子题材名称                   │
│    - 输出: cut_plan.json                                    │
│                                                             │
│  Step 2: split_by_path_plan.py                              │
│    - 按切割方案裁剪原图为 segment PNG                       │
│    - 输出: segments/segment_01..N.png + manifest.json       │
│                                                             │
│  Step 3: parse_path_segments_mm.py                          │
│    - 4 路并发多模态解析每个 segment                         │
│    - 每个 segment 最多 3 次尝试（含重试）                    │
│    - 失败则终止整个流程（fail-fast）                        │
│    - 支持 --model qwen|copilot 切换模型                     │
│    - 支持 --root-name 告知模型根题材                        │
│    - 输出: segment_parse.json                               │
│                                                             │
│  Step 4: expand_path_ancestors.py                           │
│    - 展开层级路径为祖先候选（纯 JSON 变换）                 │
│    - 输出: ancestor_candidates.json                         │
│                                                             │
│  Step 5: insert_thesis_tree.py                              │
│    - 构建树结构，BFS 分配 node_id                           │
│    - 通过 workspace 的 stock_lookup_service 查找股票代码     │
│    - 写入 SQLite: thesis_catalog + thesis_tree_{md5} +      │
│      thesis_stocks_tree_{md5}                               │
│    - 自动调 LLM 生成根题材 + 子题材描述                     │
│                                                             │
│  Step 6: verify_thesis_report.py                            │
│    - 从数据库回读完整树结构                                 │
│    - 生成 Markdown 校验报告（层级缩进 + 成分股 + 描述）     │
│    - 失败不终止流程（仅报告）                               │
│    - 输出: verify_report.md                                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
  thesis.db (SQLite) + output/{题材名}/ 下所有文件
```

---

#### 2. 红色水平线检测（plan_semantic_cuts.py）

##### 2.1 原理

开盘啦 APP 中每个一级子题材之间有横跨全宽的红色分隔线（RGB ≈ [255, 0, 0]）。通过 OpenCV 对红色像素做水平投影，找到 y 坐标上红色像素密度最高的行，即为分界线。

##### 2.2 关键参数

| 参数 | 值 | 说明 |
|------|-----|------|
| `top_skip_ratio` | 0.10 | 跳过顶部 APP 标题栏（占图片高度 10%） |
| `bottom_skip_px` | 50 | 跳过底部 UI（固定 50 像素） |

**为什么 `bottom_skip_px` 用固定像素而非比例**：用户会对原始长截图进行裁切，裁切后图片高度差异大。如果用比例（如 5%），在矮图上会过滤掉有效的红线。固定 50 像素只过滤底部 UI 按钮区域。

##### 2.3 名称匹配

多模态模型只负责列出根题材和一级子题材的名称（不猜坐标）。管道将红色分界线作为 segment 边界，再把模型给出的名称依次匹配上去。

---

#### 3. 数据库设计（v2 树状结构）

每张原始截图 → `thesis_catalog` 一行 + 一对动态表。

##### 3.1 thesis_catalog（题材总目录）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER | 主键 |
| `image_name` | TEXT UNIQUE NOT NULL | 根题材名，如 "AI 硬件" |
| `source_image` | TEXT | 原始截图文件名 |
| `description` | TEXT | 题材描述 |
| `total_stock_count` | INTEGER | 总成分股数 |
| `node_count` | INTEGER | 总节点数（不含股票） |
| `created_at` | TEXT | 创建时间 |
| `updated_at` | TEXT | 更新时间 |

##### 3.2 thesis_tree_{md5[:8]}（树节点表）

| 字段 | 类型 | 说明 |
|------|------|------|
| `node_id` | INTEGER | 主键，BFS 顺序分配 |
| `parent_id` | INTEGER FK | 父节点 ID，NULL = 根节点 |
| `node_name` | TEXT NOT NULL | 节点名 |
| `node_type` | TEXT CHECK | 'root' / 'first_level' / 'second_level' |
| `depth` | INTEGER | 0=根, 1=一级, 2=二级 |
| `description` | TEXT | 题材描述 |
| `full_path` | TEXT UNIQUE | "AI 硬件 / 光模块 / CPO" |
| `sort_order` | INTEGER | 排序 |
| `created_at` | TEXT | 创建时间 |
| `updated_at` | TEXT | 更新时间 |

##### 3.3 thesis_stocks_tree_{md5[:8]}（成分股表）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER | 主键 |
| `node_id` | INTEGER FK | 关联树节点 |
| `stock_code` | TEXT NOT NULL | 6 位股票代码 |
| `stock_name` | TEXT NOT NULL | 股票名称 |
| `stock_description` | TEXT | 归属原因 |
| `created_at` | TEXT | 创建时间 |

约束：`UNIQUE(node_id, stock_code)`

##### 3.4 表名 suffix 规则

`md5(image_name.strip().encode('utf-8')).hexdigest()[:8]`

示例：`"AI 硬件"` → `md5("AI 硬件")[:8]` → `c232d19b`

##### 3.5 与旧 schema 对比

| | 旧 schema (v1) | 新 schema (v2) |
|---|---|---|
| 总目录 | `thesis_list`（扁平） | `thesis_catalog`（含 node_count） |
| 数据表 | `thesis_stocks_{md5}`（每叶子题材一张） | `thesis_tree_{md5}` + `thesis_stocks_tree_{md5}`（每截图一对） |
| 层级关系 | 丢失（存在 description 文本中） | 完整树结构（parent_id + depth） |
| 表数量 | 261+ 张 | 每截图 2 张 |

---

#### 4. 多模态解析（parse_path_segments_mm.py）

##### 4.1 双模型支持

| 模型 | `--model` 参数 | 调用方式 | 速度 | 费用 |
|------|------|------|------|------|
| qwen3.6-plus | `qwen` (默认) | OpenAI SDK → `coding.dashscope.aliyuncs.com/v1` | ~3-5 秒/segment | 百炼 coding plan 额度 |
| gpt-5-mini | `copilot` | Copilot SDK (`github-copilot-sdk`) | ~30-60 秒/segment | 免费 (Copilot 订阅) |

##### 4.2 Prompt 结构化规则

为保证两种模型识别质量一致，prompt 中包含 7 条关键规则：

1. **题材 vs 股票区分**：左侧题材名 → path_raw，右侧股票名 → stock_text_raw
2. **股票名不入 path_raw**：path_raw 只含题材层级
3. **无题材名归属**：根据上方最近题材名归属
4. **路径深度 2-3 层**：股票名不是题材层
5. **同题材股票合并**：不为每只股票单独建条目
6. **股票名 ≤5 字**：A 股股票名最多 5 个字（含 ST/*ST 前缀），超过 5 字的一定是题材名
7. **根题材名告知**：通过 `--root-name` 参数告知模型，path_raw 第一层应为根题材名

##### 4.3 并发策略

- 默认 **4 路并发**（`ThreadPoolExecutor(max_workers=4)`）
- 超过 4 路会触发 API 限流，导致部分 segment 返回空响应
- 每个 segment 解析完成后通过 `as_completed` 收集结果，按原始索引保持顺序

##### 4.4 重试机制

```python
for attempt in range(max_retries + 1):  # max_retries=2，共 3 次尝试
    if model_backend == "copilot":
        response = call_copilot_image(image_path, prompt)
    else:
        response = call_kimi_k25_image(image_path, prompt, config)
    if not response:
        continue  # 无响应，重试
    items = extract_json_from_response(response)
    if not items:
        continue  # 解析不出 JSON，重试
    return items  # 成功

# 全部重试失败 → 返回 None → 调用方终止流程
```

##### 4.5 Fail-Fast

任何 segment 重试后仍失败，整个 Step 3 `sys.exit(1)`，不产出残缺数据。下游 Step 4-5 不会执行。

---

#### 5. 树构建（insert_thesis_tree.py）

##### 5.1 `--root-name` 参数

当一张截图被切成多个 segment 时，每个 segment 的 `path_raw` 以一级题材名开头（如 `["CPU", "推理芯片"]`），缺少根题材前缀。

`--root-name` 参数确保所有 path 自动补上根题材前缀：

```python
# 无 --root-name: ["CPU", "推理芯片"] → image_name="CPU" → 独立根题材
# 有 --root-name "AI 硬件": ["CPU", "推理芯片"] → ["AI 硬件", "CPU", "推理芯片"] → image_name="AI 硬件"
```

`process_thesis_image.py` 自动从图片文件名推断 `--root-name`（`image_path.stem`）。

##### 5.2 BFS 分配 node_id

```python
roots = sorted(p for p, n in nodes.items() if n["depth"] == 0)
queue = list(roots)
while queue:
    current_path = queue.pop(0)
    path_to_id[current_path] = next_id; next_id += 1
    children = sorted(p for p, n in nodes.items() if n.get("parent_path") == current_path)
    queue.extend(children)
```

保证 node_id 按层级顺序分配，根=1，一级=2..N，二级=N+1..M。

##### 5.3 股票代码查找

通过 `workspace/services/lookup_a_stock_code_by_name` 查找。查找策略分 3 级：

1. **精确匹配**：名称直接匹配字典 key
2. **空格变体**：去除所有空白字符后重试（如 "怡亚通" 匹配 "怡 亚 通"）
3. **模糊匹配**：Levenshtein 编辑距离 ≤ 1（仅对 2-5 字名称），修正 LLM 的 OCR 近形字错误。结果标记 `match_type: "fuzzy"`

查不到的股票打印 `[WARN]` 到 stderr，不阻塞流程。

---

#### 6. 编排脚本（process_thesis_image.py）

##### 6.1 输出目录归档

每次运行按题材名归档到 `output/{题材名}/`，运行前清空目录。所有子脚本通过 `--fixed-name` 参数使用固定文件名（无时间戳）。`run_step` 支持 `fixed_output_name` 参数精确查找输出文件。

##### 6.2 `get_latest_file` 排除规则

`*_run_*.json` 文件是运行记录（元数据），不是实际数据。`get_latest_file` 自动排除这些文件，避免 Step 4 拿到空数据。

##### 6.2 超时设置

Step 3 的 subprocess 超时为 600 秒（10 分钟）。16 个 segment 4 路并发约需 1-2 分钟。

##### 6.3 两种模式

| 模式 | 参数 | 步骤 |
|------|------|------|
| 完整模式 | `--image` only | Step 1→2→3→4→5 |
| 快捷模式 | `--image` + `--input-json` | Step 5 only |

---

#### 7. 查询接口（thesis_api.py）

13 个接口函数，详见 README.md。

---

#### 8. 校验报告（verify_thesis_report.py）

##### 8.1 输出格式

生成 `verify_report_{timestamp}.md`，按树状层级缩进，方便对照原始截图逐层校验：

```markdown
# 数据校验报告 — AI 硬件

**源文件**: AI 硬件
**生成时间**: 2026-04-12 00:36:57
**节点数**: 58 | **股票数**: 252

## AI 硬件 (root) [0 股票]
### 光模块 (first_level) [0 股票]
#### CPO (second_level) [9 股票]
    - 华工科技(000988) 光迅科技(002281) 中际旭创(300308) ...
#### LPO (second_level) [4 股票]
    - 华工科技(000988) 中际旭创(300308) 新易盛(300502) ...
### CPU (first_level) [0 股票]
#### 供货海外 (second_level) [2 股票]
    - 通富微电(002156) 宏昌电子(603002)
...

---
**汇总**: 16 一级题材, 41 二级题材, 252 只股票
```

##### 8.2 设计要点

- **标题层级**：`##` 根 → `###` 一级 → `####` 二级，视觉区分层级
- **叶子节点一行**：`名称(代码) 名称(代码) ...`，股票名+代码方便对照原始截图
- **每个节点标注股票数**：`[N 股票]` 方便快速核对数量
- **汇总行**：一级/二级/股票总数，与原始图片对比
- **失败不终止**：Step 6 失败只记录状态，不阻塞整个流程（校验报告是辅助功能）

##### 8.3 依赖

复用 `thesis_api.py` 的 `get_full_tree()` 函数读取数据，无需新增数据库查询逻辑。

核心工具函数：
```python
def resolve_tree_tables(image_name: str) -> tuple[str, str]:
    """返回 (tree_table, stocks_table) 名称"""
    h = hashlib.md5(image_name.strip().encode('utf-8')).hexdigest()[:8]
    return f"thesis_tree_{h}", f"thesis_stocks_tree_{h}"
```

---

*最后更新：2026-04-12*
