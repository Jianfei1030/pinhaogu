# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Chinese stock market concept-sector monitoring and analysis system (概念板块监控与分析系统). Monitors A-share and Hong Kong stock concept sectors with real-time price alerts, pre/post-market analysis, news collection with embedding-based deduplication, and a FastAPI web dashboard.

## Directory Layout

All application code lives under `workspace/`. This is not a Python package — scripts are run directly from this directory.

```
workspace/
├── server.py                      # FastAPI web backend (port 18805)
├── monitor.py                     # Real-time monitoring engine (60s loop)
├── premarket_analysis.py          # Pre-market concept-sector analysis (Job Runner)
├── premarket_thesis_analysis.py   # Pre-market thesis-based analysis (Phase 34, parallel to above)
├── postmarket_review.py           # Post-market review script (Job Runner)
├── daily_news_collector.py        # News collector (600s interval)
├── daily_incremental_backfill.py  # Daily A-share data backfill (16:30, parallel workers)
├── config.py                      # Unified config: env > config.yaml > defaults
├── config.yaml                    # Main YAML config (watchlist, alerts, trading hours, etc.)
├── database.py                    # SQLite persistence (per-stock-per-date .db files)
├── aggregator.py                  # K-line period aggregation (1min → 5/15/30/60/120min)
├── calc_chip_dist.py              # Chip distribution calculation (used by backfill + premarket)
├── start_all.sh                   # One-click startup (server + monitor + news)
├── services/                      # Business logic service layer (16+ modules)
├── data_sources/                  # Data adapters: tencent (HK), sina (A-share), akshare, yfinance
├── indicators/                    # Pluggable indicator engine (MACD, KDJ)
├── screener/                      # Stock screener with conditions engine
├── utils/                         # push.py (Telegram+QQ), logger.py, trading_calendar.py
├── static/                        # Frontend: native HTML/CSS/JS with Canvas charting
└── tests/                         # pytest test suite

thesis-ingest/                     # OCR-based thesis/sector ingestion (separate sub-project)
├── scripts/                       # process_thesis_image.py (6-step pipeline entry), thesis_api.py, etc.
├── thesis.db                      # SQLite: thesis_catalog + thesis_tree_* + thesis_stocks_tree_* tables
└── output/                        # 按题材名归档: output/{题材名}/cut_plan.json, segments/, etc.
```

## Commands

### Run the full system
```bash
cd workspace && ./start_all.sh
```
Starts three background processes: `server.py`, `monitor.py --config config.yaml --interval 60`, `daily_news_collector.py --interval 600`.

### Run individual scripts
```bash
cd workspace
python3 server.py                                    # Web server only
python3 monitor.py --config config.yaml --interval 60 # Monitor only
python3 premarket_analysis.py --date 2026-04-06 --dry-run
python3 postmarket_review.py --date 2026-04-06
python3 daily_incremental_backfill.py --date 2026-04-06 --dry-run  # Backfill (normally auto at 16:30)
python3 premarket_thesis_analysis.py --dry-run       # Thesis-based pre-market analysis
python3 premarket_thesis_analysis.py --date 2026-04-12  # Works on non-trading days too

# Thesis ingest (6-step pipeline: red line detection → split → MM parse → expand → insert → verify)
cd thesis-ingest
python3 scripts/process_thesis_image.py --image input_images/xxx.jpg              # Full pipeline (qwen default), output → output/{题材名}/
python3 scripts/process_thesis_image.py --image input_images/xxx.jpg --model copilot  # Use free Copilot model
python3 scripts/verify_thesis_report.py --image-name "AI 硬件" --db thesis.db     # Generate verify report only
```

### Tests
```bash
cd workspace
pytest tests/                          # Full suite
pytest tests/test_monitor_service.py   # Single file
pytest tests/test_aggregator.py::test_name  # Single test
```
`tests/conftest.py` adds the workspace directory to `sys.path` automatically.

### Health check
```bash
cd workspace && ./check_health.sh
```

### Compile check (no formal linter configured)
```bash
python3 -m py_compile <file.py>
```

## Architecture

### Layered modular monolith

```
Entry Points (thin wrappers)
  server.py / monitor.py / premarket_analysis.py / postmarket_review.py
       ↓
Services Layer (workspace/services/)
  alert_service, analysis_service, config_service, llm_service,
  market_data_service, monitor_*_service (5 sub-modules),
  news_service, push_service, quote_service, report_service,
  runtime_state_service, stock_lookup_service, trading_calendar_service
       ↓
Data Access Layer
  data_sources/ (tencent, sina, akshare, yfinance adapters)
  database.py (SQLite per-stock-per-date .db files under data/{market}/{market}{symbol}/)
  board_db.py (sector/board data)
  aggregator.py (1min → multi-period K-line aggregation)
       ↓
Indicators Layer (pluggable via IndicatorEngine.load_from_dir())
  indicators/macd.py, indicators/kdj.py
```

### Key data flow (monitoring)
1. `monitor.py` runs a 60-second loop
2. Fetches real-time quotes via `data_sources/` (Tencent for HK, Sina for A-shares)
3. Stores 1min K-line data in SQLite via `database.py`
4. Aggregates into 5/15/30/60/120min periods via `aggregator.py`
5. Calculates MACD indicators via `indicators/macd.py`
6. Evaluates alert rules from `config.yaml` via `services/alert_service.py`
7. Pushes alerts via `utils/push.py` (Telegram + QQ dual-channel)

### Key data flow (daily backfill)
1. `daily_incremental_backfill.py` runs at 16:30 (triggered by `monitor.py`)
2. Reads all 5497+ A-share symbols from `data/a_stock_list.json` (includes 303 BJ stocks, 920xxx)
3. For each stock: loads historical K-lines from local DB → fetches today's 1 bar from data source → concatenates → calculates MACD + chip distribution → writes to `kline_1d` table
4. Uses `ProcessPoolExecutor` with configurable workers (default 4)
5. `_infer_a_prefix()` maps `920xxx → bj`, `6xxxxx → sh`, `0xxxxx/3xxxxx → sz`

### Data storage layout
```
data/
├── A/                    # A-shares (includes BJ stocks)
│   ├── A600000/          # Each stock: data/A/A{symbol}/{date}.db
│   ├── A920062/          # BJ stocks stored here too (A920xxx)
│   └── ...
├── HK/                   # Hong Kong stocks
│   └── HK{symbol}/
├── board/                # Sector/board data
├── a_stock_list.json     # All A-share symbols (5497+, includes 303 BJ)
└── thesis.db             # Thesis/sector database (for premarket_thesis_analysis)
```

### Indicator plugin system
Indicators use a pluggable architecture. `IndicatorEngine` auto-discovers `.py` files in `indicators/` that define `INDICATOR_META` dict and an `IndicatorBase` subclass. Add new indicators by creating a new `.py` file in `indicators/` following the MACD/KDJ pattern.

### Config system (`config.py`)
Three-tier priority: environment variables (`STOCK_MONITOR_*` or direct keys) > `config.yaml` > hardcoded defaults. Access via `get_config('key.path')` or the `config` dataclass instance.

## Key Dependencies

- Python 3.10 (enforced by `start_all.sh`)
- Core: pandas, requests, fastapi, uvicorn, pyyaml
- Data: akshare (A-share), yfinance (HK), tencent/sina APIs (real-time)
- External: Ollama on port 13145 (news embeddings), Bailian API key in `BAILIAN_API_KEY` env var (LLM)
- Thesis ingest: qwen3.6-plus via Bailian coding plan (default), gpt-5-mini via Copilot SDK (free backup), OpenCV for red line detection
- Virtual env at `workspace/venv/` (primary, Python 3.10)

## Configuration

- `workspace/config.yaml` — watchlist, trading hours, alert rules, data source URLs, DB paths, LLM settings, web port
- `workspace/holidays_2026.yaml` — Chinese holiday calendar for trading day checks
- `workspace/data/` — runtime data: `A/` (A-shares incl. BJ 920xxx), `HK/` (HK stocks), `board/` (sector data), `a_stock_list.json`
- `thesis-ingest/thesis.db` — thesis catalog + stock tables for premarket thesis analysis

## Documentation

- `README.md` — full project documentation (Chinese)
- `ARCHITECTURE_NEXT.md` — architecture refactoring plan
- `DECISIONS.md` — key technical decisions
- `design.md` — design document with refactoring phases
- `tasks.md` — task board / progress tracker
- `docs/frontend_*.md` — frontend baseline and regression checklists
- `thesis-ingest/README.md` — thesis ingest pipeline docs (6-step pipeline, dual model, DB schema)
- `thesis-ingest/design.md` — thesis ingest design (red line detection, tree schema, MM parsing)
- `thesis-ingest/DECISIONS.md` — thesis ingest decision log (13 decisions)
