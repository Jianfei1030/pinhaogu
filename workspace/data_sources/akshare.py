# -*- coding: utf-8 -*-
"""A 股数据源接口（新浪 akshare 封装）"""
from __future__ import annotations

import os
import re
import time
from typing import Any
from datetime import datetime
from collections import defaultdict

from .base import DataSourceError
from .utils import _infer_a_prefix, _safe_float


def _disable_proxy_for_cn_api() -> dict:
    """临时禁用 HTTP/HTTPS 代理（国内数据源用）。返回旧代理配置供恢复用。"""
    proxy_vars = ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'NO_PROXY', 'no_proxy']
    saved = {}
    for var in proxy_vars:
        saved[var] = os.environ.get(var)
    os.environ['HTTP_PROXY'] = ''
    os.environ['HTTPS_PROXY'] = ''
    os.environ['no_proxy'] = '*.eastmoney.com,*.sina.com.cn,*.sinaimg.cn,*.gtimg.cn,localhost,127.0.0.1'
    os.environ['NO_PROXY'] = os.environ['no_proxy']
    return saved


def _restore_proxy(saved: dict) -> None:
    """恢复之前保存的代理配置。"""
    for var, old_val in saved.items():
        if old_val is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = old_val


def _sina_bar_to_dict(row) -> dict:
    """将 akshare stock_zh_a_daily（新浪源）的一行转为统一格式"""
    return {
        "bar_time": str(row["date"])[:10],
        "open": round(float(row["open"]), 3),
        "high": round(float(row["high"]), 3),
        "low": round(float(row["low"]), 3),
        "close": round(float(row["close"]), 3),
        "volume": int(row["volume"]),
        "amount": round(float(row["amount"]), 3),
        "turnover": round(float(row["turnover"]) * 100, 4) if "turnover" in row else None,
    }


def _fetch_a_kline_sina(symbol: str, count: int) -> list[dict]:
    """新浪 akshare stock_zh_a_daily（A 股唯一数据源）"""
    import akshare as ak
    
    saved_proxy = _disable_proxy_for_cn_api()
    
    prefix = _infer_a_prefix(symbol)
    pure = re.sub(r"^(?:sh|sz|bj)", "", symbol, flags=re.IGNORECASE)
    sina_symbol = f"{prefix}{pure}"
    
    try:
        df = ak.stock_zh_a_daily(symbol=sina_symbol, adjust="qfq")
        records = [_sina_bar_to_dict(row) for _, row in df.iterrows()]
        time.sleep(3)
        return records[-count:] if count else records
    finally:
        _restore_proxy(saved_proxy)


def fetch_a_daily(symbol: str, count: int = 0, with_indicators: bool = True) -> list[dict]:
    """获取 A 股日线数据（前复权），可选包含 MACD 和筹码分布指标。

    数据源：新浪 akshare stock_zh_a_daily（唯一源）。
    
    Args:
        symbol: 股票代码
        count: 返回条数（0=不限制）
        with_indicators: 是否计算 MACD 和筹码分布（默认 True）
    
    Returns:
        包含 K 线 + 指标的数据列表
    """
    fetch_count = max(count, 250) if count > 0 else 0
    
    records = _fetch_a_kline_sina(symbol, fetch_count)
    
    if not records or not with_indicators:
        return records[-count:] if count > 0 else records
    
    import pandas as pd
    from indicators.macd import MACD
    from calc_chip_dist import calc_chip_distribution
    
    df = pd.DataFrame(records)
    for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    macd = MACD()
    macd_result = macd.calc(df)
    
    chip_result = calc_chip_distribution(kline_data=records, use_real_turnover=True)
    
    enriched_records = []
    for i, row in enumerate(records):
        enriched = row.copy()
        if i < len(macd_result):
            enriched.update(_calc_macd_fields(macd_result, i))
        if i == len(records) - 1 and chip_result:
            enriched.update(_calc_chip_fields(chip_result))
        enriched_records.append(enriched)
    
    return enriched_records[-count:] if count > 0 else enriched_records


def _calc_macd_fields(df, index: int) -> dict:
    """计算指定索引位置的 MACD 字段"""
    if index < 0 or index >= len(df):
        return {}
    
    row = df.iloc[index]
    return {
        "dif": round(float(row.get("macd", 0)), 4),
        "dea": round(float(row.get("macd_dea", 0)), 4),
        "macd_hist": round(float(row.get("macd_hist", 0)), 4),
    }


def _calc_chip_fields(chip_result: dict) -> dict:
    """从筹码分布结果提取字段"""
    if not chip_result:
        return {}
    
    return {
        "profit_ratio": round(chip_result.get("profit_ratio", 0), 4),
        "avg_cost": round(chip_result.get("avg_cost", 0), 2),
        "concentration_90": round(chip_result.get("concentration_90", 0), 4),
        "cost_90_low": round(chip_result.get("cost_90_low", 0), 2),
        "cost_90_high": round(chip_result.get("cost_90_high", 0), 2),
    }


def _aggregate_period(daily_records: list[dict], period: str) -> list[dict]:
    """从日线数据聚合周线/月线"""
    if not daily_records:
        return []
    
    sorted_records = sorted(daily_records, key=lambda x: x['bar_time'])
    
    def get_period_key(record: dict) -> str:
        date = datetime.strptime(record['bar_time'], '%Y-%m-%d')
        if period == 'weekly':
            return f"{date.isocalendar()[0]}-W{date.isocalendar()[1]:02d}"
        else:
            return f"{date.year}-{date.month:02d}"
    
    groups = defaultdict(list)
    for record in sorted_records:
        key = get_period_key(record)
        groups[key].append(record)
    
    result = []
    for period_key in sorted(groups.keys()):
        bars = groups[period_key]
        if not bars:
            continue
        
        result.append({
            'bar_time': period_key,
            'open': bars[0]['open'],
            'high': max(b['high'] for b in bars),
            'low': min(b['low'] for b in bars),
            'close': bars[-1]['close'],
            'volume': sum(b['volume'] for b in bars),
            'amount': sum(b['amount'] for b in bars),
        })
    
    return result


def fetch_a_weekly(symbol: str, count: int = 0) -> list[dict]:
    """获取 A 股周线数据（从日线聚合）"""
    daily = fetch_a_daily(symbol, count=0, with_indicators=False)
    weekly = _aggregate_period(daily, 'weekly')
    return weekly[-count:] if count > 0 else weekly


def fetch_a_monthly(symbol: str, count: int = 0) -> list[dict]:
    """获取 A 股月线数据（从日线聚合）"""
    daily = fetch_a_daily(symbol, count=0, with_indicators=False)
    monthly = _aggregate_period(daily, 'monthly')
    return monthly[-count:] if count > 0 else monthly
