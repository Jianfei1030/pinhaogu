# 概念板块监控与分析系统

监控 A 股/港股概念板块，提供盘前分析、盘后复盘、成分股追踪和实时告警功能。

## 项目信息

- **路径**: `<your-path>/stock-monitor/`
- **代码目录**: `workspace/`
- **报告路径**: `workspace/reports/`
- **Python**: 全局 Python 3.10 (`python3 --version` = 3.10.x)
- **依赖**: pyyaml pandas requests fastapi uvicorn psutil akshare yfinance

---

## 当前状态 / 推荐入口（2026-04）

当前项目的**后台三件套**为：
1. `workspace/server.py` — FastAPI Web 后端（端口 18805，可在 `config.yaml` 中配置）
2. `workspace/monitor.py --config config.yaml --interval 60` — 监控引擎
3. `workspace/daily_news_collector.py --interval 600` — 新闻采集器

**外部依赖**：
- **Ollama（端口 13145）** — 新闻采集/embedding 去重链路的关键依赖，需单独在后台运行

> **注意**：`start_all.sh` 和 `check_health.sh` 会检查 Ollama 可用性，但不会自动启动它。

**推荐入口（macOS）**：
```bash
cd workspace
./start_all.sh      # 一键启动后台三件套（含 Ollama 依赖检查）
./check_health.sh   # 健康检查
```

说明：
- `start_all.sh` 使用全局 Python 3.10 启动三件套，自动校验版本
- `check_health.sh` 会检查三件套进程（含 Ollama）、配置的端口监听和最近日志摘要
- 若手动启动，请确保 Ollama 服务在后台运行（端口 13145）

---

## thesis-ingest 一键入口（开盘啦图片 → 成分股写库）

`thesis-ingest` 是 `stock-monitor` 下的一个子项目能力，负责把开盘啦截图中的题材/成分股信息解析并写入后续流程。根项目只需要记住这个一键入口即可，更多细节请看 `thesis-ingest/README.md`。

### 标准操作流程

#### 1. 接收图片（Telegram 方式）

Telegram 对图片会自动压缩（175x1280 级别），**必须用压缩包方式传原图**：

- 用户将截图打包为 `.7z` 或 `.zip` 压缩包
- 在 Telegram 中以**文件/附件**形式发送（不要直接发图片）
- 压缩包中的图片文件名建议为实际题材名，如 `光伏.png`、`AI 硬件.jpg`

#### 2. 解压并校验图片尺寸

收到压缩包后：

```bash
# 解压到 input_images/
7z x /path/to/archive.7z -o/tmp/thesis_extract
# 或使用 Python 的 zipfile 处理 .zip

# 校验图片尺寸（必须是原图级别，宽度通常 ≥ 1000px）
python3 -c "from PIL import Image; img = Image.open('/tmp/thesis_extract/xxx.png'); print(f'{img.size[0]}x{img.size[1]}')"
```

⚠️ **尺寸校验**：如果图片宽度 < 500px，说明被 Telegram 压缩了，必须重新发压缩包。

#### 3. 保存到目标目录并执行

```bash
# 保存到 input_images/
cp /tmp/thesis_extract/光伏.png thesis-ingest/input_images/光伏.png

# 派 Sub-Agent 执行全量 6 步管道
# model: qwen3.6-plus, thinking: medium
```

### 一键入口命令

```bash
cd <your-path>/stock-monitor/thesis-ingest
python3 scripts/process_thesis_image.py --image <your-home>/.openclaw/media/inbound/Screenshot_2026-04-09-09-03-23-962_com.aiyu.kaipanla---9054cb9b-6f59-4624-903e-b945a8600919.jpg
```

### 使用说明

- 支持 `--input-json` shortcut：如果已经有验收过的候选 JSON，可直接用它快速重跑，无需重新走图片解析流程
- 输出按题材名归档：`thesis-ingest/output/{题材名}/`，每次运行清空重建，文件名无时间戳
- 详细说明与参数约定：`thesis-ingest/README.md`

---

## 题材描述管理

`auto_generate_descriptions.py` 和 `backfill_descriptions.py` 负责为已入库的题材自动生成/补全根题材 + 一级/二级子题材的描述。

### 补全缺失描述（推荐）

```bash
cd <your-path>/stock-monitor/thesis-ingest

# 补全某个题材的缺失描述（自动跳过已有描述的节点）
.venv/bin/python3 scripts/backfill_descriptions.py 光伏

# 补全所有题材的缺失描述
.venv/bin/python3 scripts/backfill_descriptions.py
```

- 默认使用 **Copilot SDK（gpt-5-mini）** 生成描述
- 只处理 description 为空或空白字符串的节点
- 自动跳过根描述已存在的题材（但会检查子节点描述是否完整）

### 手动生成某个题材的完整描述

```bash
cd <your-path>/stock-monitor/thesis-ingest
.venv/bin/python3 scripts/auto_generate_descriptions.py --image "光伏"

# 强制使用 qwen 作为后端
.venv/bin/python3 scripts/auto_generate_descriptions.py --image "光伏" --backend qwen
```

### Python 函数接口

```python
from scripts.backfill_descriptions import fill_thesis
result = fill_thesis("光伏", "thesis.db")
# => {"total_empty": 16, "written": 16, "failed": 0}

from scripts.auto_generate_descriptions import generate_thesis_description
ok = generate_thesis_description("光伏", "thesis.db", backend="copilot")
```

---

## 🏗️ 系统架构（2026-04-05 重构后）

### 整体架构

```
┌──────────────────────────────────────────────────────────────┐
│                      应用层 (Application)                     │
├──────────────────────────────────────────────────────────────┤
│  monitor.py  │ premarket.py  │ postmarket.py │ server.py    │
│  监控引擎     │ 盘前分析       │ 盘后复盘        │ Web 后端      │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│                      工具层 (Utils)                           │
├──────────────────────────────────────────────────────────────┤
│  config.py   │ push.py       │ logger.py                      │
│  统一配置     │ 统一推送       │ 统一日志                        │
│  • Telegram  │ • send_both() │ • setup_logger()              │
│  • QQ        │ • send_telegram()                            │
│  • 数据路径   │ • send_qq()                                  │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│                    数据源层 (Data Sources)                     │
├──────────────────────────────────────────────────────────────┤
│  data_sources/ 包                                             │
│  ├── base.py       # 异常类 + 会话配置                        │
│  ├── utils.py      # 代码转换/市场推断/时间格式化             │
│  ├── tencent.py    # 腾讯接口（港股 1min K 线）                │
│  ├── sina.py       # 新浪接口（实时行情）                     │
│  ├── akshare.py    # 东财/同花顺（A 股日线/周线/月线）        │
│  └── yfinance.py   # Yahoo Finance（港股多周期）              │
│                                                              │
│  data_source.py  # 向后兼容包装层（旧代码无需修改）            │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│                    数据持久层 (Persistence)                   │
├──────────────────────────────────────────────────────────────┤
│  database.py     # SQLite 封装（upsert_kline, query_kline）   │
│  aggregator.py   # K 线聚合（60min → 120min）                 │
│  indicators.py   # 技术指标引擎（MACD）                       │
│  calc_chip_dist.py # 筹码分布计算                            │
└──────────────────────────────────────────────────────────────┘
```

### 设计原则

1. **统一配置** — 所有配置集中在 `config.py`，消灭硬编码
2. **统一推送** — `send_both()` 同时推 Telegram + QQ
3. **统一日志** — `setup_logger()` 自动管理日志文件和格式
4. **模块化数据源** — 每个数据源独立文件，易于扩展和维护
5. **向后兼容** — `data_source.py` 包装层确保旧代码无需修改

### 重构效果（Phase 0）

| 指标 | 重构前 | 重构后 | 改进 |
|------|--------|--------|------|
| .py 文件数 | 44 | 28 | -36% |
| 临时文件 | 16 | 0 | -100% |
| 配置重复 | 3+ 处 | 1 处 | -67% |
| 推送代码重复 | 3+ 处 | 1 处 | -67% |
| data_source.py | 1061 行 (35KB) | 8 个模块 (<7KB 每个) | 模块化 |
| 可读性 | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | +40% |

---

## 快速开始

```bash
# 确认 Python 版本为 3.10
python3 --version  # 应输出 Python 3.10.x

# 安装依赖
pip3 install pyyaml pandas requests fastapi uvicorn psutil akshare yfinance
```

### 推荐方式（macOS）

```bash
cd workspace

# 一键启动后台三件套（含 Ollama 依赖检查）
./start_all.sh

# 健康检查
./check_health.sh
```

脚本功能：
- `start_all.sh`：使用全局 Python 3.10 依次启动 `server.py` / `monitor.py` / `daily_news_collector.py`，避免重复启动，日志按日期归档；同时检查 Ollama（端口 13145）是否可用
- `check_health.sh`：检查三件套进程状态（含 Ollama）、配置端口监听、最近日志摘要
- `run_status_report.sh`：后台状态监控包装脚本（每小时检查 + 自动重启）
- `status_report.py`：状态检查核心脚本（检查 server/monitor/news/Ollama，异常时自动重启）

**虚拟环境**：脚本优先使用 `.venv`，其次 `venv`。Python 版本必须为 3.10。

### 手动启动（调试用）

```bash
cd workspace

python3 server.py &
python3 monitor.py --config config.yaml --interval 60 &
python3 daily_news_collector.py --interval 600 &

# 浏览器打开 http://localhost:18805（端口可在 config.yaml 中配置）
```

### 模块使用示例

```python
# 统一配置
from config import config
print(config.telegram.chat_id)  # Telegram 聊天 ID
print(config.qq.target)         # QQ 推送目标

# 统一推送
from utils.push import send_both, send_telegram, send_qq
send_both("告警消息")  # 同时推 Telegram + QQ

# 统一日志
from utils.logger import setup_logger
logger = setup_logger("my_module", log_dir="logs")
logger.info("日志消息")

# 数据源
from data_sources import fetch_kline, fetch_a_daily, fetch_hk_kline

# 港股 5 分钟 K 线
hk_data = fetch_kline("01810", market="HK", period="5min", count=100)

# A 股日线
a_data = fetch_kline("000001", market="A", period="daily", count=250)

# 港股日线（yfinance）
hk_daily = fetch_hk_kline("01810", period="1d", count=500)
```

## 项目结构

### 当前实际布局（2026-04）

> 当前项目并不是完全按 `core/analysis/backfill/legacy` 目录拆分，**多数主脚本仍位于 `workspace/` 顶层**。下面这份结构以当前真实文件布局为准。

```
workspace/
├── server.py                   # FastAPI Web 后端
├── monitor.py                  # 监控引擎（轮询 / 告警 / 补全触发）
├── daily_news_collector.py     # 新闻采集器
├── premarket_analysis.py       # 盘前分析（08:47）
├── postmarket_review.py        # 盘后复盘（21:30）
├── daily_incremental_backfill.py # 16:30 全 A 股增量补全
├── data_backfill.py            # 监控标的补全
├── data_backfill_all_v2.py     # 全量/批量补全脚本
├── data_source.py              # 兼容包装层
├── database.py                 # SQLite 封装
├── aggregator.py               # K 线聚合
├── calc_chip_dist.py           # 筹码分布计算
├── config.py / config.yaml     # 统一配置
├── start_all.bat               # Windows 一键启动
├── start_all.sh                # macOS 一键启动
├── check_health.sh             # macOS 健康检查
├── run_status_report.sh        # 后台状态监控包装脚本（每小时循环）
├── status_report.py            # 状态检查核心脚本（自动重启）
├── data_sources/               # 数据源实现（腾讯 / 新浪 / akshare / yfinance）
├── utils/                      # 通用工具（推送 / 日志）
├── indicators/                 # 指标模块
├── screener/                   # 选股相关模块
├── static/                     # Web 前端静态资源
├── data/                       # SQLite 数据目录
├── reports/                    # 报告输出
├── news_data/                  # 新闻缓存与去重结果
└── logs/                       # 运行日志
```

### 顶层脚本入口规范

> 详细规范见 `workspace/scripts/README.md`

**Thin Wrapper 原则**：
- 顶层脚本只负责：CLI 参数解析、环境变量读取、调用 `run()` 函数、处理退出码
- 真实业务逻辑下沉到 `services/` 或专职模块

**配置优先级**（从高到低）：
```
CLI 显式参数 > 环境变量 > config.yaml > 代码默认值
```

**运行口径**：
- 默认使用全局 Python 3.10，不依赖项目 venv
- Shell 脚本中统一使用 `python3`，并在启动时校验版本

**典型调用示例**：
```bash
# 监控服务（60 秒间隔）
python3 monitor.py --config config.yaml --interval 60

# 盘前分析（指定日期，测试模式）
python3 premarket_analysis.py --date 2026-04-07 --dry-run

# 盘后复盘（禁用通知）
python3 postmarket_review.py --no-notify

# 增量数据补全
python3 daily_incremental_backfill.py --date 2026-04-07

# 健康检查
./check_health.sh

# 启动全部服务
./start_all.sh
```

### Service 层（重构中）

> 详细设计见 `workspace/services/README.md`

**定位**：将 `server.py` 中的业务逻辑薄拆为独立 service 模块，便于测试和复用。

**计划新增的 service**：
- `market_data_service.py` — K 线查询 + MACD 计算
- `alert_service.py` — 告警规则管理 + 历史查询 + 测试评估
- `analysis_service.py` — 盘前/盘后分析触发 + 状态查询 + 报告读取
- `config_service.py` — 配置读取/保存、watchlist/alerts 管理
- `monitor_status_service.py` — monitor 进程检测 + 状态文件读写

**设计原则**：
- Router 层（`server.py`）只负责：路由注册、参数校验、调用 service、HTTP 响应转换
- Service 层负责：业务逻辑、文件/数据库访问、调用 Job Runner、返回结构化结果
- 延续轻量函数式模块风格（无 class，直接 `def function()`）

### 依赖关系

```
应用层 (server.py / monitor.py / premarket_analysis.py / postmarket_review.py)
    ↓
工具层 (config.py / utils.push / utils.logger)
    ↓
数据源层 (data_sources/ + data_source.py)
    ↓
持久层 (database.py / aggregator.py / indicators/ / calc_chip_dist.py)
```

## 数据源架构

### 数据源总览

| 市场 | 数据类型 | 数据源 | 用途 | 状态 |
|------|----------|--------|------|------|
| **港股** | 1min K 线 | 腾讯 | 实时告警 | ✅ |
| **港股** | 5/15/30/60min | yfinance | 数据补全 | ✅ |
| **港股** | 1d/1wk/1mo | yfinance | 历史数据 | ✅ |
| **港股** | 实时行情 | 腾讯 + 新浪 | 双源 fallback | ✅ |
| **A 股** | 1d 日线 | 新浪 (akshare) | 主源 | ✅ |
| **A 股** | 1d 日线 | 腾讯 (fqkline) | Fallback | ✅ |
| **A 股** | 1wk/1mo | 从日线聚合 | 本地计算 | ✅ |
| **A 股** | 实时行情 | 新浪 + 腾讯 | 双源 fallback | ✅ |
| **全市场** | 筹码分布 | 本地计算 | 基于 K 线模拟 | ✅ |
| **全市场** | MACD | 本地计算 | talib/numba | ✅ |

### 数据源模块（`data_sources/`）

```python
# 使用示例
from data_sources import fetch_kline, fetch_a_daily, fetch_hk_kline

# 港股多周期（yfinance）
hk_5min = fetch_kline("01810", market="HK", period="5min", count=100)
hk_daily = fetch_kline("01810", market="HK", period="1d", count=500)

# A 股日线（akshare）
a_daily = fetch_kline("000001", market="A", period="daily", count=250)

# 向后兼容（旧代码无需修改）
from data_source import fetch_kline  # 自动路由到正确的数据源
```

### 数据源策略

**概念板块**：
- 板块列表：同花顺 `stock_board_concept_name_ths()` → 375 个
- 成分股：东财 `stock_board_concept_cons_em()` 优先，同花顺 fallback
- 板块涨跌幅：成分股平均涨跌幅计算

**实时行情**：
- 港股：腾讯主源，新浪 fallback
- A 股：新浪主源，腾讯 fallback
- 双源并发，取最新时间戳

**A 股日线**：
- 主源：新浪 `ak.stock_zh_a_daily`（前复权）
- Fallback：腾讯 `fqkline/get`（仅 A 股，不支持北交所）
- 北交所：仅新浪（腾讯不支持）
- 代理处理：调用前自动清空 HTTP/HTTPS 代理

**历史数据**：
- 港股：yfinance（支持多周期，最大范围拉取）
- 周线/月线：从日线聚合（本地计算）

### 新闻采集
- 代码：`daily_news_collector.py`
- 依赖：Ollama + qwen3-embedding:4b (port 13145) 做语义去重
- 频率：每 10 分钟一轮
- 5 源：同花顺/新浪/东方财富/富途/财联社
- 输出：`news_data/financial_news_YYYY-MM-DD.json`

## 数据补全系统

> 每日自动补全全 A 股 + 监控标的的各周期历史数据，确保 MACD 计算和回测分析有完整数据支撑。
>
> 当前口径（2026-04）：**工作日 16:30 先执行全 A 股增量补全，再继续监控标的补全**。

### 触发机制

| 项目 | 说明 |
|------|------|
| **驱动者** | `monitor.py` 主进程（内置触发器） |
| **触发时间** | **工作日 16:30 一次** |
| **执行条件** | 周末/节假日不执行 |
| **去重机制** | 按日期判断，跨天自动重置（2026-04-15 修复） |
| **依赖** | monitor.py 进程必须在线运行 |
| **失败通知** | 补全失败时自动推送 Telegram+QQ 失败报告（2026-04-15 新增） |
| **手动触发** | `POST /api/backfill/run {date, dry_run, workers}`（2026-04-15 新增） |

> **2026-04-06 修复**：`daily_incremental_backfill.py` 已修复 `a_stock_list.json` 的 list[dict] 解析问题，避免 `expected string or bytes-like object` 错误。
> **2026-04-15 修复**：`monitor.py` 的 `backfill_done` 改为 `(date, time)` 元组存储，跨天自动重置；补全失败立即推送失败报告；新增 `POST /api/backfill/run` 手动触发 API。

### 执行流程

```
16:30 触发
  ↓
Step 1: 全 A 股日线补全（daily_incremental_backfill.py）
- 5,497 只 A 股
- 每只获取当日 1 条 K 线
- 计算 MACD + 筹码分布
- 推送 Telegram + QQ
- 预计耗时：~4.5 小时
  ↓
Step 2: 监控标的补全（_run_backfill）
- 5 只监控股票
- 7 个周期（5/15/30/60/120min + 1d + 1wk）
- 预计耗时：~2 分钟
  ↓
完成 @ 约 21:00
```

### 补全内容

| 对象 | 周期 | 数据源 | 范围 |
|------|------|--------|------|
| **全 A 股** | 1d（日线） | yfinance | 当日 1 条 |
| **全 A 股** | MACD | 本地计算 | 基于历史 + 当日 |
| **全 A 股** | 筹码分布 | 本地计算 | 基于历史 + 当日 |
| **监控标的** | 5min/15min/30min | yfinance | 最大 60 天 |
| **监控标的** | 60min | yfinance | 最大 730 天（2 年） |
| **监控标的** | **120min** | 从 60min 聚合 | 每 2 根 60min 合并为 1 根 |
| **监控标的** | 1d（日线） | yfinance | 全历史（IPO 至今） |
| **监控标的** | 1wk（周线） | yfinance | 全历史（IPO 至今） |

### 手动执行

```bash
cd workspace

# 单次执行（静默模式）
python data_backfill.py --once --quiet

# 详细输出
python data_backfill.py --once
```

### 手动触发 API

```bash
# 触发今天的增量补全
curl -X POST http://localhost:18805/api/backfill/run \
  -H "Content-Type: application/json" \
  -d '{"date": "2026-04-15"}'

# dry-run 模式（不写库不推送）
curl -X POST http://localhost:18805/api/backfill/run \
  -H "Content-Type: application/json" \
  -d '{"date": "2026-04-15", "dry_run": true}'

# 指定 workers 数量
curl -X POST http://localhost:18805/api/backfill/run \
  -H "Content-Type: application/json" \
  -d '{"date": "2026-04-15", "workers": 8}'

### 注意事项

1. **monitor.py 必须在线** — 数据补全由 monitor 内部触发，进程挂掉则补全停止
2. **健康检查 cron** — 每日 10:00-20:00 每小时检查进程状态，异常时自动重启
3. **120min 是聚合数据** — 不直接拉取，从 60min 数据两两合并
4. **周末跳过** — 周六日不执行补全
5. **跨天自动重置** — `backfill_done` 按 `(date, time)` 存储，新日期自动清空，不再因进程长期运行而漏触发（2026-04-15 修复）
6. **失败即时通知** — 补全失败会立即推送 Telegram+QQ 报告，不再静默失败（2026-04-15 新增）
7. **手动触发** — 可通过 `POST /api/backfill/run` 手动触发，不必等 16:30（2026-04-15 新增）

---

## 数据补全工具（手动/批量）

### 每日增量补全（daily_incremental_backfill.py）

**定位**：每日自动补全 5,497 只 A 股的当日 K 线 + MACD + 筹码分布。

**使用方法**：
```bash
cd workspace
python3 daily_incremental_backfill.py
```

**特点**：
- 增量处理：每只股票只获取当日 1 条 K 线
- 智能跳过：自动检查当日数据是否已存在
- 限流保护：每只股票后 sleep(3) 秒，每 100 只额外 sleep(60) 秒
- 双通道推送：完成后自动推送到 Telegram 和 QQ
- 预计耗时：约 4.5 小时

**数据库路径**：`data/A/A{股票代码}/{日期}.db`

### 全量补全 V2（data_backfill_all_v2.py）

**定位**：一次性补全全部 A 股的历史数据（约 250 条/只），支持断点续传和分批执行。

**使用方法**：
```bash
cd workspace

# 测试前 N 只
python3 data_backfill_all_v2.py --test 10

# 执行指定批次
python3 data_backfill_all_v2.py --batch 1 --batch-size 100

# 全量执行
python3 data_backfill_all_v2.py --all

# 从断点继续
python3 data_backfill_all_v2.py --resume
```

**特点**：
- 进度保存：`data/backfill_progress.json` 记录处理进度
- 断点续传：中途中断后可 `--resume` 继续
- 分批执行：支持 `--batch N --batch-size 100` 分批处理
- 抽样验证：每完成 100 只后随机抽取 5 只验证
- 预计耗时：全量约 12-15 小时（建议分批执行）

**输出**：
- 进度文件：`data/backfill_progress.json`
- 日志文件：`logs/backfill_all_YYYY-MM-DD.log`
- 数据库：`data/A/A{symbol}/{date}.db`（每只股票一个）

## Cron 任务

| 任务名 | 时间 | 说明 |
|--------|------|------|
| **每天** 08:47 | 盘前分析：拉取板块 → LLM 推荐 → 成分股筛选 → 筹码计算 → 推送 Telegram + QQ |
| **每天** 16:30（工作日） | 全 A 股增量补全 + 后续监控标的补全，详见上方「数据补全系统」 |
| **每天** 21:30 | 盘后复盘：对比预测 vs 实际 → LLM 复盘 → 推送 Telegram + QQ |
| **每天** 10:00-20:00 每小时 | 进程健康检查 / 状态汇报（`run_status_report.sh` + `status_report.py`） |
| `skill-update-check` | 每天 10:00 | 检查技能更新 |
| `ai-daily-news` | 每天 23:00 | AI 新闻汇总 |

## 东方财富妙想 Skills

路径：`skills/mx-skills/`

| Skill | 说明 |
|-------|------|
| `mx-data` | 数据获取 |
| `mx-search` | 搜索查询 |
| `mx-xuangu` | 选股功能 |
| `mx-zixuan` | 自选管理 |
| `mx-moni` | 模拟交易 |

**环境变量**: `MX_APIKEY`

## Ollama 配置

- **端口**: 13145
- **模型**: `qwen3-embedding:4b` (2560 维，新闻去重主力) + `bge-m3` (备用)
- **模型大小**: Qwen3-Embedding 4B Q4 量化约 2.5GB，推理 ~230ms/条

## Web 界面

### Tab 布局

- **📊 监控**: K 线图+MACD+ 告警规则
- **📰 新闻**: 新闻列表 + 盘前分析/盘后复盘
- **🔍 选股**: 板块选择 + 条件筛选 + 结果
- **📈 回测**: 即将推出

### 状态栏

- **左侧**: 监控状态 + 市场状态
- **右侧**: 新闻采集状态

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | Web 前端页面 |
| `/api/config` | GET | 配置信息（含 watchlist、alerts、analysisModel） |
| `/api/kline` | GET | K 线 +MACD 数据（参数：symbol, period, date, market） |
| `/api/quote/{symbol}` | GET | 实时行情 |
| `/api/monitor/status` | GET | 监控引擎状态（进程状态、市场状态） |
| `/api/calibration/status` | GET | 校准任务状态 |
| `/api/alerts` | GET/POST/PUT/DELETE | 告警规则 CRUD |
| `/api/alerts/test` | POST | 告警规则回测测试 |
| `/api/indicators` | GET | 可用指标列表 |
| `/api/indicators/reload` | POST | 触发指标引擎重载 |
| `/api/premarket/report` | GET | 指定日期盘前分析报告 |
| `/api/premarket/latest` | GET | 最近一次盘前分析 |
| `/api/premarket/status` | GET | 盘前分析状态（报告是否存在） |
| `/api/premarket-thesis/run` | POST | 启动盘前题材分析 |
| `/api/premarket-thesis/report` | GET | 指定日期盘前题材分析报告 |
| `/api/premarket-thesis/status` | GET | 盘前题材分析状态 |
| `/api/premarket-thesis/history` | GET | 盘前题材分析历史日期列表 |
| `/api/backfill/run` | POST | 手动触发全 A 股增量补全 |
| `/api/review/report` | GET | 指定日期复盘报告 |
| `/api/review/latest` | GET | 最近一次复盘 |
| `/api/board/snapshots` | GET | 板块快照列表 |
| `/api/board/stocks` | GET | 板块成分股 |
| `/api/board/history` | GET | 板块历史数据 |
| `/api/screener/conditions` | GET | 选股条件列表 |
| `/api/screener/sectors` | GET | 板块列表 |
| `/api/screener/run` | POST | 执行选股 |
| `/api/analysis/daily` | POST | 启动每日分析任务 |
| `/api/analysis/status` | GET | 分析任务状态 |
| `/api/analysis/report` | GET | 分析报告（Markdown） |
| `/api/news/status` | GET | 新闻采集状态 |
| `/api/news/recent` | GET | 最近新闻列表（支持增量轮询） |

## 告警系统

### 配置示例
```yaml
alerts:
  - name: "15min DIF+ 柱双斜率向上"
    period: 15min
    conditions:
      logic: AND
      rules:
        - {indicator: macd_slope, op: ">", value: 0}
        - {indicator: hist_slope, op: ">", value: 0}
    cooldown: 300
```

### 可用指标
`macd` / `macd_dea` / `macd_hist` / `macd_slope` / `dea_slope` / `hist_slope`

支持跨周期：`15min:macd_slope` / `15min:hist_slope`

### 运算符
`>` / `<` / `>=` / `<=` / `==`

## 概念板块盘前分析 + 复盘

> ✅ Phase 17 + 18 已完成 (2026-03-27)

基于同花顺概念板块 API，每日自动执行：

| 时段 | 功能 | 数据源 |
|------|------|--------|
| **08:47** 盘前 | 拉取全部概念板块（375 个）→ LLM 选 1 个推荐 → 拉取成分股 → 推送 Telegram → 写入数据库 | 同花顺 + 百炼 qwen3.5-plus |
| **21:30** 盘后 | 对比预测 vs 实际涨跌 → LLM 复盘 → 推送 Telegram → 写入数据库 | 同花顺 |

### 数据获取流程

```
Step 1 (Python): fetch_all_boards() → 全部 375 个同花顺概念板块
Step 2 (LLM):    全部新闻 + 全部板块信息 → 推荐 1 个概念板块（详细分析 200+ 字）
Step 3 (Python): fetch_board_stocks(板块名) → 该板块全部成分股
Step 4 (Python): 通过成分股平均涨跌幅计算板块涨跌幅
Step 5 (输出):    汇总报告 → Telegram 推送 + 数据库存储
```

### 数据库

每日自动创建 SQLite 数据库：`workspace/reports/board/YYYYMMDD.db`

**表结构：**
- `board_snapshot`：板块快照（代码/名称/涨跌幅/推荐理由/催化/是否推荐）
- `stock_snapshot`：成分股快照（股票代码/名称/价格/涨跌幅）

### 前端展示

- **新闻 Tab**: 按日期显示盘前分析卡片列表 + 复盘查看
- **选股 Tab**: 今日推荐板块 + 成分股实时涨跌 + 复盘分析

## 盘前题材分析（Thesis-based）

> ✅ Phase 34 已完成 (2026-04-13) | ✅ Phase 37 新闻过滤优化已完成 (2026-04-15)

基于 thesis 题材（从开盘啦图片 OCR 识别入库）的盘前分析，与概念板块盘前分析并存。

| 时段 | 功能 | 数据源 |
|------|------|--------|
| **08:47** 盘前 | 拉取全部 thesis 题材 → LLM 选 1 个推荐根题材 → **LLM 子题材精筛（v2 新增）** → 拉取精筛后成分股行情 → 筹码筛选 → 推送 Telegram+QQ → 写入报告 | thesis.db + 本地 DB (kline_1d) + 百炼 |

**特性**：
- 休市日（周末/节假日）可正常执行，自动使用上一交易日数据
- Telegram 推送仅输出最终筛选结果（获利比例>50%），精简洁出
- 报告 JSON 保留全量统计 count，不存储全量成分股数据

### 与概念板块分析的区别

| | 概念板块分析 | 题材分析 |
|---|---|---|
| 数据源 | 同花顺概念板块 API | thesis.db（开盘啦 OCR） |
| 行情获取 | akshare 实时行情 | 本地 DB（kline_1d） |
| 脚本 | `premarket_analysis.py` | `premarket_thesis_analysis.py` |
| 报告类型 | `premarket_*.json` | `premarket_thesis_*.json` |
| 休市日 | 跳过 | 正常执行（降级） |
| 推送内容 | 全量+筛选三层 | 仅最终筛选结果 |
| 子题材筛选 | 无 | v2: LLM 基于树状结构精筛高价值子题材（见下文） |

**执行流程**（5 步）：

| Step | 描述 |
|------|------|
| 1/5 | 拉取题材列表 |
| 2/5 | 新闻过滤（embedding 分类）+ 宏观形势分析 |
| 3/5 | LLM 主题材选择（仅用产业类新闻） |
| 3.5/5 | 子题材精筛 |
| 4/5 | 行情补全 + 筛选 |
| 5/5 | 报告 + 推送（含宏观判断） |

### 新闻过滤架构（v3 新增）

Phase 37 新增新闻过滤模块 `news_filter.py`，用双参考向量 embedding 对盘前新闻做宏观/产业分类。

**原理**：
- 宏观参考向量：`地缘冲突 战争 中东 伊朗 以色列 军事 制裁 原油 黄金 政治选举 外交 央行 通胀 GDP`
- 产业参考向量：`业绩预增 净利 涨停 资金 机构 政策 产业 技术突破 产品发布 合作 中标 研报 A股 港股`
- 对每条新闻 title 做 embedding（Ollama qwen3-embedding:4b + /api/embed 批量接口），计算与两个参考向量的余弦相似度
- `macro_sim > industry_sim` → 宏观类；否则 → 产业类
- 效果：~40% 宏观 / ~60% 产业，LLM 第一轮输入 token 从 ~69000 降至 ~48000（降幅 ~30%）

**宏观形势分析**：
- 新增 `llm_macro_analysis()` 函数，基于宏观类新闻输出：形势判断（偏乐观/偏谨慎/中性）+ 一句话摘要 + 关键信号 + 关注风险
- Telegram 消息头部新增 `🌍 宏观形势: {judgment} — {summary}` 行
- 报告 JSON 新增 `macro_analysis` 字段

### 子题材精筛流程（v2）

v2 在 LLM 推荐根题材后，新增 **Step 2.5 子题材精筛**，避免拉取全部成分股导致行情请求过多。

**核心流程**：

1. `get_thesis_tree_structure(image_name)` — 从 thesis.db 提取题材的一级 + 二级树状结构（含每个节点的股票数量），返回结构化 JSON
2. LLM 根据树状结构 + 各子题材描述 + 股票数量，选择有投资价值的子题材节点（`node_id` 列表）
3. `get_stocks_by_nodes(image_name, node_ids)` — 根据选中的 `node_id` 批量拉取成分股，按 `stock_code` 合并去重
4. 仅对精筛后的成分股获取行情并执行后续筹码筛选

**关键 API**（定义在 `thesis-ingest/scripts/thesis_api.py`）：

| 函数 | 作用 |
|---|---|
| `get_thesis_tree_structure(image_name)` | 提取题材树状结构（root → first_level → second_level），含每个节点的 `node_id`、`name`、`description`、`stock_count` |
| `get_stocks_by_nodes(image_name, node_ids)` | 根据选中的 `node_id` 列表获取成分股，按 `stock_code` 合并去重，返回 `{stock_code, stock_name, node_id, node_path}` |

### 执行方式

```bash
# 手动 dry-run
cd workspace && python3 premarket_thesis_analysis.py --dry-run

# 指定日期（支持休市日）
cd workspace && python3 premarket_thesis_analysis.py --date 2026-04-12

# 通过 API 触发
curl -X POST http://localhost:18805/api/premarket-thesis/run -H "Content-Type: application/json" -d '{"dry_run": true}'
```

## A 股支持

系统支持 A 股（沪深）数据源。A 股代码前缀自动推断：
- **6/5/9 开头 → sh**，其他 → **sz**

```yaml
watchlist:
  - {symbol: "01810", market: "HK", name: "小米集团-W"}
  - {symbol: "603986", market: "A",  name: "兆易创新"}
```

### 市值字段（Phase 38 新增，2026-04-15）

kline_1d 表新增 `total_mv`（总市值）和 `circ_mv`（流通市值）两列，单位：亿元。

- **数据来源**：腾讯实时行情接口 `qt.gtimg.cn/q={code}`，字段 [44] 总市值 / [45] 流通市值
- **写入时机**：每日 16:30 增量补全时，每只股票补全日线后附带抓取
- **数据库兼容**：旧 DB 文件自动 ALTER TABLE 添加新列，不影响已有数据
- **查询兼容**：`query_kline()` 自动检测列是否存在，旧数据返回 null
- **限流控制**：补全过程中已有 sleep_per_stock 限流，不额外增加请求压力

## 部署

```bash
# 启动服务
cd workspace
python server.py &
python monitor.py --config config.yaml --interval 60

# 日志
logs/server_YYYY-MM-DD.log
logs/monitor_YYYY-MM-DD.log
logs/news_YYYY-MM-DD.log
```

## 移动端适配

Web 页面已适配移动端浏览器：
- 768px 断点：平板布局
- 侧栏抽屉式（点击☰展开）
- Canvas 触摸交互（拖拽 + 缩放）

---

## 推送系统

### 双渠道推送

| 渠道 | 账号 | 方式 | 覆盖范围 |
|------|------|------|----------|
| **Telegram** | stock bot (`8624013562`) | Bot API `requests.post` | 所有推送 |
| **QQ** | guzi (股子) | `openclaw message send --channel qqbot --account guzi` | 所有推送 |

**已集成 QQ 推送的脚本**：
- `monitor.py` — 实时告警触发时推送
- `premarket_analysis.py` — 盘前分析报告
- `postmarket_review.py` — 盘后复盘报告
- `daily_news_collector.py` — 新闻采集（配置层）
- `status_report.py` — 进程健康汇报

## 筹码分布计算

### 模块：`calc_chip_dist.py`
- **数据源**: yfinance 90 天历史日线
- **算法**: 模拟筹码衰减（每日换手率 ≈ 2%）
- **输出指标**:
  - `profit_ratio` — 获利比例（当前价以下筹码占比，0-1）
  - `avg_cost` — 市场平均成本
  - `concentration_90` — 90% 筹码集中度（越小越集中）

### 盘前分析中的筹码应用
1. Step 1-2: 拉取板块 + LLM 推荐
2. Step 3: 拉取成分股
3. **Step 3.5: 筹码分布计算**（前 10 只）
   - 每只成分股计算获利比例 + 集中度
4. Step 4: **三重筛选**
   - ① 换手率 > 3%
   - ② 成交额 > 3 亿
   - ③ 获利比例 > 50%（剔除底部未启动股票）
5. Step 5: 推送报告（含筹码数据）

### 推送消息格式示例
```
1. 601872 招商轮船 +8.17% 换手:5.23% 成交额:12.3亿 获利96.6% 集中度0.71
2. 600428 中远海特 - 换手:3.45% 成交额:8.7亿 获利100.0% 集中度0.27
```

## Embedding 模型（新闻去重）

### 升级历史
- **旧**: `bge-m3` (567M, 1024 维, ~120ms/条)
- **新**: `qwen3-embedding:4b` (4B, 2560 维, ~230ms/条)

### 选择原因
- 阿里 Qwen3 架构，中文理解提升 8-10%
- 向量维度提升 2.5x（1024 → 2560）
- 速度仅慢 2x，对 700 条新闻去重影响 ~1.5 分钟

---

*最后更新：2026-04-15*（Phase 34/35/36/37/38 完成：新闻过滤优化 + 宏观形势分析 + 子题材精筛 + A 股市值字段 + 补全失败推送 + 手动触发 API）

---

## thesis-ingest: 题材注入系统

> 从开盘啦长截图识别题材层级 + 成分股 → 写入 SQLite 数据库（树状结构）

---

### 核心思路

开盘啦 APP 的题材详情页是一张非常长的手机截图（1220x12000~20000px），包含一个树状层级结构：**根题材 → 一级子题材 → 二级子题材 → 股票列表**。

每张原始截图最终产出**一棵树**：`thesis_catalog` 一行 + 一对动态表（`thesis_tree_{md5}` + `thesis_stocks_tree_{md5}`），表内存储完整的树状层级。

---

### 管道流程（6 步）

```
input_images/*.jpg
      │
      ▼
  Step 1: plan_semantic_cuts.py      检测红色水平线 → 定位切割边界
      │                                  输出: cut_plan.json
      ▼
  Step 2: split_by_path_plan.py      按边界裁剪原图为 segment 图片
      │                                  输出: segments/segment_*.png + manifest.json
      ▼
  Step 3: parse_path_segments_mm.py  多模态模型并发解析每个 segment → 题材路径 + 股票列表
      │                                  输出: segment_parse.json
      ▼
  Step 4: expand_path_ancestors.py   展开层级路径为祖先候选（纯 JSON 变换）
      │                                  输出: ancestor_candidates.json
      ▼
  Step 5: insert_thesis_tree.py      构建树 → 查找股票代码 → 写入 SQLite → 自动生成描述
      │
      ▼
  Step 6: verify_thesis_report.py    从数据库回读 → 生成 Markdown 校验报告（含描述）
      │                                  输出: verify_report.md
      ▼
  thesis.db (SQLite) + output/{题材名}/ 下所有文件
```

#### 快捷模式

如果已有 `ancestor_candidates.json`，可跳过前 4 步直接入库（共 2 步：入库 + 校验）：

```bash
python3 thesis-ingest/scripts/process_thesis_image.py --image /path/to/image.jpg --input-json output/题材名/ancestor_candidates.json
```

---

### 运行方式

```bash
cd <your-path>/stock-monitor/thesis-ingest

# 完整管道（6 步，一键执行，默认 qwen 模型）
# 输出自动归档到 output/{题材名}/ 目录
python3 scripts/process_thesis_image.py --image input_images/固态电池.jpg

# 使用 Copilot 免费模型
python3 scripts/process_thesis_image.py --image input_images/固态电池.jpg --model copilot

# 指定数据库和输出根目录
python3 scripts/process_thesis_image.py --image input_images/电力.png --output-dir output --db thesis.db

# 单独运行某一步（使用 --fixed-name 生成无时间戳文件名）
python3 scripts/plan_semantic_cuts.py --image input_images/xxx.jpg --output-dir output/题材名 --fixed-name
python3 scripts/split_by_path_plan.py --plan output/题材名/cut_plan.json --image input_images/xxx.jpg --output-dir output/题材名 --fixed-name
python3 scripts/parse_path_segments_mm.py --manifest output/题材名/segments/manifest.json --output-dir output/题材名 --model copilot --root-name "固态电池" --fixed-name
python3 scripts/expand_path_ancestors.py --source output/题材名/segment_parse.json --output-dir output/题材名 --fixed-name
python3 scripts/insert_thesis_tree.py --input output/题材名/ancestor_candidates.json --db thesis.db --source-image xxx.jpg --root-name "根题材名"

# 单独生成校验报告
python3 scripts/verify_thesis_report.py --image-name "AI 硬件" --db thesis.db --output-dir output/AI硬件 --fixed-name
```

---

### 关键脚本

| 脚本 | 步骤 | 说明 |
|------|------|------|
| `thesis-ingest/scripts/process_thesis_image.py` | 编排 | 6 步管道的一键入口，自动传递参数。支持 `--model qwen\|copilot` 切换识图模型。输出按题材名归档到 `output/{题材名}/`，每次运行清空重建 |
| `thesis-ingest/scripts/plan_semantic_cuts.py` | Step 1 | **红色水平线检测**（OpenCV）定位切割边界 + 多模态模型识别子题材名称 |
| `thesis-ingest/scripts/split_by_path_plan.py` | Step 2 | 按切割方案裁剪图片，生成 segment PNG + manifest |
| `thesis-ingest/scripts/parse_path_segments_mm.py` | Step 3 | **4 路并发**多模态解析每个 segment，带重试机制（最多 3 次），失败则终止流程。支持 `--model qwen\|copilot` 和 `--root-name` |
| `thesis-ingest/scripts/expand_path_ancestors.py` | Step 4 | 将层级路径展开为祖先候选（纯 JSON 变换） |
| `thesis-ingest/scripts/insert_thesis_tree.py` | Step 5 | 构建树结构，查找股票代码，写入 SQLite。支持 `--root-name` 将所有子题材挂在同一根节点下 |
| `thesis-ingest/scripts/verify_thesis_report.py` | Step 6 | 从数据库回读完整树结构，生成 Markdown 校验报告（层级缩进 + 成分股名称代码 + 节点描述），方便对照原始截图校验 |

#### 识图模型

| 模型 | 参数 | 端点 | 速度 | 费用 |
|------|------|------|------|------|
| qwen3.6-plus (百炼) | `--model qwen` (默认) | `coding.dashscope.aliyuncs.com/v1` | ~3-5 秒/segment | 有额度限制 |
| gpt-5-mini (Copilot) | `--model copilot` | Copilot SDK (本地 GitHub 登录) | ~30-60 秒/segment | 免费 (Copilot 订阅) |

两种模型通过 prompt 中的结构化规则（题材 vs 股票区分、股票名 ≤5 字、根题材名告知）保证识别质量一致。

---

### 切割方案设计（plan_semantic_cuts.py）

**核心挑战**：多模态模型对 y 坐标的估计偏差太大（最大偏差 1000px+），导致切割不准确。

**解决方案**：将"识别名称"和"定位坐标"拆成两个独立步骤：

1. **OpenCV 红色水平线检测**（像素级精确）：开盘啦 APP 中每个一级子题材之间有横跨全宽的红色分隔线。通过红色像素水平投影，精确定位分界线的 y 坐标。
2. **多模态模型只列名称**（不猜坐标）：模型只负责识别根题材和一级子题材的名称/顺序。
3. **名称与边界匹配**：将红色分界线作为 segment 边界，再把模型给出的名称依次匹配上去。

**关键参数**：
- `top_skip_ratio=0.10` — 跳过顶部 APP 标题栏（占图片高度 10%）
- `bottom_skip_px=50` — 跳过底部 UI（固定 50 像素，不使用比例，避免裁切后图片误过滤有效红线）

---

### 数据库结构

每张原始截图 → `thesis_catalog` 一行 + 一对动态表：

#### thesis_catalog（题材总目录）

```sql
CREATE TABLE thesis_catalog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_name TEXT NOT NULL UNIQUE,   -- 根题材名，如 "AI 硬件"
    source_image TEXT,                  -- 原始截图文件名
    description TEXT,                   -- 题材描述
    total_stock_count INTEGER DEFAULT 0,
    node_count INTEGER DEFAULT 0,       -- 总节点数（不含股票）
    created_at TEXT,
    updated_at TEXT
);
```

#### thesis_tree_{md5[:8]}（树节点表）

```sql
CREATE TABLE thesis_tree_{suffix} (
    node_id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER,                  -- NULL = 根节点
    node_name TEXT NOT NULL,
    node_type TEXT CHECK(node_type IN ('root','first_level','second_level')),
    depth INTEGER NOT NULL DEFAULT 0,   -- 0=根, 1=一级, 2=二级
    description TEXT,
    full_path TEXT NOT NULL UNIQUE,      -- "AI 硬件 / 光模块 / CPO"
    sort_order INTEGER DEFAULT 0,
    created_at TEXT,
    updated_at TEXT,
    FOREIGN KEY (parent_id) REFERENCES self(node_id)
);
```

#### thesis_stocks_tree_{md5[:8]}（成分股表）

```sql
CREATE TABLE thesis_stocks_tree_{suffix} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id INTEGER NOT NULL,           -- FK → tree node
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    stock_description TEXT,              -- 归属原因
    created_at TEXT,
    FOREIGN KEY (node_id) REFERENCES thesis_tree_{suffix}(node_id),
    UNIQUE(node_id, stock_code)
);
```

表名 suffix 规则：`md5(image_name)[:8]`

---

### 查询接口（thesis_api.py）

```python
from thesis_ingest_api import *

# 获取所有主题材
list_all_thesis()
# → [{image_name, description, total_stock_count, node_count}, ...]

# 获取完整树结构
get_full_tree("AI 硬件")
# → {image_name, nodes: [{node_id, parent_id, node_name, node_type, depth, full_path}, ...]}

# 获取某题材的子题材
get_child_theses("AI 硬件", "AI 硬件")
# → [{node_name, node_type, full_path, description, stock_count}, ...]

# 获取成分股
get_constituent_stocks("AI 硬件", "液冷相关", "冷却液")
# → [{stock_code, stock_name, stock_description}, ...]

# 获取父题材
get_parent_thesis("AI 硬件", "AI 硬件 / 光模块 / CPO")
# → {node_name, node_type, full_path, description}
```

#### CLI 调试

```bash
python3 thesis-ingest/scripts/thesis_api.py list
python3 thesis-ingest/scripts/thesis_api.py tree "AI 硬件"
python3 thesis-ingest/scripts/thesis_api.py stocks "AI 硬件" "液冷相关"
python3 thesis-ingest/scripts/thesis_api.py children "AI 硬件" "AI 硬件"
python3 thesis-ingest/scripts/thesis_api.py parent "AI 硬件" "AI 硬件 / 光模块 / CPO"
```

---

### 查看数据库

```bash
sqlite3 thesis-ingest/thesis.db ".tables"
sqlite3 thesis-ingest/thesis.db "SELECT * FROM thesis_catalog;"
sqlite3 thesis-ingest/thesis.db "SELECT node_id, parent_id, node_name, node_type, depth FROM thesis_tree_c232d19b ORDER BY node_id;"
sqlite3 thesis-ingest/thesis.db "SELECT * FROM thesis_stocks_tree_c232d19b LIMIT 10;"
```

---

### 已知注意事项

1. **并发数**：Step 3 默认 4 路并发调用 LLM，超过 4 路可能触发 API 限流导致部分 segment 失败
2. **重试机制**：Step 3 每个 segment 最多重试 2 次（共 3 次调用），全部失败则终止流程
3. **超时**：Step 3 的 subprocess 超时为 600 秒，16 个 segment 并发约需 1-2 分钟（qwen）或 5-10 分钟（copilot）
4. **`--root-name`**：当一张截图被切成多个 segment 时，每个 segment 的 path_raw 以一级题材名开头。`--root-name` 参数确保所有子题材挂在同一根节点下，而不是各自成为独立根题材。同时在 Step 3 的 prompt 中告知模型根题材名，帮助 path_raw 生成正确前缀
5. **`get_latest_file`**：自动排除 `*_run_*.json` 运行记录文件，避免 Step 4 拿到空数据
6. **股票名模糊匹配**：`stock_lookup_service` 在精确匹配和空格变体都失败后，会用 Levenshtein 编辑距离（≤1）做模糊匹配，修正 LLM 的 OCR 近形字错误（如 骄→骐、新能→新能源）。匹配结果标记 `match_type: "fuzzy"`

---

*最后更新：2026-04-12*
