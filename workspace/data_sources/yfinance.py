# -*- coding: utf-8 -*-
"""Yahoo Finance 数据源接口 - 用于港股数据"""
from __future__ import annotations

import os
import time
from typing import Any

from .base import DataSourceError

# 代理配置：读取环境变量，yfinance 在国内必须显式传 proxy 才能走通
YF_PROXY = (
    os.environ.get("HTTP_PROXY")
    or os.environ.get("https_proxy")
    or os.environ.get("http_proxy")
    or None
)


# 周期映射（yfinance → 内部格式）
PERIOD_MAP = {
    "1min": "1m",
    "5min": "5m",
    "15min": "15m",
    "30min": "30m",
    "60min": "60m",
    "1h": "60m",
    "2h": "120m",
    "1d": "1d",
    "5d": "5d",
    "1wk": "1wk",
    "1mo": "1mo",
    "3mo": "3mo",
}

# yfinance 各周期最大范围
MAX_RANGE_MAP = {
    "1m": "7d",
    "5m": "60d",
    "15m": "60d",
    "30m": "60d",
    "60m": "730d",
    "120m": "730d",
    "1d": "max",
    "5d": "max",
    "1wk": "max",
    "1mo": "max",
    "3mo": "max",
}


def _to_yfinance_symbol(symbol: str, market: str = "HK") -> str:
    """转换为 yfinance 格式的股票代码"""
    symbol = str(symbol).strip()
    
    if market == "HK":
        # 港股：去掉前缀，添加 .HK
        pure = symbol
        if symbol.lower().startswith("hk"):
            pure = symbol[2:]
        if not pure.endswith(".HK"):
            pure = f"{pure}.HK"
        return pure
    
    elif market == "A":
        # A 股：添加 .SS（沪市）或 .SZ（深市）
        if symbol.lower().startswith("sh"):
            return f"{symbol[2:]}.SS"
        elif symbol.lower().startswith("sz"):
            return f"{symbol[2:]}.SZ"
        else:
            # 自动推断
            if symbol.startswith("6") or symbol.startswith("5"):
                return f"{symbol}.SS"
            else:
                return f"{symbol}.SZ"
    
    return symbol


def _bar_to_dict(bar: Any) -> dict | None:
    """将 yfinance 的 K 线数据转换为统一格式"""
    try:
        # yfinance 返回的是 DataFrame 的行
        if hasattr(bar, 'to_dict'):
            row = bar.to_dict()
        else:
            row = dict(bar)
        
        bar_time = str(row.get('Datetime', row.get('datetime', row.get('Date', ''))))
        if not bar_time:
            return None
        
        # 格式化时间
        if ' ' in bar_time:
            bar_time = bar_time.split(' ')[0]  # 只保留日期部分
        
        return {
            "bar_time": bar_time[:10],
            "open": round(float(row.get('Open', 0)), 3),
            "high": round(float(row.get('High', 0)), 3),
            "low": round(float(row.get('Low', 0)), 3),
            "close": round(float(row.get('Close', 0)), 3),
            "volume": int(row.get('Volume', 0)),
            "amount": round(float(row.get('Volume', 0)) * round(float(row.get('Close', 0)), 3), 3),  # 估算成交额
        }
    except Exception:
        return None


def fetch_hk_kline(symbol: str, period: str = "1d", count: int = 0) -> list[dict]:
    """获取港股 K 线数据（yfinance 源）
    
    Args:
        symbol: 股票代码（如 "01810"）
        period: 周期（1min/5min/15min/30min/60min/1d/1wk/1mo）
        count: 返回条数（0=不限制）
    
    Returns:
        K 线数据列表
    """
    import yfinance as yf
    
    yf_symbol = _to_yfinance_symbol(symbol, "HK")
    yf_period = PERIOD_MAP.get(period, "1d")
    yf_range = MAX_RANGE_MAP.get(yf_period, "max")
    
    try:
        ticker = yf.Ticker(yf_symbol, proxy=YF_PROXY)
        df = ticker.history(period=yf_range, interval=yf_period)
        
        if df.empty:
            return []
        
        # 转换为统一格式
        records = []
        for _, row in df.iterrows():
            bar = _bar_to_dict(row)
            if bar:
                records.append(bar)
        
        # 限流
        time.sleep(0.5)
        
        return records[-count:] if count > 0 else records
    
    except Exception as e:
        raise DataSourceError(f"yfinance 获取港股数据失败：{symbol} - {e}")


def fetch_hk_daily(symbol: str, count: int = 0) -> list[dict]:
    """获取港股日线数据"""
    return fetch_hk_kline(symbol, period="1d", count=count)


def fetch_hk_weekly(symbol: str, count: int = 0) -> list[dict]:
    """获取港股周线数据"""
    return fetch_hk_kline(symbol, period="1wk", count=count)


def fetch_hk_monthly(symbol: str, count: int = 0) -> list[dict]:
    """获取港股月线数据"""
    return fetch_hk_kline(symbol, period="1mo", count=count)


def fetch_hk_minute(symbol: str, period: str = "5min", count: int = 0) -> list[dict]:
    """获取港股分钟 K 线数据"""
    return fetch_hk_kline(symbol, period=period, count=count)
