# -*- coding: utf-8 -*-
"""
Market Data Service for Stock Monitor

This module provides core market data functionality for the /api/kline endpoint.
It encapsulates K-line data loading, MACD calculation, and payload construction.

Style: Lightweight functional module (not class-based).
"""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from database import get_db_path, list_db_dates, query_kline, query_kline_multi_days
from data_source import fetch_daily
from indicators import IndicatorEngine
from indicators.macd import MACD

# Default periods supported by the system
DEFAULT_PERIODS = ["1min", "5min", "15min", "30min", "60min", "daily"]

# Reference to project root - will be set by caller or default to parent of workspace
# This is intentionally left flexible to be overridden by server.py
_PROJECT_ROOT: Path | None = None


def set_project_root(root: Path) -> None:
    """Set the project root path. Optional - can be called by server.py to override default."""
    global _PROJECT_ROOT
    _PROJECT_ROOT = root


def _get_project_root() -> Path:
    """Get the project root path. Defaults to parent of workspace directory."""
    if _PROJECT_ROOT is not None:
        return _PROJECT_ROOT
    # Default: assume this file is at workspace/services/, so parent of workspace is project root
    return Path(__file__).resolve().parent.parent.parent


# =============================================================================
# Business Exceptions
# =============================================================================

class MarketDataError(Exception):
    """Base exception for market data operations."""
    pass


class MarketDataNotFoundError(MarketDataError):
    """Raised when requested market data is not found."""
    pass


# =============================================================================
# Core Helper Functions
# =============================================================================

def period_to_table(period: str) -> str:
    """
    Convert period string to database table name.
    
    Args:
        period: Period string (e.g., '1min', '5min', 'daily')
    
    Returns:
        Table name (e.g., 'kline_1min', 'kline_daily')
    
    Raises:
        MarketDataError: If period is not supported
    """
    if period not in DEFAULT_PERIODS:
        raise MarketDataError(f"Unsupported period: {period}. Valid periods: {DEFAULT_PERIODS}")
    if period == "daily":
        return "kline_daily"
    return f"kline_{period}"


def resolve_db_path(market: str, symbol: str, date: str) -> Path:
    """
    Resolve the database file path for a given market, symbol, and date.
    
    Args:
        market: Market identifier (e.g., 'HK', 'A')
        symbol: Stock symbol
        date: Date string in YYYY-MM-DD format
    
    Returns:
        Absolute path to the database file
    """
    project_root = _get_project_root()
    db_path = get_db_path(market, symbol, date)
    return project_root / db_path


def ensure_db(market: str, symbol: str, date: str) -> Path:
    """
    Ensure the database file exists for a given market, symbol, and date.
    
    Note: This function currently just resolves the path.
    The actual database generation logic remains in server.py for now.
    
    Args:
        market: Market identifier
        symbol: Stock symbol
        date: Date string
    
    Returns:
        Absolute path to the database file
    """
    db_path = resolve_db_path(market, symbol, date)
    if db_path.exists():
        return db_path
    # Database doesn't exist - caller should handle generation
    # For now, just return the path (generation logic stays in server.py for R3.2a)
    return db_path


def days_needed_for_macd(period: str) -> int:
    """
    Calculate how many days of historical data are needed for MACD calculation.
    
    MACD(12,26,9) requires at least 34 bars to converge, recommends 500+ bars
    to match East Money values.
    
    Args:
        period: K-line period (e.g., '1min', '5min', 'daily')
    
    Returns:
        Number of days to load
    """
    # Approximate bars per day for HK market (4-hour trading day)
    bars_per_day = {
        "1min": 240,
        "5min": 48,
        "15min": 16,
        "30min": 8,
        "60min": 4,
    }
    
    bars = bars_per_day.get(period, 4)
    
    # Target bar count: at least 500 bars for MACD convergence
    min_bars = 500
    days = min(120, max(30, min_bars // bars + 1))  # At least 30 days, max 120 days
    
    return days


def _iter_previous_dates(target_date: str, limit: int = 12) -> list[str]:
    """
    Generate a list of previous dates starting from target_date.
    
    Args:
        target_date: Starting date in YYYY-MM-DD format
        limit: Number of dates to generate
    
    Returns:
        List of date strings in YYYY-MM-DD format
    """
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    result = []
    for i in range(limit):
        result.append(dt.strftime("%Y-%m-%d"))
        dt = dt.fromordinal(dt.toordinal() - 1)
    return result


def _safe_number(value: Any) -> float:
    """
    Safely convert a value to a float, handling None, NaN, and Inf.
    
    Args:
        value: Value to convert
    
    Returns:
        Float value, or 0.0 if conversion fails or value is invalid
    """
    if value is None:
        return 0.0
    try:
        num = float(value)
        if math.isnan(num) or math.isinf(num):
            return 0.0
        return round(num, 6)
    except Exception:
        return 0.0


# =============================================================================
# Data Loading Functions
# =============================================================================

def load_multi_day_rows(
    market: str,
    symbol: str,
    period: str,
    target_date: str
) -> tuple[list[dict], list[dict]]:
    """
    Load multi-day K-line data for MACD calculation.
    
    Args:
        market: Market identifier
        symbol: Stock symbol
        period: K-line period
        target_date: Target date in YYYY-MM-DD format
    
    Returns:
        Tuple of (history_rows, target_rows) where:
        - history_rows: All historical data for MACD calculation
        - target_rows: Data for the target date only
    
    Raises:
        MarketDataError: If data loading fails
    """
    table = period_to_table(period)
    
    # Calculate how many days to load based on period
    days_to_load = days_needed_for_macd(period)
    
    # Get known database dates
    # Note: list_db_dates expects db_dir to be the data root (e.g., 'data' or absolute path to data dir)
    # We pass db_dir=None to use the default _DATA_ROOT from database.py
    known_dates = [
        d for d in list_db_dates(market, symbol, db_dir=None)
        if d <= target_date
    ]
    if target_date not in known_dates:
        known_dates.insert(0, target_date)
    known_dates = sorted(set(known_dates), reverse=True)
    
    # Use query_kline_multi_days to load historical data
    # Use db_dir='data' to match the _DATA_ROOT expected by database.py
    dates_to_query = list(reversed(known_dates[:days_to_load]))
    rows_via_api = query_kline_multi_days(
        market,
        symbol,
        table,
        dates_to_query,
        db_dir='data',
    )
    
    # Load data day by day, preserving real time order for MACD calculation
    history_rows: list[dict] = []
    
    # Build candidate date list: prioritize known dates, trace back if insufficient
    candidate_dates = []
    for date in known_dates:
        if date not in candidate_dates:
            candidate_dates.append(date)
    
    # Trace back if known dates are insufficient
    for date in _iter_previous_dates(target_date, limit=days_to_load):
        if date not in candidate_dates:
            candidate_dates.append(date)
    
    # Only take needed days
    candidate_dates = candidate_dates[:days_to_load]
    
    # Load data day by day
    for date in candidate_dates:
        db_path = resolve_db_path(market, symbol, date)
        if not db_path.exists():
            # Silently skip non-existent databases (fallback mechanism)
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
    
    # Sort by time
    history_rows.sort(key=lambda x: x["calc_time"])
    
    # Extract data for target date
    target_rows = [row for row in history_rows if row["date"] == target_date]
    
    # Fallback to API query result if target date has no data
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


# =============================================================================
# MACD Calculation Functions
# =============================================================================

def calc_macd_payload(
    history_rows: list[dict],
    target_rows: list[dict]
) -> tuple[list[dict], str, dict[str, int]]:
    """
    Calculate MACD payload from historical K-line data.
    
    Args:
        history_rows: Historical data for MACD calculation
        target_rows: Data for target date (for filtering results)
    
    Returns:
        Tuple of (macd_payload, data_status, data_info) where:
        - macd_payload: List of MACD data points
        - data_status: Data quality status ('low', 'medium', 'high')
        - data_info: Dict with 'bars', 'min', 'recommend' counts
    
    Raises:
        MarketDataNotFoundError: If no target data available
    """
    if not target_rows:
        raise MarketDataNotFoundError("No kline data found for target date")
    
    df = pd.DataFrame(
        history_rows,
        columns=["calc_time", "bar_time", "open", "high", "low", "close", "volume", "amount", "date"]
    )
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    
    engine = IndicatorEngine()
    macd_indicator = MACD(12, 26, 9)
    engine.register(macd_indicator)
    result = engine.calc_all(df)
    
    status = result.attrs.get("macd_data_status", "low")
    info = result.attrs.get("macd_data_info", {})
    
    # Filter results to target date only
    target_times = {(row["date"], row["bar_time"]) for row in target_rows}
    target_result = result[
        result.apply(lambda r: (r["date"], r["bar_time"]) in target_times, axis=1)
    ].copy()
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


def calc_daily_payload(
    market: str,
    symbol: str,
    target_date: str
) -> tuple[list[dict], list[dict], str, dict[str, int], float | None, float | None]:
    """
    Calculate daily K-line and MACD payload.
    
    Args:
        market: Market identifier
        symbol: Stock symbol
        target_date: Target date in YYYY-MM-DD format
    
    Returns:
        Tuple of (kline_payload, macd_payload, data_status, data_info, prev_close, today_close)
    
    Raises:
        MarketDataNotFoundError: If no daily data available
    """
    daily_rows = fetch_daily(symbol, "2025-01-01", target_date, 300, market=market)
    if not daily_rows:
        raise MarketDataNotFoundError(f"No daily kline data found for {symbol} {target_date}")
    
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
    
    df = pd.DataFrame(
        history_rows,
        columns=["calc_time", "bar_time", "open", "high", "low", "close", "volume", "amount", "date"]
    )
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


# =============================================================================
# Main API Entry Point
# =============================================================================

def get_kline_api_payload(
    market: str,
    symbol: str,
    period: str,
    target_date: str,
    name: str | None = None
) -> dict:
    """
    Build the complete payload for the /api/kline API endpoint.
    
    This is the main entry point for router/server integration.
    
    Args:
        market: Market identifier (e.g., 'HK', 'A')
        symbol: Stock symbol
        period: K-line period (e.g., '1min', '5min', 'daily')
        target_date: Target date in YYYY-MM-DD format
        name: Optional stock name (defaults to symbol if not provided)
    
    Returns:
        Dict with the complete API response structure including:
        - symbol, name, period, date, market
        - data_status, data_bars, data_min_bars, data_recommend_bars
        - kline, macd
        - prev_close, today_close
    
    Raises:
        MarketDataError: For unsupported periods or data errors
        MarketDataNotFoundError: If requested data is not found
    """
    if name is None:
        name = symbol
    
    market = str(market).upper().strip()
    symbol = str(symbol).strip()
    period = str(period).strip()
    
    # Validate period
    period_to_table(period)  # Will raise MarketDataError if invalid
    
    if period == "daily":
        # Daily K-line path
        kline_payload, macd_payload, data_status, data_info, prev_close, today_close = \
            calc_daily_payload(market, symbol, target_date)
        
        return {
            "symbol": symbol,
            "name": name,
            "period": period,
            "date": target_date,
            "market": market,
            "data_status": data_status,
            "data_bars": data_info["bars"],
            "data_min_bars": data_info["min"],
            "data_recommend_bars": data_info["recommend"],
            "kline": kline_payload,
            "macd": macd_payload,
            "prev_close": prev_close,
            "today_close": today_close,
        }
    
    # Non-daily path (intraday periods)
    # Note: This path requires database access and is not fully tested in smoke tests
    table = period_to_table(period)
    project_root = _get_project_root()
    
    # Get known database dates (use db_dir=None to use default _DATA_ROOT from database.py)
    known_dates = [d for d in list_db_dates(market, symbol, db_dir=None) if d <= target_date]
    
    # If target date has no data, fallback to the most recent date that has data for this period
    effective_date = target_date
    if target_date not in known_dates:
        if not known_dates:
            raise MarketDataNotFoundError(f"No historical data found for {market}{symbol}")
        # Find the most recent date that has data for the requested period
        for date in known_dates:
            db_path = resolve_db_path(market, symbol, date)
            if db_path.exists():
                try:
                    rows = query_kline(str(db_path), table)
                    if rows:
                        effective_date = date
                        break
                except Exception:
                    continue
        else:
            raise MarketDataNotFoundError(f"No data in {table} found for {market}{symbol}")
    
    db_path = ensure_db(market, symbol, effective_date)
    if not db_path.exists():
        raise MarketDataNotFoundError(f"Database not found: {db_path}")
    
    # Check if table has data
    current_rows = query_kline(str(db_path), table)
    if not current_rows:
        raise MarketDataNotFoundError(f"No data in {table} for {market}{symbol} {effective_date}")
    
    # Load multi-day data and calculate MACD (use effective_date if target_date has no data)
    history_rows, target_rows = load_multi_day_rows(market, symbol, period, effective_date)
    macd_payload, data_status, data_info = calc_macd_payload(history_rows, target_rows)
    
    # Build K-line payload for target date
    kline_payload = [
        {
            "time": str(row.get("bar_time", ""))[-5:],
            "open": _safe_number(row.get("open")),
            "high": _safe_number(row.get("high")),
            "low": _safe_number(row.get("low")),
            "close": _safe_number(row.get("close")),
            "volume": int(float(row.get("volume") or 0)),
        }
        for row in target_rows
    ]
    
    # Helper to get prev close
    def _get_prev_close(mkt: str, sym: str, tgt_date: str) -> float | None:
        dates = list_db_dates(mkt, sym, db_dir=None)  # Use default _DATA_ROOT from database.py
        prev_dates = [d for d in dates if d < tgt_date]
        if not prev_dates:
            try:
                daily = fetch_daily(sym, "2026-01-01", tgt_date, 5, market=mkt)
                if len(daily) >= 2:
                    return float(daily[-2]["close"])
            except Exception:
                pass
            return None
        
        prev_db = project_root / get_db_path(mkt, sym, prev_dates[0])
        if not prev_db.exists():
            return None
        
        try:
            rows = query_kline(str(prev_db), "kline_60min")
            if rows:
                return float(rows[-1]["close"])
        except Exception:
            pass
        return None
    
    # Helper to get today's close
    def _get_today_close(kline_data: list[dict]) -> float | None:
        if kline_data:
            return float(kline_data[-1]["close"])
        return None
    
    return {
        "symbol": symbol,
        "name": name,
        "period": period,
        "date": effective_date,  # Use effective_date (may differ from target_date if fallback)
        "market": market,
        "data_status": data_status,
        "data_bars": data_info["bars"],
        "data_min_bars": data_info["min"],
        "data_recommend_bars": max(data_info["recommend"], 105),
        "kline": kline_payload,
        "macd": macd_payload,
        "prev_close": _get_prev_close(market, symbol, target_date),
        "today_close": _get_today_close(kline_payload),
    }
