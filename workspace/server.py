# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import math
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

try:
    import psutil  # type: ignore
except Exception:  # noqa: BLE001
    psutil = None
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from aggregator import run_pipeline
from database import get_db_path, list_db_dates, query_kline, query_kline_multi_days
from board_db import get_board_snapshots as _get_board_snapshots, get_board_stocks as _get_board_stocks, get_board_history as _get_board_history
from data_source import DataSourceError, fetch_daily, fetch_realtime
from indicators import IndicatorEngine
from indicators.macd import MACD
from monitor import AlertRule
from services.market_data_service import (
    get_kline_api_payload,
    MarketDataError,
    MarketDataNotFoundError,
)
from services.alert_service import (
    list_alerts,
    add_alert,
    update_alert,
    delete_alert,
    AlertValidationError,
    AlertIndexError,
    AlertServiceError,
    AlertTestError,
    AlertTestNotFoundError,
    test_alert_rule,
)
from services.analysis_service import (
    start_daily_analysis,
    get_daily_analysis_status,
    get_daily_analysis_report_text,
    AnalysisConflictError,
    AnalysisNotFoundError,
    AnalysisPayloadError,
    AnalysisServiceError,
    read_analysis_status as read_analysis_status_service,
    analysis_is_running as analysis_is_running_service,
    resolve_analysis_report_path as resolve_analysis_report_path_service,
)
from services.report_service import (
    get_report,
    get_latest_report,
    get_report_status,
    ReportNotFoundError,
    ReportUnreadableError,
    ReportInvalidTypeError,
    ReportServiceError,
)
from services.news_service import (
    get_news_status,
    get_recent_news,
    normalize_news_date,
    is_news_collector_running,
)
from services.quote_service import build_quote_payload
from services.runtime_status_service import (
    build_monitor_status_payload,
    build_calibration_status_payload,
)
from services.config_service import build_config_payload

# 从统一配置读取数据路径
try:
    from config import get_config
    _DATA_ROOT = Path(get_config('data.root', 'data'))
    _NEWS_DIR = Path(get_config('data.news', 'news_data'))
except Exception:
    # Fallback: 使用硬编码默认值
    _DATA_ROOT = PROJECT_ROOT / "data"
    _NEWS_DIR = BASE_DIR / "news_data"

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
STATIC_DIR = BASE_DIR / "static"
CONFIG_PATH = BASE_DIR / "config.yaml"
DATA_DIR = PROJECT_ROOT / _DATA_ROOT
MONITOR_PID_PATH = DATA_DIR / ".monitor_pid"
LEGACY_MONITOR_PID_PATH = DATA_DIR / ".monitor_pid"  # 兼容旧进程锁文件
MONITOR_STATUS_PATH = DATA_DIR / ".monitor_status.json"
MONITOR_RELOAD_PATH = DATA_DIR / ".monitor_reload"
CALIBRATION_STATUS_PATH = DATA_DIR / ".calibration_status.json"
ANALYSIS_STATUS_PATH = DATA_DIR / ".analysis_status.json"  # 盘前分析状态
REVIEW_STATUS_PATH = DATA_DIR / ".review_status.json"      # 盘后复盘状态
PREMARKET_THESIS_STATUS_PATH = DATA_DIR / ".premarket_thesis_status.json"  # 盘前题材分析状态
ANALYSIS_RUNNING_STATUSES = {"loading", "analyzing", "sending", "saving"}
ANALYSIS_SCRIPT_PATH = BASE_DIR / "daily_sector_pipeline.py"
PREMARKET_SCRIPT_PATH = BASE_DIR / "premarket_analysis.py"
POSTMARKET_SCRIPT_PATH = BASE_DIR / "postmarket_review.py"
PREMARKET_THESIS_SCRIPT_PATH = BASE_DIR / "premarket_thesis_analysis.py"
REPORT_DIR = BASE_DIR / "reports"  # 统一使用 workspace/reports 目录
NEWS_DIR = BASE_DIR / _NEWS_DIR

DEFAULT_PERIODS = ["1min", "5min", "15min", "30min", "60min", "daily"]

AVAILABLE_INDICATORS = [
    {
        "name": "macd",
        "display": "MACD(12,26,9)",
        "columns": ["macd", "macd_dea", "macd_hist", "macd_slope", "dea_slope", "hist_slope"],
    }
]
DATE_FMT = "%Y-%m-%d"

app = FastAPI(title="HK Stock Monitor", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {"watchlist": [], "periods": DEFAULT_PERIODS}
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    config.setdefault("watchlist", [])
    config.setdefault("periods", DEFAULT_PERIODS)
    config.setdefault("alerts", [])
    return config


def save_config(config: dict[str, Any]) -> None:
    config.setdefault("watchlist", [])
    config.setdefault("periods", DEFAULT_PERIODS)
    config.setdefault("alerts", [])
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)


def trigger_monitor_reload() -> None:
    """通知 monitor.py 重新加载配置（写状态文件 + 尝试信号）"""
    # 写 reload 标记文件，monitor.py 每次 tick 会检查
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MONITOR_RELOAD_PATH.write_text(str(time.time()), encoding="utf-8")

    # 同时尝试通过 PID 文件发信号（如果 monitor 正在运行）
    pid_data = _read_monitor_pid_file()
    if pid_data:
        pid = int(pid_data.get("pid") or 0)
        if pid > 0 and _pid_running(pid):
            try:
                import signal as _signal
                os.kill(pid, _signal.SIGTERM)
            except Exception:
                pass  # Windows 上 SIGTERM 可能不可用，忽略


def normalize_date(value: str | None) -> str:
    if value:
        return datetime.strptime(str(value).strip(), DATE_FMT).strftime(DATE_FMT)
    return datetime.now().strftime(DATE_FMT)


def resolve_db_path(market: str, symbol: str, date: str) -> Path:
    return PROJECT_ROOT / get_db_path(market, symbol, date)


def ensure_db(market: str, symbol: str, date: str) -> Path:
    db_path = resolve_db_path(market, symbol, date)
    if db_path.exists():
        return db_path
    generated = Path(run_pipeline(symbol=symbol, market=market, date=date))
    return generated if generated.is_absolute() else (PROJECT_ROOT / generated)


def get_watch_item(config: dict[str, Any], market: str, symbol: str) -> dict[str, Any] | None:
    for item in config.get("watchlist", []):
        if str(item.get("market", "")).upper() == market and str(item.get("symbol", "")).strip() == symbol:
            return item
    return None


def _period_table(period: str) -> str:
    if period not in DEFAULT_PERIODS:
        raise HTTPException(status_code=400, detail=f"Unsupported period: {period}")
    if period == "daily":
        return "kline_daily"
    return f"kline_{period}"


def _iter_previous_dates(target_date: str, limit: int = 12) -> list[str]:
    dt = datetime.strptime(target_date, DATE_FMT)
    result = []
    for i in range(limit):
        result.append(dt.strftime(DATE_FMT))
        dt = dt.fromordinal(dt.toordinal() - 1)
    return result


def _days_needed_for_macd(period: str) -> int:
    """
    根据 K 线周期计算需要加载多少天的历史数据才能保证 MACD 计算准确。
    MACD(12,26,9) 需要至少 34 根 bar 才能收敛，推荐 500+ 根以匹配东财数值。
    """
    # 每个周期一天大约有多少根 K 线（港股交易时间约 4 小时）
    bars_per_day = {
        "1min": 240,
        "5min": 48,
        "15min": 16,
        "30min": 8,
        "60min": 4,
    }
    
    bars = bars_per_day.get(period, 4)
    
    # 目标 bar 数：至少 500 根，确保 MACD 充分收敛并与东财对齐
    min_bars = 500
    days = min(120, max(30, min_bars // bars + 1))  # 至少 30 天，最多 120 天
    
    return days


def _load_multi_day_rows(market: str, symbol: str, period: str, target_date: str) -> tuple[list[dict], list[dict]]:
    table = _period_table(period)
    
    # 根据周期动态计算需要加载多少天的历史数据
    days_to_load = _days_needed_for_macd(period)
    
    # 获取已知的数据库日期
    known_dates = [d for d in list_db_dates(market, symbol, db_dir=str(PROJECT_ROOT)) if d <= target_date]
    if target_date not in known_dates:
        known_dates.insert(0, target_date)
    known_dates = sorted(set(known_dates), reverse=True)
    
    # 使用 query_kline_multi_days 加载历史数据（静默跳过不存在的数据库）
    dates_to_query = list(reversed(known_dates[:days_to_load]))
    rows_via_api = query_kline_multi_days(
        market,
        symbol,
        table,
        dates_to_query,
        db_dir=str(PROJECT_ROOT),
    )

    # 逐日读取数据，保留真实时间顺序，用于 MACD 计算
    # 这样可以确保 bar_time 带有日期信息，避免跨天合并时被覆盖
    history_rows: list[dict] = []
    
    # 构建候选日期列表：优先使用已知日期，不足时往前追溯
    candidate_dates = []
    for date in known_dates:
        if date not in candidate_dates:
            candidate_dates.append(date)
    
    # 如果已知日期不足，往前追溯
    for date in _iter_previous_dates(target_date, limit=days_to_load):
        if date not in candidate_dates:
            candidate_dates.append(date)
    
    # 只取需要的天数
    candidate_dates = candidate_dates[:days_to_load]

    # 逐日读取数据
    for date in candidate_dates:
        db_path = resolve_db_path(market, symbol, date)
        if not db_path.exists():
            # 静默跳过不存在的数据库（回退机制）
            continue
        day_rows = query_kline(str(db_path), table)
        for row in day_rows:
            bt = row["bar_time"]
            # bar_time format is "HH:MM" (5 chars), calc_time should be "YYYY-MM-DD HH:MM"
            history_rows.append(
                {
                    "calc_time": f"{date} {bt}",
                    "bar_time": bt,
                    "open": row.get("open"),
                    "high": row.get("high"),
                    "low": row.get("low"),
                    "close": row.get("close"),
                    "volume": row.get("volume"),
                    "amount": row.get("amount"),
                    "date": date,
                }
            )

    # 按时间排序
    history_rows.sort(key=lambda x: x["calc_time"])

    # 提取目标日期的数据
    target_rows = [row for row in history_rows if row["date"] == target_date]
    
    # 如果目标日期没有数据，使用 API 查询的结果作为回退
    if not target_rows and rows_via_api:
        target_rows = [
            {
                "calc_time": f"{target_date} {row['bar_time']}",
                "bar_time": row["bar_time"],
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("volume"),
                "amount": row.get("amount"),
                "date": target_date,
            }
            for row in rows_via_api
        ]

    return history_rows, target_rows


def _calc_macd_payload(history_rows: list[dict], target_rows: list[dict]) -> tuple[list[dict], str, dict[str, int]]:
    if not target_rows:
        raise HTTPException(status_code=404, detail="No kline data found for target date")

    df = pd.DataFrame(history_rows, columns=["calc_time", "bar_time", "open", "high", "low", "close", "volume", "amount", "date"])
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    engine = IndicatorEngine()
    macd_indicator = MACD(12, 26, 9)
    engine.register(macd_indicator)
    result = engine.calc_all(df)

    status = result.attrs.get("macd_data_status", "low")
    info = result.attrs.get("macd_data_info", {})
    target_times = {(row["date"], row["bar_time"]) for row in target_rows}
    target_result = result[result.apply(lambda r: (r["date"], r["bar_time"]) in target_times, axis=1)].copy()
    target_result = target_result.sort_values(by=["calc_time"])

    macd_payload = [
        {
            "time": str(row["bar_time"])[-5:],
            "macd": _safe_number(row.get("macd")),
            "dea": _safe_number(row.get("macd_dea")),
            "hist": _safe_number(row.get("macd_hist")),
            "macd_slope": _safe_number(row.get("macd_slope")),
            "dea_slope": _safe_number(row.get("macd_dea_slope")),
            "hist_slope": _safe_number(row.get("macd_hist_slope")),
        }
        for _, row in target_result.iterrows()
    ]
    return macd_payload, status, {
        "bars": int(info.get("bars", len(history_rows))),
        "min": int(info.get("min", macd_indicator.MIN_BARS)),
        "recommend": int(info.get("recommend", 105)),
    }


def _calc_daily_payload(market: str, symbol: str, target_date: str) -> tuple[list[dict], list[dict], str, dict[str, int], float | None, float | None]:
    daily_rows = fetch_daily(symbol, "2025-01-01", target_date, 300, market=market)
    if not daily_rows:
        raise HTTPException(status_code=404, detail=f"No daily kline data found for {symbol} {target_date}")

    history_rows = [
        {
            "calc_time": row["date"],
            "bar_time": row["date"],
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "close": row.get("close"),
            "volume": row.get("volume"),
            "amount": 0,
            "date": row["date"],
        }
        for row in daily_rows
    ]

    df = pd.DataFrame(history_rows, columns=["calc_time", "bar_time", "open", "high", "low", "close", "volume", "amount", "date"])
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    engine = IndicatorEngine()
    macd_indicator = MACD(12, 26, 9)
    engine.register(macd_indicator)
    result = engine.calc_all(df)

    status = result.attrs.get("macd_data_status", "low")
    info = result.attrs.get("macd_data_info", {})
    data_info = {
        "bars": int(info.get("bars", len(history_rows))),
        "min": int(info.get("min", macd_indicator.MIN_BARS)),
        "recommend": max(200, int(info.get("recommend", 200))),
    }

    kline_payload = [
        {
            "time": str(row.get("date", "")),
            "open": _safe_number(row.get("open")),
            "high": _safe_number(row.get("high")),
            "low": _safe_number(row.get("low")),
            "close": _safe_number(row.get("close")),
            "volume": int(float(row.get("volume") or 0)),
        }
        for row in daily_rows
    ]
    macd_payload = [
        {
            "time": str(row.get("bar_time", "")),
            "macd": _safe_number(row.get("macd")),
            "dea": _safe_number(row.get("macd_dea")),
            "hist": _safe_number(row.get("macd_hist")),
            "macd_slope": _safe_number(row.get("macd_slope")),
            "dea_slope": _safe_number(row.get("macd_dea_slope")),
            "hist_slope": _safe_number(row.get("macd_hist_slope")),
        }
        for _, row in result.iterrows()
    ]

    prev_close = float(daily_rows[-2]["close"]) if len(daily_rows) >= 2 else None
    today_close = float(daily_rows[-1]["close"]) if daily_rows else None
    return kline_payload, macd_payload, status, data_info, prev_close, today_close


def _safe_number(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        num = float(value)
        if math.isnan(num) or math.isinf(num):
            return 0.0
        return round(num, 6)
    except Exception:
        return 0.0


def _normalize_single_condition(item: Any, path: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise HTTPException(status_code=400, detail=f"{path} must be an object")

    indicator = str(item.get("indicator") or "").strip()
    op = str(item.get("op") or "").strip()
    if not indicator or not op:
        raise HTTPException(status_code=400, detail=f"{path} missing indicator/op")

    try:
        value = float(item.get("value"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"{path} has invalid value") from exc

    return {"indicator": indicator, "op": op, "value": value}



def _normalize_conditions_tree(node: Any, path: str = "conditions") -> Any:
    if isinstance(node, list):
        if not node:
            raise HTTPException(status_code=400, detail=f"{path} must be a non-empty list")
        return [_normalize_conditions_tree(item, f"{path}[{idx}]") for idx, item in enumerate(node)]

    if not isinstance(node, dict):
        raise HTTPException(status_code=400, detail=f"{path} must be an object or list")

    if "indicator" in node:
        return _normalize_single_condition(node, path)

    logic = str(node.get("logic", "AND") or "AND").upper()
    if logic not in {"AND", "OR"}:
        raise HTTPException(status_code=400, detail=f"{path}.logic must be AND or OR")

    rules = node.get("rules")
    if not isinstance(rules, list) or not rules:
        raise HTTPException(status_code=400, detail=f"{path}.rules must be a non-empty list")

    return {
        "logic": logic,
        "rules": [_normalize_conditions_tree(item, f"{path}.rules[{idx}]") for idx, item in enumerate(rules)],
    }



def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_monitor_pid_file() -> dict[str, Any] | None:
    pid_path = MONITOR_PID_PATH if MONITOR_PID_PATH.exists() else LEGACY_MONITOR_PID_PATH
    if not pid_path.exists():
        return None
    try:
        raw = pid_path.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    if not raw:
        return None

    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return None
    try:
        pid = int(lines[0])
    except Exception:
        return None

    result: dict[str, Any] = {"pid": pid}
    if len(lines) >= 2:
        result["start_time"] = lines[1]
    return result


@app.get("/")
def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/config")
def api_config() -> JSONResponse:
    result = build_config_payload(load_config)
    return JSONResponse(result)


@app.get("/api/quote/{symbol}")
def api_quote(symbol: str, market: str | None = None) -> JSONResponse:
    """Thin route: delegates to quote_service.build_quote_payload()"""
    config = load_config()
    result = build_quote_payload(config, symbol, market)
    return JSONResponse(result)


@app.get("/api/monitor/status")
def api_monitor_status() -> JSONResponse:
    """Thin route: delegates to runtime_status_service.build_monitor_status_payload()"""
    config = load_config()
    trading_hours = config.get("trading_hours", {})
    
    result = build_monitor_status_payload(
        monitor_status_path=MONITOR_STATUS_PATH,
        monitor_pid_primary_path=MONITOR_PID_PATH,
        monitor_pid_legacy_path=LEGACY_MONITOR_PID_PATH,
        trading_hours=trading_hours,
    )
    return JSONResponse(result)


@app.get("/api/calibration/status")
def api_calibration_status(date: str | None = Query(None)) -> JSONResponse:
    """Thin route: delegates to runtime_status_service.build_calibration_status_payload()"""
    target_date = normalize_date(date) if date else datetime.now().strftime(DATE_FMT)
    
    result = build_calibration_status_payload(
        target_date=target_date,
        calibration_status_path=CALIBRATION_STATUS_PATH,
    )
    return JSONResponse(result)


@app.get("/api/alerts")
def api_get_alerts() -> JSONResponse:
    config = load_config()
    alerts = list_alerts(config)
    return JSONResponse({"alerts": alerts})


@app.post("/api/alerts")
async def api_add_alert(request: Request) -> JSONResponse:
    payload = await request.json()
    config = load_config()
    try:
        alerts = add_alert(config, payload)
    except AlertValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AlertServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    config["alerts"] = alerts
    save_config(config)
    trigger_monitor_reload()
    return JSONResponse({"alerts": alerts})


@app.put("/api/alerts/{index}")
async def api_update_alert(index: int, request: Request) -> JSONResponse:
    payload = await request.json()
    config = load_config()
    try:
        alerts = update_alert(config, index, payload)
    except AlertIndexError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except AlertValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AlertServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    config["alerts"] = alerts
    save_config(config)
    trigger_monitor_reload()
    return JSONResponse({"alerts": alerts})


@app.delete("/api/alerts/{index}")
def api_delete_alert(index: int) -> JSONResponse:
    config = load_config()
    try:
        alerts = delete_alert(config, index)
    except AlertIndexError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except AlertServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    config["alerts"] = alerts
    save_config(config)
    trigger_monitor_reload()
    return JSONResponse({"alerts": alerts})


@app.get("/api/indicators")
def api_get_indicators() -> JSONResponse:
    return JSONResponse({"indicators": AVAILABLE_INDICATORS})


@app.post("/api/indicators/reload")
def api_reload_indicators() -> JSONResponse:
    trigger_monitor_reload()
    return JSONResponse({"status": "reload triggered", "indicators": AVAILABLE_INDICATORS})


@app.post("/api/alerts/test")
async def api_test_alert(request: Request) -> JSONResponse:
    """Thin route: delegates to alert_service.test_alert_rule()"""
    payload = await request.json()
    config = load_config()
    
    try:
        result = test_alert_rule(payload, config, normalize_date_fn=normalize_date)
    except AlertValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AlertTestNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except AlertTestError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return JSONResponse(result)


@app.get("/api/kline")
def api_kline(
    symbol: str = Query(..., min_length=1),
    period: str = Query("15min"),
    date: str = Query(...),
    market: str = Query("HK"),
):
    config = load_config()
    market = str(market).upper().strip()
    symbol = str(symbol).strip()
    period = str(period).strip()
    target_date = normalize_date(date)

    watch_item = get_watch_item(config, market, symbol) or {}
    name = str(watch_item.get("name") or symbol)

    try:
        payload = get_kline_api_payload(
            market=market,
            symbol=symbol,
            period=period,
            target_date=target_date,
            name=name,
        )
        return JSONResponse(payload)
    except MarketDataNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except MarketDataError as e:
        raise HTTPException(status_code=400, detail=str(e))


# === 选股 API ===
import sys as _sys

_SCREENER_DIR = Path(__file__).parent / "screener"
if str(_SCREENER_DIR) not in _sys.path:
    _sys.path.insert(0, str(_SCREENER_DIR))

from screener import list_conditions, list_sectors, screen_stocks


@app.get("/api/screener/conditions")
def get_screener_conditions():
    """返回可用条件类型"""
    return {"conditions": list_conditions()}


@app.get("/api/screener/sectors")
def get_screener_sectors():
    """返回板块列表"""
    return {"sectors": list_sectors()}


@app.post("/api/screener/run")
def run_screener(req: dict):
    """
    执行选股
    body: {"conditions": [{"type": "sector", "sector_code": "new_blhy"}, ...]}
    """
    conditions = req.get("conditions", [])
    results = screen_stocks(conditions)
    return {"count": len(results), "results": results}


@app.post("/api/analysis/daily")
async def api_start_daily_analysis(request: Request) -> JSONResponse:
    """Thin route: delegates to analysis_service.start_daily_analysis()"""
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    if payload is None:
        payload = {}

    try:
        result = start_daily_analysis(
            payload=payload,
            status_path=ANALYSIS_STATUS_PATH,
            script_path=ANALYSIS_SCRIPT_PATH,
            base_dir=BASE_DIR,
            normalize_date_fn=normalize_date,
            running_statuses=ANALYSIS_RUNNING_STATUSES,
        )
        return JSONResponse(result)
    except AnalysisPayloadError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AnalysisConflictError as e:
        # Extract date from error message for backward compatibility
        conflict_date = None
        error_msg = str(e)
        if "date:" in error_msg:
            conflict_date = error_msg.split("date:")[-1].strip().strip("()")
        return JSONResponse(
            {"status": "conflict", "message": error_msg, "date": conflict_date},
            status_code=409,
        )
    except AnalysisServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/analysis/status")
def api_get_daily_analysis_status(date: str | None = Query(None)) -> JSONResponse:
    """Thin route: delegates to analysis_service.get_daily_analysis_status()"""
    target_date = normalize_date(date) if date else None
    result = get_daily_analysis_status(
        target_date=target_date,
        status_path=ANALYSIS_STATUS_PATH,
        normalize_date_fn=normalize_date,
    )
    return JSONResponse(result)


@app.get("/api/news/status")
async def news_status(date: str | None = Query(default=None)) -> JSONResponse:
    """Thin route: delegates to news_service.get_news_status()"""
    target_date = normalize_news_date(date)
    result = get_news_status(
        news_dir=NEWS_DIR,
        target_date=target_date,
        psutil_module=psutil,
        subprocess_run=subprocess.run,
    )
    return JSONResponse(result)


@app.get("/api/news/recent")
async def news_recent(
    date: str | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=5000),
    after: str | None = Query(default=None),
) -> JSONResponse:
    """Thin route: delegates to news_service.get_recent_news()"""
    # Support "today" keyword for backward compatibility
    if date and str(date).lower() == "today":
        date = None  # normalize_news_date will use today
    
    target_date = normalize_news_date(date)
    result = get_recent_news(
        news_dir=NEWS_DIR,
        target_date=target_date,
        limit=limit,
        after=after,
    )
    return JSONResponse(result)


@app.get("/api/analysis/report")
def api_get_daily_analysis_report(date: str | None = Query(None)) -> PlainTextResponse:
    """Thin route: delegates to analysis_service.get_daily_analysis_report_text()"""
    target_date = normalize_date(date) if date else None
    try:
        report_text = get_daily_analysis_report_text(
            target_date=target_date,
            report_dir=REPORT_DIR,
            normalize_date_fn=normalize_date,
        )
        return PlainTextResponse(report_text, media_type="text/markdown")
    except AnalysisNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ─── 盘前分析 & 盘后复盘 API ──────────────────────────────────────────────
# Thin routes: delegate to report_service

@app.get("/api/premarket/report")
def api_premarket_report(date: str | None = Query(None)) -> JSONResponse:
    """返回指定日期的盘前分析报告 JSON"""
    target_date = normalize_date(date) if date else datetime.now().strftime(DATE_FMT)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        data = get_report(REPORT_DIR, 'premarket', target_date)
    except ReportNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ReportUnreadableError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ReportInvalidTypeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ReportServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse(data)


@app.get("/api/premarket/latest")
def api_premarket_latest() -> JSONResponse:
    """返回最近一次盘前分析报告"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        data = get_latest_report(REPORT_DIR, 'premarket')
    except ReportNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ReportUnreadableError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ReportInvalidTypeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ReportServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse(data)


@app.get("/api/premarket/status")
def api_premarket_status(date: str | None = Query(None)) -> JSONResponse:
    """返回盘前分析状态（是否存在报告 + 是否正在运行）"""
    target_date = normalize_date(date) if date else datetime.now().strftime(DATE_FMT)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        # 获取报告存在状态
        report_status = get_report_status(REPORT_DIR, 'premarket', target_date)

        # 获取分析运行状态（从 analysis_status.json）
        analysis_status = read_analysis_status_service(ANALYSIS_STATUS_PATH)

        # 如果分析状态存在且日期匹配，合并到响应中
        if analysis_status and analysis_status.get('date') == target_date:
            report_status['status'] = analysis_status.get('status', 'idle')
            report_status['progress'] = analysis_status.get('progress', 0)
            report_status['current_step'] = analysis_status.get('current_step', '')
            report_status['news_count'] = analysis_status.get('news_count', 0)
            report_status['board_name'] = analysis_status.get('board_name', '')
            report_status['board_code'] = analysis_status.get('board_code', '')
        else:
            # 没有运行中的分析，根据报告是否存在设置状态
            report_status['status'] = 'done' if report_status.get('exists') else 'idle'
            report_status['progress'] = 100 if report_status.get('exists') else 0
            report_status['current_step'] = '分析完成' if report_status.get('exists') else '未开始'

    except ReportInvalidTypeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ReportServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse(report_status)


@app.post("/api/premarket/run")
async def api_premarket_run(request: Request) -> JSONResponse:
    """启动盘前分析（复用 /api/analysis/daily 逻辑）"""
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    if payload is None:
        payload = {}

    try:
        result = start_daily_analysis(
            payload=payload,
            status_path=ANALYSIS_STATUS_PATH,
            script_path=PREMARKET_SCRIPT_PATH,
            base_dir=BASE_DIR,
            normalize_date_fn=normalize_date,
            running_statuses=ANALYSIS_RUNNING_STATUSES,
        )
        return JSONResponse(result)
    except AnalysisPayloadError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AnalysisConflictError as e:
        conflict_date = None
        error_msg = str(e)
        if "date:" in error_msg:
            conflict_date = error_msg.split("date:")[-1].strip().strip("()")
        return JSONResponse(
            {"status": "conflict", "message": error_msg, "date": conflict_date},
            status_code=409,
        )
    except AnalysisServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/review/report")
def api_review_report(date: str | None = Query(None)) -> JSONResponse:
    """返回指定日期的复盘报告 JSON"""
    target_date = normalize_date(date) if date else datetime.now().strftime(DATE_FMT)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        data = get_report(REPORT_DIR, 'review', target_date)
    except ReportNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ReportUnreadableError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ReportInvalidTypeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ReportServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse(data)


@app.get("/api/premarket/history")
def api_premarket_history() -> JSONResponse:
    """返回盘前分析报告历史日期列表"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    pattern = "premarket_*.json"
    candidates = sorted(REPORT_DIR.glob(pattern), reverse=True)
    dates = []
    for path in candidates:
        match = path.stem.replace("premarket_", "").replace("_", "-")
        # Convert YYYYMMDD to YYYY-MM-DD
        if len(match) == 8:
            dates.append(f"{match[:4]}-{match[4:6]}-{match[6:]}")
    return JSONResponse({"dates": dates})


@app.get("/api/review/history")
def api_review_history() -> JSONResponse:
    """返回复盘报告历史日期列表"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    pattern = "review_*.json"
    candidates = sorted(REPORT_DIR.glob(pattern), reverse=True)
    dates = []
    for path in candidates:
        match = path.stem.replace("review_", "").replace("_", "-")
        # Convert YYYYMMDD to YYYY-MM-DD
        if len(match) == 8:
            dates.append(f"{match[:4]}-{match[4:6]}-{match[6:]}")
    return JSONResponse({"dates": dates})


@app.get("/api/review/latest")
def api_review_latest() -> JSONResponse:
    """返回最近一次复盘报告"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        data = get_latest_report(REPORT_DIR, 'review')
    except ReportNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ReportUnreadableError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ReportInvalidTypeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ReportServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse(data)


@app.get("/api/review/status")
def api_review_status(date: str | None = Query(None)) -> JSONResponse:
    """返回复盘报告状态（是否存在 + 是否正在运行），风格与 /api/premarket/status 保持一致"""
    target_date = normalize_date(date) if date else datetime.now().strftime(DATE_FMT)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        # 获取报告存在状态
        report_status = get_report_status(REPORT_DIR, 'review', target_date)

        # 获取复盘运行状态（从 review_status.json）
        review_status = read_analysis_status_service(REVIEW_STATUS_PATH)

        # 如果复盘状态存在且日期匹配，合并到响应中
        if review_status and review_status.get('date') == target_date:
            report_status['status'] = review_status.get('status', 'idle')
            report_status['progress'] = review_status.get('progress', 0)
            report_status['current_step'] = review_status.get('current_step', '')
        else:
            # 没有运行中的复盘，根据报告是否存在设置状态
            report_status['status'] = 'done' if report_status.get('exists') else 'idle'
            report_status['progress'] = 100 if report_status.get('exists') else 0
            report_status['current_step'] = '复盘完成' if report_status.get('exists') else '未开始'

    except ReportInvalidTypeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ReportServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse(report_status)


@app.post("/api/review/run")
async def api_review_run(request: Request) -> JSONResponse:
    """启动盘后复盘分析（复用 /api/premarket/run 逻辑）"""
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    if payload is None:
        payload = {}

    try:
        result = start_daily_analysis(
            payload=payload,
            status_path=REVIEW_STATUS_PATH,
            script_path=POSTMARKET_SCRIPT_PATH,
            base_dir=BASE_DIR,
            normalize_date_fn=normalize_date,
            running_statuses=ANALYSIS_RUNNING_STATUSES,
        )
        return JSONResponse(result)
    except AnalysisPayloadError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AnalysisConflictError as e:
        conflict_date = None
        error_msg = str(e)
        if "date:" in error_msg:
            conflict_date = error_msg.split("date:")[-1].strip().strip("()")
        return JSONResponse(
            {"status": "conflict", "message": error_msg, "date": conflict_date},
            status_code=409,
        )
    except AnalysisServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── 盘前题材分析 API ──────────────────────────────────────────

@app.post("/api/premarket-thesis/run")
async def api_premarket_thesis_run(request: Request) -> JSONResponse:
    """启动盘前题材分析"""
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    if payload is None:
        payload = {}

    try:
        result = start_daily_analysis(
            payload=payload,
            status_path=PREMARKET_THESIS_STATUS_PATH,
            script_path=PREMARKET_THESIS_SCRIPT_PATH,
            base_dir=BASE_DIR,
            normalize_date_fn=normalize_date,
            running_statuses=ANALYSIS_RUNNING_STATUSES,
        )
        return JSONResponse(result)
    except AnalysisPayloadError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AnalysisConflictError as e:
        conflict_date = None
        error_msg = str(e)
        if "date:" in error_msg:
            conflict_date = error_msg.split("date:")[-1].strip().strip("()")
        return JSONResponse(
            {"status": "conflict", "message": error_msg, "date": conflict_date},
            status_code=409,
        )
    except AnalysisServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/premarket-thesis/report")
def api_premarket_thesis_report(date: str | None = Query(None)) -> JSONResponse:
    """返回指定日期的盘前题材分析报告 JSON"""
    target_date = normalize_date(date) if date else datetime.now().strftime(DATE_FMT)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        data = get_report(REPORT_DIR, 'premarket_thesis', target_date)
    except ReportNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ReportUnreadableError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ReportInvalidTypeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ReportServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse(data)


@app.get("/api/premarket-thesis/status")
def api_premarket_thesis_status(date: str | None = Query(None)) -> JSONResponse:
    """返回盘前题材分析报告状态（是否存在 + 是否正在运行）"""
    target_date = normalize_date(date) if date else datetime.now().strftime(DATE_FMT)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        report_status = get_report_status(REPORT_DIR, 'premarket_thesis', target_date)

        # 获取运行状态
        thesis_status = read_analysis_status_service(PREMARKET_THESIS_STATUS_PATH)
        if thesis_status and thesis_status.get('date') == target_date:
            report_status['status'] = thesis_status.get('status', 'idle')
            report_status['progress'] = thesis_status.get('progress', 0)
            report_status['current_step'] = thesis_status.get('current_step', '')

        return JSONResponse(report_status)
    except ReportInvalidTypeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/premarket-thesis/history")
def api_premarket_thesis_history() -> JSONResponse:
    """返回盘前题材分析报告历史日期列表"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    pattern = "premarket_thesis_*.json"
    candidates = sorted(REPORT_DIR.glob(pattern), reverse=True)
    dates = []
    for path in candidates:
        match = path.stem.replace("premarket_thesis_", "")
        match = match.replace("_", "-")
        dates.append(match)
    return JSONResponse({"dates": dates})



# ─── 全 A 股补全 API ──────────────────────────────────────────────

@app.post("/api/backfill/run")
async def api_backfill_run(request: Request) -> JSONResponse:
    """手动触发全 A 股日线增量补全"""
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    if payload is None:
        payload = {}

    date = payload.get("date") or datetime.now().strftime("%Y-%m-%d")
    dry_run = bool(payload.get("dry_run", False))
    workers = payload.get("workers")

    try:
        from daily_incremental_backfill import run as run_daily_backfill
        result = run_daily_backfill(
            date=date,
            dry_run=dry_run,
            notify=True,
            workers=workers,
        )
        if isinstance(result, dict):
            return JSONResponse({"status": "ok", "result": result})
        else:
            return JSONResponse({"status": "error", "message": str(result)}, status_code=500)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── 板块数据库 API ──────────────────────────────────────────────

@app.get("/api/board/snapshots")
def api_board_snapshots(date: str | None = None, period: str | None = None) -> JSONResponse:
    """获取板块快照列表"""
    target_date = (date or datetime.now().strftime("%Y%m%d")).replace("-", "")
    snapshots = _get_board_snapshots(target_date, period)
    return JSONResponse({"date": target_date, "snapshots": snapshots})


@app.get("/api/board/stocks")
def api_board_stocks(
    date: str | None = None,
    board_code: str | None = None,
    period: str | None = None,
) -> JSONResponse:
    """获取板块成分股"""
    target_date = (date or datetime.now().strftime("%Y%m%d")).replace("-", "")
    if not board_code:
        return JSONResponse({"error": "board_code required"}, status_code=400)
    stocks = _get_board_stocks(target_date, board_code, period)
    return JSONResponse({"date": target_date, "board_code": board_code, "stocks": stocks})


@app.get("/api/board/history")
def api_board_history(board_code: str | None = None, days: int = 7) -> JSONResponse:
    """获取板块历史数据"""
    if not board_code:
        return JSONResponse({"error": "board_code required"}, status_code=400)
    history = _get_board_history(board_code, days)
    return JSONResponse({"board_code": board_code, "history": history})


if __name__ == "__main__":
    import uvicorn

    # 从配置读取端口，默认 18805
    try:
        from config import get_config
        port = int(get_config('web.port', 18805))
    except Exception:
        port = 18805

    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
